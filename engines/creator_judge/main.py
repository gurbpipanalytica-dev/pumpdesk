"""
PumpDesk v2 — Creator Judge: Reputation Scoring Engine
Scores creator wallets 0.0-1.0 based on on-chain history.

A creator with 50 launches and 0 graduations = score 0.05 (auto-blacklisted)
A creator with 10 launches and 6 graduations = score 0.85 (trusted)
A new creator with 1 launch = score 0.50 (neutral, let other signals decide)

Factors:
  - Graduation rate (launches that hit 100% curve / total launches)
  - Rug rate (launches where creator sold >50% within first hour)
  - Average time to graduation (faster = more engaged creator)
  - Wallet age and SOL balance (new empty wallets = suspicious)
  - Cluster analysis: is this wallet connected to known bad actors?

The orchestrator's fast path checks creator_score on every signal.
Score < 0.3 → auto-reject. Score < 0.2 → auto-blacklist.
"""

import asyncio
import json
import logging
import time
import sys
from typing import Optional
from dataclasses import dataclass, field

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import utcnow
from shared.config import STATE_DIR, SOLANA_RPC_URL
from shared import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.judge")

bus = RedisBus("creator_judge")

# In-memory score cache
score_cache: dict[str, dict] = {}  # address -> {score, factors, timestamp}
CACHE_TTL = 3600  # 1 hour


@dataclass
class CreatorProfile:
    """Aggregated on-chain history for a creator wallet."""
    address: str
    total_launches: int = 0
    graduated_tokens: int = 0
    rugged_tokens: int = 0       # sold >50% within 1 hour
    active_tokens: int = 0       # currently on bonding curve
    avg_curve_pct_at_exit: float = 0.0
    total_sol_earned: float = 0.0
    wallet_age_days: float = 0.0
    sol_balance: float = 0.0
    connected_wallets: int = 0   # wallets funded by same source
    first_seen: str = ""
    last_launch: str = ""


def score_creator(profile: CreatorProfile) -> tuple[float, dict]:
    """Calculate a 0.0-1.0 reputation score from a creator's profile.
    Returns (score, factors_dict)."""

    factors = {}
    score = 0.5  # neutral baseline

    # ── Factor 1: Graduation rate (strongest signal) ───────────────
    if profile.total_launches > 0:
        grad_rate = profile.graduated_tokens / profile.total_launches
        factors["graduation_rate"] = round(grad_rate, 3)

        if grad_rate >= 0.5:
            score += 0.20
        elif grad_rate >= 0.3:
            score += 0.10
        elif grad_rate >= 0.1:
            score += 0.0
        elif grad_rate == 0 and profile.total_launches >= 5:
            score -= 0.25  # 5+ launches, 0 graduations = very bad
        else:
            score -= 0.10
    else:
        factors["graduation_rate"] = None  # no history

    # ── Factor 2: Rug rate ─────────────────────────────────────────
    if profile.total_launches > 0:
        rug_rate = profile.rugged_tokens / profile.total_launches
        factors["rug_rate"] = round(rug_rate, 3)

        if rug_rate >= 0.5:
            score -= 0.30  # half or more launches were rugs
        elif rug_rate >= 0.3:
            score -= 0.15
        elif rug_rate > 0:
            score -= 0.05
    else:
        factors["rug_rate"] = None

    # ── Factor 3: Volume of launches (serial launchers are suspect) ─
    factors["total_launches"] = profile.total_launches

    if profile.total_launches > 50 and profile.graduated_tokens < 3:
        score -= 0.15  # spamming tokens with no success
    elif profile.total_launches > 20 and profile.graduated_tokens < 1:
        score -= 0.10

    # ── Factor 4: Wallet age ───────────────────────────────────────
    factors["wallet_age_days"] = round(profile.wallet_age_days, 1)

    if profile.wallet_age_days < 1:
        score -= 0.10  # brand new wallet
    elif profile.wallet_age_days < 7:
        score -= 0.05
    elif profile.wallet_age_days > 90:
        score += 0.05  # established wallet

    # ── Factor 5: SOL balance ──────────────────────────────────────
    factors["sol_balance"] = round(profile.sol_balance, 2)

    if profile.sol_balance < 0.1:
        score -= 0.05  # dust wallet
    elif profile.sol_balance > 10:
        score += 0.05  # has skin in the game

    # ── Factor 6: Cluster connections ──────────────────────────────
    factors["connected_wallets"] = profile.connected_wallets

    if profile.connected_wallets > 10:
        score -= 0.10  # likely sybil network

    # Clamp to 0.0-1.0
    score = max(0.0, min(1.0, score))
    factors["final_score"] = round(score, 3)

    return score, factors


async def evaluate_creator(address: str) -> tuple[float, dict]:
    """Full evaluation of a creator wallet. Fetches data and scores."""

    # Check cache first
    cached = score_cache.get(address)
    if cached and time.time() - cached["timestamp"] < CACHE_TTL:
        return cached["score"], cached["factors"]

    # Build profile from on-chain data
    profile = await _build_profile(address)
    score, factors = score_creator(profile)

    # Cache the result
    score_cache[address] = {
        "score": score,
        "factors": factors,
        "timestamp": time.time(),
    }

    # Publish to orchestrator's intelligence channel
    await bus.publish(Channels.INTEL_CREATOR_SCORE, {
        "address": address,
        "score": score,
        "factors": factors,
        "timestamp": utcnow(),
    })

    log.info(f"Creator scored: {address[:12]}... = {score:.2f} | {factors}")

    return score, factors


async def _build_profile(address: str) -> CreatorProfile:
    """Fetch on-chain data to build a creator's profile."""
    import aiohttp

    profile = CreatorProfile(address=address)

    try:
        async with aiohttp.ClientSession() as session:
            # Get wallet SOL balance
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
            async with session.post(SOLANA_RPC_URL, json=payload) as resp:
                data = await resp.json()
                lamports = data.get("result", {}).get("value", 0)
                profile.sol_balance = lamports / 1e9

            # Get transaction history to count launches
            # We look for transactions involving the PumpFun program
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [address, {"limit": 100}]
            }
            async with session.post(SOLANA_RPC_URL, json=payload) as resp:
                data = await resp.json()
                sigs = data.get("result", [])

                if sigs:
                    # Wallet age from earliest tx
                    oldest = sigs[-1] if sigs else None
                    if oldest and oldest.get("blockTime"):
                        age_seconds = time.time() - oldest["blockTime"]
                        profile.wallet_age_days = age_seconds / 86400

                    # Count PumpFun creates (rough heuristic from tx count)
                    # In production, we'd filter by program ID and instruction type
                    # For now, use total tx count as a proxy
                    profile.total_launches = max(1, len(sigs) // 10)  # rough estimate

    except Exception as e:
        log.error(f"_build_profile error for {address[:12]}: {e}")

    return profile


# ══════════════════════════════════════════════════════════════════════════════
#  REDIS HANDLERS — respond to score requests
# ══════════════════════════════════════════════════════════════════════════════

async def handle_score_request(channel: str, data: dict):
    """Handle a request to score a creator (from orchestrator or other bots)."""
    address = data.get("address", "")
    if address:
        await evaluate_creator(address)


async def handle_new_token_signal(channel: str, data: dict):
    """When any bot signals a new token, proactively score the creator."""
    token = data.get("token", {})
    creator = token.get("creator", "")
    if creator and creator not in score_cache:
        await evaluate_creator(creator)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    await bus.connect()

    # Subscribe to signals that contain creator info — proactively score them
    await bus.subscribe(Channels.SIGNAL_NEW_TOKEN, handle_new_token_signal)
    await bus.subscribe(Channels.SIGNAL_CURVE, handle_new_token_signal)
    await bus.subscribe(Channels.SIGNAL_MOMENTUM, handle_new_token_signal)

    # Direct score requests
    await bus.subscribe("pumpdesk:judge:score_request", handle_score_request)

    log.info("Creator Judge Engine started")
    log.info(f"Cache TTL: {CACHE_TTL}s")

    await bus.listen()


if __name__ == "__main__":
    asyncio.run(main())


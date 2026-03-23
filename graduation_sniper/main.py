"""
PumpDesk v2 — Graduation Sniper Bot (Bot 1)
Monitors PumpFun bonding curves and buys tokens at 85-95% completion,
right before they graduate to PumpSwap.

Our most unique strategy — least competition in this zone because:
  - Launch snipers focus on 0-5% curve (too early, most die)
  - Copy traders follow whales (crowded, adverse selection)
  - We target 85-95% where graduation is near-certain but price
    hasn't fully reflected the PumpSwap listing premium

Two scan modes:
  1. Discovery: subscribe to PumpFun creates, track ALL new tokens
  2. Focused: poll known tokens approaching graduation threshold

Signals published to orchestrator — we never execute directly.
"""

import asyncio
import json
import logging
import time
import sys

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import Signal, Token, utcnow
from shared.config import (
    STATE_DIR, SOLANA_WS_URL, PUMPFUN_PROGRAM_ID,
    ENABLE_SNIPER, MAX_POSITION_SOL
)

from curve_analyzer import CurveAnalyzer, CurveState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.sniper")

bus = RedisBus("graduation_sniper")
analyzer = CurveAnalyzer()

# Track tokens we're monitoring
# mint -> {bonding_curve, first_seen, last_checked, signaled}
tracked_tokens: dict = {}
MAX_TRACKED = 500

# Track tokens we've already signaled to avoid spam
signaled_mints: set = set()

SCAN_INTERVAL = 10  # seconds between curve checks
MIN_CURVE_PCT = 0.85
MAX_CURVE_PCT = 0.995  # don't buy if basically already graduated


async def on_new_token(mint: str, bonding_curve: str, creator: str, name: str = "", symbol: str = ""):
    """Called when a new PumpFun token is detected. Start light tracking."""
    if mint in tracked_tokens:
        return
    if len(tracked_tokens) >= MAX_TRACKED:
        # Evict oldest tokens below threshold
        _evict_stale_tokens()

    tracked_tokens[mint] = {
        "bonding_curve": bonding_curve,
        "creator": creator,
        "name": name,
        "symbol": symbol,
        "first_seen": time.time(),
        "last_checked": 0,
        "last_pct": 0,
    }


async def scan_tracked_tokens():
    """Periodically check all tracked tokens for graduation proximity."""
    while True:
        try:
            now = time.time()
            tokens_to_check = [
                (mint, info) for mint, info in tracked_tokens.items()
                if mint not in signaled_mints
                and now - info["last_checked"] > SCAN_INTERVAL
            ]

            if not tokens_to_check:
                await asyncio.sleep(2)
                continue

            for mint, info in tokens_to_check:
                try:
                    state = await analyzer.fetch_curve_state(info["bonding_curve"], mint)
                    if not state:
                        continue

                    info["last_checked"] = now
                    info["last_pct"] = state.curve_pct

                    # Check if this token is in our sweet spot
                    if state.curve_pct < MIN_CURVE_PCT:
                        continue
                    if state.curve_pct > MAX_CURVE_PCT:
                        continue
                    if state.graduated:
                        continue

                    should_buy, confidence, reason = analyzer.should_snipe(state)
                    if not should_buy:
                        continue

                    # Build and publish signal
                    await _publish_signal(state, info, confidence, reason)

                except Exception as e:
                    log.error(f"Error checking {mint[:12]}: {e}")

                # Small delay between checks to avoid RPC rate limits
                await asyncio.sleep(0.2)

        except Exception as e:
            log.error(f"scan_tracked_tokens error: {e}")

        await asyncio.sleep(1)


async def _publish_signal(state: CurveState, info: dict, confidence: float, reason: str):
    """Publish a graduation snipe signal to the orchestrator."""
    if state.mint in signaled_mints:
        return

    signaled_mints.add(state.mint)

    token = Token(
        mint=state.mint,
        name=info.get("name", ""),
        symbol=info.get("symbol", ""),
        creator=info.get("creator", state.creator),
        bonding_curve=state.bonding_curve,
        curve_pct=state.curve_pct,
        price_sol=state.price_sol,
        is_graduated=False,
    )

    vel = analyzer.get_velocity(state.mint)

    signal = Signal(
        signal_id=f"SIG-{int(time.time())}-sniper-{state.mint[:8]}",
        bot="graduation_sniper",
        signal_type="curve_progress",
        token=token,
        action="buy",
        confidence=confidence,
        size_sol=min(MAX_POSITION_SOL, 1.0),  # conservative default
        reason=f"Graduation snipe: {reason}",
        metadata={
            "curve_pct": state.curve_pct,
            "tokens_remaining": state.tokens_remaining,
            "real_sol_reserves": state.real_sol_reserves,
            "velocity_pct_per_min": vel.pct_per_minute if vel else 0,
            "est_minutes_to_grad": vel.est_minutes_to_graduation if vel else 0,
            "accelerating": vel.accelerating if vel else False,
        },
    )

    await bus.publish(Channels.SIGNAL_CURVE, json.loads(signal.to_json()))

    log.info(
        f"SIGNAL: {info.get('symbol', state.mint[:12])} | "
        f"curve={state.curve_pct:.1%} | "
        f"conf={confidence:.2f} | "
        f"{reason}"
    )


def _evict_stale_tokens():
    """Remove oldest tokens that haven't reached our threshold."""
    if len(tracked_tokens) < MAX_TRACKED:
        return
    # Sort by last_pct (lowest first) and remove bottom 20%
    sorted_mints = sorted(tracked_tokens.keys(), key=lambda m: tracked_tokens[m]["last_pct"])
    to_remove = sorted_mints[:MAX_TRACKED // 5]
    for mint in to_remove:
        del tracked_tokens[mint]


# ══════════════════════════════════════════════════════════════════════════════
#  TOKEN DISCOVERY — listen for new PumpFun creates
# ══════════════════════════════════════════════════════════════════════════════

async def token_discovery():
    """Subscribe to PumpFun program logs to discover new tokens."""
    import websockets

    while True:
        try:
            async with websockets.connect(SOLANA_WS_URL, ping_interval=30) as ws:
                log.info("Token discovery: connected to Solana WS")

                sub_msg = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": [PUMPFUN_PROGRAM_ID]},
                        {"commitment": "confirmed"}
                    ]
                }
                await ws.send(json.dumps(sub_msg))
                resp = await ws.recv()
                log.info("Token discovery: subscribed to PumpFun logs")

                async for message in ws:
                    try:
                        data = json.loads(message)
                        logs = data.get("params", {}).get("result", {}).get("value", {}).get("logs", [])
                        sig = data.get("params", {}).get("result", {}).get("value", {}).get("signature", "")

                        # Look for create instructions in logs
                        is_create = any("Program log: Instruction: Create" in l for l in logs)
                        if not is_create:
                            continue

                        # Fetch the full tx to extract mint and bonding curve
                        tx_info = await _fetch_create_tx(sig)
                        if tx_info:
                            await on_new_token(**tx_info)

                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        log.debug(f"Discovery message error: {e}")

        except Exception as e:
            log.warning(f"Token discovery error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)


async def _fetch_create_tx(signature: str) -> dict | None:
    """Fetch a PumpFun create transaction and extract token details."""
    import aiohttp
    from shared.config import SOLANA_RPC_URL

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTransaction",
                "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            }
            async with session.post(SOLANA_RPC_URL, json=payload) as resp:
                data = await resp.json()
                result = data.get("result")
                if not result:
                    return None

                tx = result.get("transaction", {})
                message = tx.get("message", {})
                accounts = message.get("accountKeys", [])

                if len(accounts) < 5:
                    return None

                # PumpFun create instruction account layout:
                # [0]=signer/creator, [1]=mint, [2]=bonding_curve, [3]=assoc_bonding_curve, ...
                # The exact indices depend on the instruction, but mint is typically index 1-3
                # We look for the new mint in post token balances
                post_balances = result.get("meta", {}).get("postTokenBalances", [])
                mint = ""
                for tb in post_balances:
                    m = tb.get("mint", "")
                    if m and m != "So11111111111111111111111111111111111111112":
                        mint = m
                        break

                if not mint:
                    return None

                creator = accounts[0] if accounts else ""

                # Find bonding curve from account list (it's a PDA derived from the mint)
                # For now, we'll need to derive it or find it in the accounts
                bonding_curve = accounts[2] if len(accounts) > 2 else ""

                return {
                    "mint": mint,
                    "bonding_curve": bonding_curve,
                    "creator": creator,
                    "name": "",
                    "symbol": "",
                }

    except Exception as e:
        log.debug(f"_fetch_create_tx error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  GRADUATION LISTENER — detect when tracked tokens graduate
# ══════════════════════════════════════════════════════════════════════════════

async def graduation_listener():
    """Monitor for graduation events on tokens we hold positions in."""
    while True:
        try:
            for mint, info in list(tracked_tokens.items()):
                if info["last_pct"] >= 0.99:
                    state = await analyzer.fetch_curve_state(info["bonding_curve"], mint)
                    if state and state.graduated:
                        await bus.publish(Channels.SIGNAL_GRADUATION, {
                            "mint": mint,
                            "symbol": info.get("symbol", ""),
                            "bonding_curve": info["bonding_curve"],
                            "timestamp": utcnow(),
                        })
                        log.info(f"GRADUATED: {info.get('symbol', mint[:12])}")
                        # Remove from tracked — it's now on PumpSwap
                        del tracked_tokens[mint]
                        break
        except Exception as e:
            log.error(f"graduation_listener error: {e}")

        await asyncio.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if not ENABLE_SNIPER:
        log.info("Graduation sniper disabled by config — exiting")
        return

    await bus.connect()

    log.info("Graduation Sniper Bot started")
    log.info(f"Target zone: {MIN_CURVE_PCT:.0%} - {MAX_CURVE_PCT:.1%}")
    log.info(f"Scan interval: {SCAN_INTERVAL}s")

    await asyncio.gather(
        token_discovery(),
        scan_tracked_tokens(),
        graduation_listener(),
        bus.listen(),
    )


if __name__ == "__main__":
    asyncio.run(main())


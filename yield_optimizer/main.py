"""
PumpDesk v2 — Yield Optimizer (Bot 10)
Treasury management bot. Every SOL not actively in a PumpFun trade
should be earning yield instead of sitting dead.

Strategy 1: Hedged JLP (primary)
  - Buy JLP (Jupiter Liquidity Provider token — $1.6B TVL)
  - JLP is a basket of SOL/BTC/ETH/USDC/USDT, earns perp trading fees
  - Hedge volatile exposure by shorting SOL/BTC/ETH on Drift Protocol
  - Net result: 15-30% APY with near-zero directional risk
  - Gauntlet manages $140M doing exactly this

Strategy 2: Lending rate arb (secondary)
  - Monitor rates across Kamino, MarginFi, Solend, Drift
  - Borrow where cheap, lend where expensive
  - Pocket the spread (typically 3-8% APY)
  - Rebalance when rates shift

The orchestrator tells this bot how much capital is "idle" and this bot
deploys it. When a trading bot needs capital for a new position,
this bot unwinds enough to free it up.
"""

import asyncio
import json
import logging
import time
import sys

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import utcnow
from shared.config import STATE_DIR, SOLANA_RPC_URL, PAPER_MODE
from shared import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.yield")

bus = RedisBus("yield_optimizer")

# ── STATE ───────────────────────────────────────────────────────────────────
state = {
    "strategy": "hedged_jlp",       # hedged_jlp | lending_arb | idle
    "deployed_sol": 0.0,             # SOL equivalent deployed in yield
    "jlp_balance": 0.0,              # JLP tokens held
    "hedge_positions": [],            # Drift short positions
    "lending_positions": [],          # borrow/lend positions
    "current_apy": 0.0,
    "total_yield_earned": 0.0,
    "last_rebalance": "",
}

# ── PROTOCOL ADDRESSES ──────────────────────────────────────────────────────
JLP_POOL = "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4"  # Jupiter JLP pool
DRIFT_PROGRAM = "dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH"

# ── RATE MONITORING ─────────────────────────────────────────────────────────
LENDING_PROTOCOLS = {
    "kamino": {"name": "Kamino", "url": "https://api.kamino.finance"},
    "marginfi": {"name": "MarginFi", "url": "https://api.marginfi.com"},
    "drift": {"name": "Drift", "url": "https://api.drift.trade"},
}

REBALANCE_INTERVAL = 300  # check rates every 5 min
MIN_SPREAD_APY = 0.02     # minimum 2% spread to bother with lending arb


async def deploy_to_jlp(sol_amount: float):
    """Deploy SOL into hedged JLP strategy."""
    if PAPER_MODE:
        state["deployed_sol"] += sol_amount
        state["jlp_balance"] += sol_amount * 0.95  # rough conversion
        state["strategy"] = "hedged_jlp"
        state["current_apy"] = 0.22  # ~22% APY typical
        log.info(f"PAPER: Deployed {sol_amount:.3f} SOL to hedged JLP | "
                 f"total={state['deployed_sol']:.3f} SOL | APY ~{state['current_apy']:.0%}")
        return

    # Live implementation:
    # 1. Swap SOL → JLP via Jupiter
    # 2. Open short SOL/BTC/ETH positions on Drift to hedge
    # 3. Track positions
    log.warning("Live JLP deployment not yet implemented")


async def withdraw_from_jlp(sol_amount: float):
    """Withdraw SOL from JLP strategy (when trading bot needs capital)."""
    if PAPER_MODE:
        actual = min(sol_amount, state["deployed_sol"])
        state["deployed_sol"] -= actual
        state["jlp_balance"] -= actual * 0.95
        log.info(f"PAPER: Withdrew {actual:.3f} SOL from JLP | "
                 f"remaining={state['deployed_sol']:.3f} SOL")
        return actual

    log.warning("Live JLP withdrawal not yet implemented")
    return 0


async def check_lending_rates() -> dict:
    """Fetch current borrow/lend rates across protocols."""
    import aiohttp
    rates = {}

    for protocol_id, info in LENDING_PROTOCOLS.items():
        try:
            # In production, each protocol has a different API
            # For now, simulate realistic rates
            if PAPER_MODE:
                import random
                rates[protocol_id] = {
                    "name": info["name"],
                    "usdc_lend_apy": round(random.uniform(0.05, 0.15), 4),
                    "usdc_borrow_apy": round(random.uniform(0.03, 0.12), 4),
                    "sol_lend_apy": round(random.uniform(0.02, 0.08), 4),
                    "sol_borrow_apy": round(random.uniform(0.01, 0.06), 4),
                }
        except Exception as e:
            log.debug(f"Failed to fetch rates from {protocol_id}: {e}")

    return rates


async def find_lending_arb(rates: dict) -> dict | None:
    """Find the best borrow-low/lend-high opportunity."""
    best_spread = 0
    best_arb = None

    protocols = list(rates.keys())
    for borrow_proto in protocols:
        for lend_proto in protocols:
            if borrow_proto == lend_proto:
                continue
            for asset in ["usdc", "sol"]:
                borrow_rate = rates[borrow_proto].get(f"{asset}_borrow_apy", 0)
                lend_rate = rates[lend_proto].get(f"{asset}_lend_apy", 0)
                spread = lend_rate - borrow_rate

                if spread > best_spread and spread >= MIN_SPREAD_APY:
                    best_spread = spread
                    best_arb = {
                        "asset": asset,
                        "borrow_from": borrow_proto,
                        "borrow_rate": borrow_rate,
                        "lend_to": lend_proto,
                        "lend_rate": lend_rate,
                        "spread": spread,
                    }

    return best_arb


# ══════════════════════════════════════════════════════════════════════════════
#  REDIS HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def handle_capital_available(channel: str, data: dict):
    """Orchestrator tells us idle capital is available — deploy it."""
    idle_sol = data.get("idle_sol", 0)
    if idle_sol > 0.1:
        await deploy_to_jlp(idle_sol)
        await bus.publish("pumpdesk:yield:status", {**state, "timestamp": utcnow()})


async def handle_capital_needed(channel: str, data: dict):
    """A trading bot needs capital — unwind some yield positions."""
    needed_sol = data.get("needed_sol", 0)
    if needed_sol > 0 and state["deployed_sol"] > 0:
        withdrawn = await withdraw_from_jlp(needed_sol)
        await bus.publish("pumpdesk:yield:withdrawn", {
            "amount_sol": withdrawn, "timestamp": utcnow()
        })


# ══════════════════════════════════════════════════════════════════════════════
#  REBALANCE LOOP
# ══════════════════════════════════════════════════════════════════════════════

async def rebalance_loop():
    """Periodically check rates and rebalance yield positions."""
    while True:
        try:
            rates = await check_lending_rates()
            arb = await find_lending_arb(rates)

            if arb:
                log.info(f"Lending arb found: borrow {arb['asset'].upper()} from {arb['borrow_from']} "
                         f"at {arb['borrow_rate']:.1%}, lend to {arb['lend_to']} at {arb['lend_rate']:.1%} "
                         f"= {arb['spread']:.1%} spread")

            # Publish status for dashboard
            await bus.publish("pumpdesk:yield:status", {
                **state,
                "lending_rates": rates,
                "best_arb": arb,
                "timestamp": utcnow(),
            })

            # Calculate yield earned (paper mode)
            if PAPER_MODE and state["deployed_sol"] > 0:
                interval_years = REBALANCE_INTERVAL / (365 * 24 * 3600)
                yield_earned = state["deployed_sol"] * state["current_apy"] * interval_years
                state["total_yield_earned"] += yield_earned

            state["last_rebalance"] = utcnow()

        except Exception as e:
            log.error(f"rebalance_loop error: {e}")

        await asyncio.sleep(REBALANCE_INTERVAL)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    await bus.connect()

    await bus.subscribe("pumpdesk:yield:deploy", handle_capital_available)
    await bus.subscribe("pumpdesk:yield:withdraw", handle_capital_needed)

    log.info(f"Yield Optimizer started | paper_mode={PAPER_MODE}")
    log.info(f"Primary strategy: hedged JLP (~22% APY)")
    log.info(f"Secondary: lending rate arb (min spread {MIN_SPREAD_APY:.0%})")

    await asyncio.gather(
        rebalance_loop(),
        bus.listen(),
    )


if __name__ == "__main__":
    asyncio.run(main())


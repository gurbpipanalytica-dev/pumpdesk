"""
PumpDesk v2 — Jito Backrun Arb Bot (Bot 8)
The money printer. Monitors the Solana mempool for large DEX trades,
calculates profitable backrun routes, executes via flashloan in Jito bundles.

How it works:
  1. Subscribe to Jito mempool (pending transactions stream)
  2. Filter for large DEX swaps (Raydium, Orca, PumpSwap, Meteora)
  3. Simulate the pending trade to find the price impact
  4. Calculate backrun arb routes (2-hop and 3-hop)
  5. If profitable: borrow via flashloan → execute arb → repay → tip validator
  6. All atomic in one Jito bundle — if arb fails, tx reverts, zero loss

This bot operates across ALL of Solana, not just PumpFun.
It prints money while the PumpFun bots wait for signals.

Based on Jito Labs' open-source reference: github.com/jito-labs/mev-bot
"""

import asyncio
import json
import logging
import time
import sys

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import utcnow
from shared.config import (
    STATE_DIR, SOLANA_WS_URL, JITO_BLOCK_ENGINE_URL,
    GEYSER_GRPC_URL, PAPER_MODE
)
from shared import db

from jito_backrunner.pool_tracker import PoolTracker, PoolState, DEX_PROGRAMS
from jito_backrunner.route_calculator import RouteCalculator, SOL_MINT, USDC_MINT
from jito_backrunner.flashloan import FlashloanExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.backrunner")

# ── COMPONENTS ──────────────────────────────────────────────────────────────
bus = RedisBus("jito_backrunner")
pool_tracker = PoolTracker()
route_calc = RouteCalculator(pool_tracker)
flashloan_exec = None  # initialized in main()

# ── STATS ───────────────────────────────────────────────────────────────────
stats = {
    "trades_scanned": 0,
    "backruns_found": 0,
    "backruns_executed": 0,
    "total_profit_sol": 0.0,
    "total_volume_sol": 0.0,
    "started_at": "",
}

# Minimum trade size worth backrunning (in SOL equivalent)
MIN_TRADE_SIZE_SOL = 1.0
# Maximum concurrent backrun attempts
MAX_CONCURRENT = 3
_semaphore = None


async def process_pending_trade(tx_data: dict):
    """Process a pending transaction from the mempool.
    If it's a large DEX trade, find and execute a backrun."""

    stats["trades_scanned"] += 1

    try:
        # Extract trade details from the pending transaction
        trade = _extract_dex_trade(tx_data)
        if not trade:
            return

        mint = trade["mint"]
        quote = trade["quote"]
        amount = trade["amount_quote"]
        direction = trade["direction"]
        signature = trade["signature"]

        # Skip tiny trades
        if amount < MIN_TRADE_SIZE_SOL:
            return

        log.debug(f"Large trade detected: {direction} {amount:.2f} {quote[:8]} of {mint[:12]}")

        # Find backrun route
        route = route_calc.find_backrun(mint, quote, amount, direction)
        if not route:
            return

        stats["backruns_found"] += 1

        # Execute via flashloan
        async with _semaphore:
            result = await flashloan_exec.execute_backrun(route, after_tx=signature)

        if result.success:
            stats["backruns_executed"] += 1
            stats["total_profit_sol"] += result.profit_net
            stats["total_volume_sol"] += result.borrowed

            # Publish to bus for dashboard
            await bus.publish("pumpdesk:mev:backrun_executed", {
                "route_type": route.route_type,
                "profit_net_sol": result.profit_net,
                "borrowed": result.borrowed,
                "hops": len(route.hops),
                "signature": result.signature,
                "bundle_id": result.bundle_id,
                "latency_ms": result.latency_ms,
                "paper": result.paper,
                "timestamp": utcnow(),
            })

            # Log to Supabase
            if db.is_available():
                db.log_trade({
                    "bot": "jito_backrunner",
                    "action": "backrun",
                    "size_sol": result.borrowed,
                    "pnl_sol": result.profit_net,
                    "signature": result.signature,
                    "paper": result.paper,
                    "metadata": {
                        "route_type": route.route_type,
                        "flashloan_fee": result.flashloan_fee,
                        "jito_tip": result.jito_tip,
                    },
                    "created_at": utcnow(),
                })

            log.info(
                f"BACKRUN OK: {route.route_type} | "
                f"net={result.profit_net:.6f} SOL | "
                f"borrowed={result.borrowed:.4f} | "
                f"total_profit={stats['total_profit_sol']:.6f} SOL | "
                f"{result.latency_ms:.1f}ms"
            )

    except Exception as e:
        log.error(f"process_pending_trade error: {e}")


def _extract_dex_trade(tx_data: dict) -> dict | None:
    """Extract DEX trade details from a pending transaction.
    Returns None if this isn't a DEX trade we care about."""
    try:
        # Check which program is being called
        message = tx_data.get("transaction", {}).get("message", {})
        account_keys = message.get("accountKeys", [])
        instructions = message.get("instructions", [])

        for ix in instructions:
            program_idx = ix.get("programIdIndex", -1)
            if program_idx < 0 or program_idx >= len(account_keys):
                continue
            program = account_keys[program_idx]

            # Check if this is a known DEX program
            dex_name = None
            for name, pid in DEX_PROGRAMS.items():
                if program == pid:
                    dex_name = name
                    break

            if not dex_name:
                continue

            # Simulate balance changes to determine trade size and direction
            # In production, we'd use simulateTransaction RPC call
            # For now, extract from account list heuristics
            signer = account_keys[0] if account_keys else ""

            return {
                "mint": "",  # extracted from simulation
                "quote": SOL_MINT,  # assume SOL for now
                "amount_quote": 0.0,  # from simulation
                "direction": "buy",
                "dex": dex_name,
                "signer": signer,
                "signature": tx_data.get("signature", ""),
            }

        return None

    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  MEMPOOL LISTENER
# ══════════════════════════════════════════════════════════════════════════════

async def mempool_listener():
    """Subscribe to Jito mempool for pending transactions.
    This is the core data source — we see trades BEFORE they land on-chain."""

    import websockets

    jito_ws = JITO_BLOCK_ENGINE_URL.replace("https://", "wss://").replace("http://", "ws://")
    mempool_url = f"{jito_ws}/api/v1/mempool"

    while True:
        try:
            log.info(f"Connecting to Jito mempool: {mempool_url}")
            async with websockets.connect(mempool_url, ping_interval=20) as ws:
                log.info("Jito mempool connected — scanning for backrun opportunities")

                # Subscribe to DEX program transactions
                subscribe_msg = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "subscribe",
                    "params": {
                        "programs": list(DEX_PROGRAMS.values()),
                    }
                }
                await ws.send(json.dumps(subscribe_msg))

                async for message in ws:
                    try:
                        data = json.loads(message)
                        txs = data.get("params", {}).get("result", {}).get("transactions", [])
                        for tx in txs:
                            asyncio.create_task(process_pending_trade(tx))
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            log.warning(f"Mempool connection error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
#  POOL STATE UPDATER
# ══════════════════════════════════════════════════════════════════════════════

async def pool_state_updater():
    """Keep pool reserves up to date via WebSocket account subscriptions."""
    import websockets

    while True:
        try:
            vaults = pool_tracker.get_all_vaults()
            if not vaults:
                log.info("No pool vaults to track yet — waiting 30s")
                await asyncio.sleep(30)
                continue

            async with websockets.connect(SOLANA_WS_URL, ping_interval=30) as ws:
                log.info(f"Subscribing to {len(vaults)} pool vault accounts")

                for vault in vaults[:100]:  # limit to 100 subscriptions
                    sub_msg = {
                        "jsonrpc": "2.0", "id": 1,
                        "method": "accountSubscribe",
                        "params": [vault, {"encoding": "jsonParsed", "commitment": "confirmed"}]
                    }
                    await ws.send(json.dumps(sub_msg))

                async for message in ws:
                    try:
                        data = json.loads(message)
                        result = data.get("params", {}).get("result", {})
                        value = result.get("value", {})
                        lamports = value.get("lamports", 0)
                        slot = result.get("context", {}).get("slot", 0)

                        # Update pool tracker with new balance
                        # In production, we'd map the subscription ID back to vault address
                        # For now, this is the framework
                    except Exception:
                        continue

        except Exception as e:
            log.warning(f"Pool updater error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
#  STATUS REPORTER
# ══════════════════════════════════════════════════════════════════════════════

async def status_reporter():
    """Periodically publish stats to Redis for the dashboard."""
    while True:
        await asyncio.sleep(30)
        pool_stats = pool_tracker.stats()
        await bus.publish("pumpdesk:mev:backrunner_status", {
            **stats,
            **pool_stats,
            "timestamp": utcnow(),
        })
        if stats["backruns_executed"] > 0:
            log.info(
                f"Stats: scanned={stats['trades_scanned']} | "
                f"found={stats['backruns_found']} | "
                f"executed={stats['backruns_executed']} | "
                f"profit={stats['total_profit_sol']:.6f} SOL"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    global flashloan_exec, _semaphore

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    stats["started_at"] = utcnow()

    # Initialize components
    from execution.solana_client import SolanaClient
    solana = SolanaClient()
    await solana.connect()

    flashloan_exec = FlashloanExecutor(solana, JITO_BLOCK_ENGINE_URL)

    await bus.connect()

    log.info("Jito Backrun Arb Bot started")
    log.info(f"Paper mode: {PAPER_MODE}")
    log.info(f"Min trade size: {MIN_TRADE_SIZE_SOL} SOL")
    log.info(f"Max concurrent: {MAX_CONCURRENT}")

    # Run all tasks concurrently
    await asyncio.gather(
        mempool_listener(),
        pool_state_updater(),
        status_reporter(),
        bus.listen(),
    )


if __name__ == "__main__":
    asyncio.run(main())


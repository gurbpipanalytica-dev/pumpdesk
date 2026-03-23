"""
PumpDesk v2 — Execution Engine Main
Listens for approved decisions from the orchestrator via Redis,
builds Solana transactions, submits via Jito bundles.
Reports results back to the bus.

This is the ONLY service that touches Solana wallets.
"""

import asyncio
import json
import logging
import sys
import time

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import Signal, Decision, Position, utcnow
from shared.config import STATE_DIR, PAPER_MODE
from shared import db

from execution.solana_client import SolanaClient
from execution.priority_fees import PriorityFeeManager
from execution.risk_manager import RiskManager
from execution.executor import JitoExecutor, TradeResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.execution")

# ── COMPONENTS ──────────────────────────────────────────────────────────────
bus = RedisBus("executor")
solana = SolanaClient()
fee_mgr = PriorityFeeManager(solana)
risk_mgr = RiskManager()
executor = JitoExecutor(solana, fee_mgr, risk_mgr)

# Position counter for unique IDs
_position_counter = 0


def next_position_id() -> str:
    global _position_counter
    _position_counter += 1
    return f"POS-{int(time.time())}-{_position_counter}"


# ══════════════════════════════════════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def handle_execute(channel: str, data: dict):
    """Handle an approved trade command from the orchestrator."""
    try:
        decision_data = data.get("decision", {})
        signal_data = data.get("signal", {})

        decision = Decision.from_json(json.dumps(decision_data))
        signal = Signal.from_json(json.dumps(signal_data))

        if signal.action == "buy":
            result = await executor.execute_buy(decision, signal)
            if result.success:
                await _create_position(signal, decision, result)
        elif signal.action == "sell":
            result = await executor.execute_sell(
                signal.token.mint,
                signal.metadata.get("amount_tokens", 0),
            )
            if result.success:
                await _report_tx(result, signal, "sell")
        else:
            log.warning(f"Unknown action: {signal.action}")
            return

        # Report result
        if result.success:
            await bus.publish(Channels.TX_CONFIRMED, {
                "signal_id": signal.signal_id,
                "decision_id": decision.decision_id,
                "signature": result.signature,
                "size_sol": result.size_sol,
                "latency_ms": result.latency_ms,
                "paper": result.paper,
                "timestamp": utcnow(),
            })
        else:
            await bus.publish(Channels.TX_FAILED, {
                "signal_id": signal.signal_id,
                "decision_id": decision.decision_id,
                "error": result.error,
                "timestamp": utcnow(),
            })

    except Exception as e:
        log.error(f"handle_execute error: {e}")


async def handle_exit(channel: str, data: dict):
    """Handle a progressive exit command — sell a portion of a position."""
    try:
        mint = data.get("mint", "")
        amount_tokens = data.get("amount_tokens", 0)
        urgency = data.get("urgency", "high")
        position_id = data.get("position_id", "")
        stage = data.get("stage", {})

        result = await executor.execute_sell(mint, amount_tokens, urgency=urgency)

        if result.success:
            await bus.publish(Channels.POSITION_PARTIAL, {
                "position_id": position_id,
                "mint": mint,
                "tokens_sold": amount_tokens,
                "signature": result.signature,
                "stage": stage,
                "paper": result.paper,
                "timestamp": utcnow(),
            })
            log.info(f"Exit stage executed: {position_id} | {amount_tokens:.0f} tokens | {mint[:12]}")
        else:
            log.error(f"Exit stage failed: {result.error}")

    except Exception as e:
        log.error(f"handle_exit error: {e}")


async def handle_emergency(channel: str, data: dict):
    """Handle emergency liquidation — sell everything NOW."""
    try:
        mint = data.get("mint", "")
        amount_tokens = data.get("amount_tokens", 0)
        position_id = data.get("position_id", "")

        log.warning(f"EMERGENCY EXIT: {position_id} | {mint[:12]} | {amount_tokens:.0f} tokens")

        result = await executor.execute_sell(mint, amount_tokens, urgency="critical")

        if result.success:
            await bus.publish(Channels.POSITION_EMERGENCY, {
                "position_id": position_id,
                "mint": mint,
                "tokens_sold": amount_tokens,
                "signature": result.signature,
                "paper": result.paper,
                "timestamp": utcnow(),
            })
        else:
            log.error(f"EMERGENCY EXIT FAILED: {result.error} — manual intervention needed")

    except Exception as e:
        log.error(f"handle_emergency error: {e}")


async def handle_launch(channel: str, data: dict):
    """Handle token launch command from the launcher bot."""
    try:
        result = await executor.execute_bundle_launch(data)
        status = "launched" if result.success else "failed"

        await bus.publish(Channels.LAUNCH_STATUS, {
            "status": status,
            "signature": result.signature,
            "error": result.error,
            "config": data,
            "paper": result.paper,
            "timestamp": utcnow(),
        })

        if result.success:
            log.info(f"Token launched: {data.get('symbol','?')} | sig={result.signature[:16]}...")
        else:
            log.error(f"Launch failed: {result.error}")

    except Exception as e:
        log.error(f"handle_launch error: {e}")


async def handle_volume(channel: str, data: dict):
    """Handle volume bot cycle — buy+sell same block."""
    try:
        mint = data.get("mint", "")
        sol_amount = data.get("sol_amount", 0.01)

        result = await executor.execute_volume_cycle(mint, sol_amount)

        if result.success:
            log.debug(f"Volume cycle: {mint[:12]} | {sol_amount:.4f} SOL")

    except Exception as e:
        log.error(f"handle_volume error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def _create_position(signal: Signal, decision: Decision, result: TradeResult):
    """Create a new Position and publish it to the bus."""
    pos = Position(
        position_id=next_position_id(),
        bot=signal.bot,
        mint=signal.token.mint,
        side="long",
        entry_price_sol=result.price_sol or signal.token.price_sol,
        size_tokens=result.size_tokens,
        size_sol=result.size_sol,
        current_price_sol=result.price_sol or signal.token.price_sol,
        exit_stages_remaining=decision.exit_plan.get("stages", []),
        status="open",
        tx_signatures=[result.signature],
    )

    await bus.publish(Channels.POSITION_OPENED, json.loads(pos.to_json()))

    if db.is_available():
        db.log_trade({
            "bot": signal.bot,
            "mint": signal.token.mint,
            "symbol": signal.token.symbol,
            "action": "buy",
            "size_sol": result.size_sol,
            "size_tokens": result.size_tokens,
            "price_sol": result.price_sol,
            "signature": result.signature,
            "paper": result.paper,
            "created_at": utcnow(),
        })

    log.info(f"Position created: {pos.position_id} | {signal.bot} | "
             f"{result.size_sol:.4f} SOL | {signal.token.symbol or signal.token.mint[:12]}")


async def _report_tx(result: TradeResult, signal: Signal, action: str):
    """Log a completed transaction."""
    if db.is_available():
        db.log_trade({
            "bot": signal.bot,
            "mint": signal.token.mint,
            "symbol": signal.token.symbol,
            "action": action,
            "size_sol": result.size_sol,
            "size_tokens": result.size_tokens,
            "price_sol": result.price_sol,
            "signature": result.signature,
            "paper": result.paper,
            "created_at": utcnow(),
        })


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    await bus.connect()
    await solana.connect()
    await executor.connect()

    # Subscribe to command channels
    await bus.subscribe(Channels.CMD_EXECUTE, handle_execute)
    await bus.subscribe(Channels.CMD_EXIT, handle_exit)
    await bus.subscribe(Channels.CMD_EMERGENCY, handle_emergency)
    await bus.subscribe(Channels.LAUNCH_CREATE, handle_launch)
    await bus.subscribe(Channels.VOLUME_CONTROL, handle_volume)

    log.info(f"Execution engine started | paper_mode={PAPER_MODE}")
    log.info("Listening for trade commands...")

    await bus.listen()


if __name__ == "__main__":
    asyncio.run(main())


"""
PumpDesk v2 — Orchestrator Main
The brain. Connects to Redis, receives signals from all bots,
runs fast path + signal correlation, publishes decisions,
runs slow path AI cycle periodically, serves API for dashboard.

This is the ONLY service that decides whether a trade happens.
"""

import asyncio
import json
import logging
import time
import threading
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import sys
sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import Signal, Decision, Position, utcnow
from shared.config import STATE_DIR, PAPER_MODE
from shared import db

from fast_path import FastPath, PortfolioState
from slow_path import SlowPath
from signal_correlator import SignalCorrelator

# ── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.orchestrator")

# ── STATE ───────────────────────────────────────────────────────────────────
portfolio = PortfolioState()
fast_path = FastPath(portfolio)
slow_path = SlowPath(portfolio)
correlator = SignalCorrelator(window_seconds=300)
bus = RedisBus("orchestrator")

# Dashboard WebSocket clients
ws_clients: list[WebSocket] = []

# ── FASTAPI ─────────────────────────────────────────────────────────────────
app = FastAPI(title="PumpDesk Orchestrator", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
#  REDIS SIGNAL HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def handle_signal(channel: str, data: dict):
    """Core handler: receives signal from any bot, runs fast path, publishes decision."""
    try:
        signal = Signal.from_json(json.dumps(data))
    except Exception as e:
        log.error(f"Failed to parse signal: {e}")
        return

    # Register in correlator
    correlator.add_signal(signal)

    # Get cross-signal context
    correlation = correlator.get_correlation(signal)

    # Boost confidence from correlation
    if correlation["confidence_boost"] != 0:
        original_conf = signal.confidence
        signal.confidence = min(1.0, max(0.0, signal.confidence + correlation["confidence_boost"]))
        if correlation["confidence_boost"] > 0:
            log.info(f"Confidence boosted: {original_conf:.2f} → {signal.confidence:.2f} "
                     f"(corroborated by {correlation['corroborating_bots']})")

    # Run fast path rules
    decision = fast_path.evaluate(signal)

    # Publish decision
    if decision.approved:
        await bus.publish(Channels.DECISION_APPROVE, json.loads(decision.to_json()))
        # Also publish execute command for the executor
        await bus.publish(Channels.CMD_EXECUTE, {
            "decision": json.loads(decision.to_json()),
            "signal": json.loads(signal.to_json()),
            "correlation": correlation,
        })
    else:
        await bus.publish(Channels.DECISION_REJECT, json.loads(decision.to_json()))

    # Push to dashboard WebSocket clients
    await broadcast_ws({
        "type": "decision",
        "data": json.loads(decision.to_json()),
        "signal_summary": {
            "bot": signal.bot,
            "token": signal.token.symbol or signal.token.mint[:12],
            "action": signal.action,
            "confidence": signal.confidence,
        },
        "correlation": correlation,
    })


async def handle_position_opened(channel: str, data: dict):
    """Track new position in portfolio state."""
    try:
        pos = Position.from_json(json.dumps(data))
        portfolio.open_positions[pos.position_id] = pos
        portfolio.total_exposure_sol += pos.size_sol
        portfolio.daily_trades += 1
        log.info(f"Position opened: {pos.bot} | {pos.mint[:12]} | {pos.size_sol:.3f} SOL")
        if db.is_available():
            db.upsert_position(json.loads(pos.to_json()))
    except Exception as e:
        log.error(f"handle_position_opened error: {e}")


async def handle_position_closed(channel: str, data: dict):
    """Remove closed position from portfolio state."""
    try:
        pos = Position.from_json(json.dumps(data))
        old = portfolio.open_positions.pop(pos.position_id, None)
        if old:
            portfolio.total_exposure_sol -= old.size_sol
        portfolio.daily_pnl_sol += pos.realized_pnl_sol
        if pos.realized_pnl_sol < 0:
            portfolio.daily_loss_sol += abs(pos.realized_pnl_sol)
        log.info(f"Position closed: {pos.bot} | {pos.mint[:12]} | PnL: {pos.realized_pnl_sol:+.4f} SOL")
        if db.is_available():
            db.upsert_position(json.loads(pos.to_json()))
    except Exception as e:
        log.error(f"handle_position_closed error: {e}")


async def handle_position_partial(channel: str, data: dict):
    """Update partially exited position."""
    try:
        pos = Position.from_json(json.dumps(data))
        portfolio.open_positions[pos.position_id] = pos
        log.info(f"Partial exit: {pos.bot} | {pos.mint[:12]} | realized: {pos.realized_pnl_sol:+.4f} SOL")
        if db.is_available():
            db.upsert_position(json.loads(pos.to_json()))
    except Exception as e:
        log.error(f"handle_position_partial error: {e}")


async def handle_intel_creator(channel: str, data: dict):
    """Cache creator reputation score from judge engine."""
    address = data.get("address", "")
    score = data.get("score", 0.5)
    portfolio.creator_scores[address] = score
    if score < 0.2:
        portfolio.blacklisted_creators.add(address)
        log.warning(f"Creator auto-blacklisted: {address[:12]} (score={score:.2f})")


async def handle_intel_hype(channel: str, data: dict):
    """Cache hype score from social aggregator."""
    mint = data.get("mint", "")
    score = data.get("score", 0.0)
    portfolio.hype_scores[mint] = score


async def handle_intel_grad(channel: str, data: dict):
    """Cache graduation probability from oracle."""
    mint = data.get("mint", "")
    prob = data.get("probability", 0.0)
    portfolio.grad_probabilities[mint] = prob


# ══════════════════════════════════════════════════════════════════════════════
#  WEBSOCKET — real-time dashboard feed
# ══════════════════════════════════════════════════════════════════════════════

async def broadcast_ws(data: dict):
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


# ══════════════════════════════════════════════════════════════════════════════
#  API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"ok": True, "time": utcnow(), "paper_mode": PAPER_MODE}


@app.get("/status")
async def status():
    return {
        "orchestrator_ok": True,
        "paper_mode": PAPER_MODE,
        "open_positions": len(portfolio.open_positions),
        "total_exposure_sol": round(portfolio.total_exposure_sol, 4),
        "daily_pnl_sol": round(portfolio.daily_pnl_sol, 4),
        "daily_trades": portfolio.daily_trades,
        "daily_loss_sol": round(portfolio.daily_loss_sol, 4),
        "creator_scores_cached": len(portfolio.creator_scores),
        "hype_scores_cached": len(portfolio.hype_scores),
        "blacklisted_creators": len(portfolio.blacklisted_creators),
        "latest_assessment": slow_path.get_latest_assessment(),
        "hot_tokens": correlator.get_hot_tokens(),
        "timestamp": utcnow(),
    }


@app.get("/positions")
async def get_positions():
    positions = [json.loads(p.to_json()) for p in portfolio.open_positions.values()]
    return {"positions": positions, "count": len(positions)}


@app.get("/trades")
async def get_trades(bot: str = None, limit: int = 50):
    trades = db.get_recent_trades(bot=bot, limit=limit)
    return {"trades": trades, "source": "supabase" if db.is_available() else "unavailable"}


@app.get("/assessment")
async def get_assessment():
    return slow_path.get_latest_assessment()


@app.get("/hot-tokens")
async def hot_tokens():
    return {"tokens": correlator.get_hot_tokens()}


@app.post("/blacklist/creator")
async def blacklist_creator(body: dict):
    address = body.get("address", "").strip()
    if address:
        portfolio.blacklisted_creators.add(address)
        log.info(f"Creator blacklisted via API: {address[:12]}")
        return {"ok": True, "blacklisted": address}
    return {"ok": False, "error": "address required"}


@app.post("/blacklist/token")
async def blacklist_token(body: dict):
    mint = body.get("mint", "").strip()
    if mint:
        portfolio.blacklisted_mints.add(mint)
        log.info(f"Token blacklisted via API: {mint[:12]}")
        return {"ok": True, "blacklisted": mint}
    return {"ok": False, "error": "mint required"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    log.info(f"Dashboard WS connected ({len(ws_clients)} clients)")
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        ws_clients.remove(ws)
        log.info(f"Dashboard WS disconnected ({len(ws_clients)} clients)")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN — startup
# ══════════════════════════════════════════════════════════════════════════════

async def redis_listener():
    """Connect to Redis and subscribe to all relevant channels."""
    await bus.connect()

    # Subscribe to all signal channels
    for ch in [
        Channels.SIGNAL_NEW_TOKEN, Channels.SIGNAL_CURVE, Channels.SIGNAL_WHALE,
        Channels.SIGNAL_ARB, Channels.SIGNAL_MOMENTUM, Channels.SIGNAL_SOCIAL,
        Channels.SIGNAL_GRADUATION,
    ]:
        await bus.subscribe(ch, handle_signal)

    # Subscribe to position updates
    await bus.subscribe(Channels.POSITION_OPENED, handle_position_opened)
    await bus.subscribe(Channels.POSITION_CLOSED, handle_position_closed)
    await bus.subscribe(Channels.POSITION_PARTIAL, handle_position_partial)
    await bus.subscribe(Channels.POSITION_EMERGENCY, handle_position_closed)

    # Subscribe to intelligence updates
    await bus.subscribe(Channels.INTEL_CREATOR_SCORE, handle_intel_creator)
    await bus.subscribe(Channels.INTEL_HYPE_SCORE, handle_intel_hype)
    await bus.subscribe(Channels.INTEL_GRAD_PROB, handle_intel_grad)

    log.info("All Redis subscriptions active")
    await bus.listen()


async def slow_path_loop():
    """Run Claude AI strategic assessment every N seconds."""
    await asyncio.sleep(60)  # wait for system to stabilize
    while True:
        try:
            result = slow_path.run_cycle()
            await broadcast_ws({"type": "assessment", "data": result})
            if db.is_available():
                db.save_snapshot({
                    "type": "ai_assessment",
                    "data": result,
                    "created_at": utcnow(),
                })
        except Exception as e:
            log.error(f"Slow path error: {e}")
        await asyncio.sleep(slow_path.interval_seconds)


async def startup():
    """Start Redis listener and slow path as background tasks."""
    asyncio.create_task(redis_listener())
    asyncio.create_task(slow_path_loop())
    log.info("PumpDesk Orchestrator v2 started")
    log.info(f"Paper mode: {PAPER_MODE}")


app.add_event_handler("startup", startup)


if __name__ == "__main__":
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("PumpDesk Orchestrator v2 — port 8765")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")


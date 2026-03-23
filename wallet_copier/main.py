"""
PumpDesk v2 — Wallet Copier Bot (Bot 2)
Monitors profitable Solana wallets in real-time, detects their PumpFun/PumpSwap
trades, and publishes copy signals to the orchestrator.

Two modes:
  1. WebSocket (default) — subscribe to wallet transactions via Solana WS
  2. Geyser gRPC (advanced) — sub-slot latency via Yellowstone, for when speed matters

This bot does NOT execute trades. It only generates signals.
The orchestrator decides go/no-go. The executor handles Solana transactions.
"""

import asyncio
import json
import logging
import time
import sys
import websockets
from typing import Optional

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import Signal, Token, utcnow
from shared.config import (
    STATE_DIR, SOLANA_WS_URL, GEYSER_GRPC_URL,
    ENABLE_COPIER, PUMPFUN_PROGRAM_ID
)

from wallet_registry import WalletRegistry, TrackedWallet
from tx_parser import parse_transaction, ParsedTrade

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.copier")

bus = RedisBus("wallet_copier")
registry = WalletRegistry()

# Track recently seen trades to avoid duplicates
_seen_signatures: set = set()
_MAX_SEEN = 5000


async def on_wallet_trade(trade: ParsedTrade):
    """Called when a tracked wallet makes a trade. Build and publish a signal."""

    # Dedup check
    if trade.signature in _seen_signatures:
        return
    _seen_signatures.add(trade.signature)
    if len(_seen_signatures) > _MAX_SEEN:
        _seen_signatures.clear()

    wallet = registry.get(trade.wallet)
    if not wallet:
        return

    # Update stats
    registry.update_trade_seen(trade.wallet)

    # Check if we should copy this wallet right now
    if not wallet.should_copy():
        log.info(f"Skipping {wallet.name or trade.wallet[:12]} — copy disabled or limits hit")
        return

    # Skip if trade is too small
    if trade.sol_amount < wallet.min_copy_sol:
        log.debug(f"Skipping tiny trade: {trade.sol_amount:.4f} SOL < min {wallet.min_copy_sol}")
        return

    # Only copy buys (for now — sell copies are tricky because we need to own the token)
    if trade.action not in ("buy",):
        log.info(f"Whale {wallet.name or trade.wallet[:12]} SOLD {trade.token_amount:.0f} tokens "
                 f"({trade.mint[:12]}) — not copying sells")
        return

    # Optional delay to avoid detection
    if wallet.copy_delay_seconds > 0:
        await asyncio.sleep(wallet.copy_delay_seconds)

    # Build token object
    token = Token(
        mint=trade.mint,
        creator="",  # we don't know creator from the trade
        bonding_curve=trade.bonding_curve,
        price_sol=trade.sol_amount / max(trade.token_amount, 1) if trade.token_amount > 0 else 0,
        is_graduated=(trade.platform == "pumpswap"),
    )

    # Build signal
    # Confidence is based on wallet's historical performance
    confidence = 0.5  # base
    if wallet.win_rate > 0.6:
        confidence = 0.7
    if wallet.win_rate > 0.75:
        confidence = 0.85
    if wallet.total_trades_copied < 5:
        confidence = 0.5  # not enough data yet

    signal = Signal(
        signal_id=f"SIG-{int(time.time())}-copier-{trade.wallet[:8]}",
        bot="wallet_copier",
        signal_type="whale_trade",
        token=token,
        action="buy",
        confidence=confidence,
        size_sol=min(wallet.copy_size_sol, wallet.max_copy_sol),
        reason=f"Whale {wallet.name or trade.wallet[:12]} bought {trade.sol_amount:.3f} SOL of {trade.mint[:12]}",
        metadata={
            "source_wallet": trade.wallet,
            "source_wallet_name": wallet.name,
            "source_sol_amount": trade.sol_amount,
            "source_token_amount": trade.token_amount,
            "source_signature": trade.signature,
            "platform": trade.platform,
            "wallet_win_rate": wallet.win_rate,
            "wallet_total_copies": wallet.total_trades_copied,
        },
    )

    # Publish to orchestrator
    await bus.publish(Channels.SIGNAL_WHALE, json.loads(signal.to_json()))

    log.info(
        f"SIGNAL: {wallet.name or trade.wallet[:12]} bought {trade.sol_amount:.3f} SOL "
        f"of {trade.mint[:12]} on {trade.platform} | "
        f"conf={confidence:.2f} | copy_size={wallet.copy_size_sol:.2f} SOL"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SOLANA WEBSOCKET MONITOR
# ══════════════════════════════════════════════════════════════════════════════

async def ws_monitor():
    """Monitor tracked wallets via Solana WebSocket accountSubscribe.
    Reconnects automatically on disconnect."""

    addresses = registry.get_all_addresses()
    if not addresses:
        log.warning("No wallets configured — copier idle")
        return

    copyable = registry.get_copyable()
    log.info(f"Monitoring {len(addresses)} wallets ({len(copyable)} copy-enabled)")

    while True:
        try:
            async with websockets.connect(SOLANA_WS_URL, ping_interval=30) as ws:
                log.info(f"WebSocket connected: {SOLANA_WS_URL}")

                # Subscribe to each wallet's transactions using logsSubscribe
                # This catches all transactions that mention the PumpFun program
                # and filter by wallet in our parser
                sub_id = None
                subscribe_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": [PUMPFUN_PROGRAM_ID]},
                        {"commitment": "confirmed"}
                    ]
                }
                await ws.send(json.dumps(subscribe_msg))
                resp = await ws.recv()
                resp_data = json.loads(resp)
                sub_id = resp_data.get("result")
                log.info(f"Subscribed to PumpFun logs (sub_id={sub_id})")

                # Listen for transactions
                watched = set(addresses)
                async for message in ws:
                    try:
                        data = json.loads(message)
                        params = data.get("params", {})
                        result = params.get("result", {})
                        value = result.get("value", {})

                        # Check if any of our watched wallets are in the logs
                        logs = value.get("logs", [])
                        signature = value.get("signature", "")

                        if not signature or signature in _seen_signatures:
                            continue

                        # Check if any watched address appears in the logs
                        log_text = " ".join(logs)
                        relevant_wallet = None
                        for addr in watched:
                            if addr in log_text:
                                relevant_wallet = addr
                                break

                        if not relevant_wallet:
                            continue

                        # Fetch full transaction for parsing
                        # (logsSubscribe doesn't give us the full tx data)
                        tx_data = await _fetch_transaction(signature)
                        if not tx_data:
                            continue

                        trade = parse_transaction(tx_data, watched)
                        if trade:
                            await on_wallet_trade(trade)

                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        log.error(f"WS message error: {e}")

        except websockets.ConnectionClosed:
            log.warning("WebSocket disconnected — reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            log.error(f"WebSocket error: {e} — reconnecting in 10s...")
            await asyncio.sleep(10)


async def _fetch_transaction(signature: str) -> Optional[dict]:
    """Fetch full transaction data via RPC for parsing."""
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
                if result:
                    result["signature"] = signature
                return result
    except Exception as e:
        log.debug(f"Failed to fetch tx {signature[:16]}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  REDIS COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def handle_add_wallet(channel: str, data: dict):
    """Add a new wallet to track (from dashboard or API)."""
    wallet = TrackedWallet(
        address=data.get("address", ""),
        name=data.get("name", ""),
        copy_enabled=data.get("copy_enabled", True),
        copy_size_sol=data.get("copy_size_sol", 0.5),
        source=data.get("source", "manual"),
        added_at=utcnow(),
    )
    if wallet.address:
        registry.add(wallet)


async def handle_remove_wallet(channel: str, data: dict):
    """Remove a wallet from tracking."""
    address = data.get("address", "")
    if address:
        registry.remove(address)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if not ENABLE_COPIER:
        log.info("Wallet copier disabled by config — exiting")
        return

    await bus.connect()

    # Listen for wallet management commands
    await bus.subscribe("pumpdesk:copier:add_wallet", handle_add_wallet)
    await bus.subscribe("pumpdesk:copier:remove_wallet", handle_remove_wallet)

    log.info("Wallet Copier Bot started")
    log.info(f"Tracked wallets: {len(registry.wallets)}")
    log.info(f"Copy-enabled: {len(registry.get_copyable())}")

    # Run WebSocket monitor and Redis listener concurrently
    await asyncio.gather(
        ws_monitor(),
        bus.listen(),
    )


if __name__ == "__main__":
    asyncio.run(main())


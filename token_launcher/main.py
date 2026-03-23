"""
PumpDesk v2 — Token Launcher Bot (Bot 5)
Creates PumpFun tokens and executes bundled launches via Jito.

The full launch flow:
  1. User submits LaunchConfig via dashboard (name, symbol, image, socials)
  2. Launcher validates config and prepares bundle wallets
  3. Distributes SOL from treasury to dev wallet + bundle wallets
  4. Builds atomic Jito bundle:
     - TX 0: Create token on PumpFun (dev wallet = creator)
     - TX 1: Dev wallet buys (sets initial position)
     - TX 2-N: Bundle wallets buy (simulates organic demand)
  5. Submits bundle to Jito block engine
  6. On success: starts graduation monitor, optionally enables volume bot
  7. Tracks token through lifecycle → graduation → creator fee revenue

Revenue model:
  - Pre-graduation: sell bundled positions for profit on rising curve
  - Post-graduation: creator fees (0.3% min → 0.95% max at 420 SOL mcap)
  - A graduated token with 100 SOL daily volume = 0.3-0.95 SOL/day passive income

Channels:
  LAUNCH_CREATE → this bot (from dashboard)
  LAUNCH_STATUS → dashboard (from this bot)
  LAUNCH_GRADUATED → orchestrator + dashboard
  VOLUME_CONTROL → volume_bot
"""

import asyncio
import json
import logging
import time
import sys

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import LaunchConfig, utcnow
from shared.config import STATE_DIR, PAPER_MODE, PUMPFUN_PROGRAM_ID

from wallet_manager import WalletManager
from graduation_monitor import GraduationMonitor, LaunchedToken

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.launcher")

bus = RedisBus("token_launcher")
wallets = WalletManager()
monitor = GraduationMonitor(bus)

# Stats
stats = {
    "total_launches": 0,
    "successful_launches": 0,
    "graduated_tokens": 0,
    "total_sol_invested": 0.0,
    "total_creator_fees": 0.0,
}


async def handle_launch_request(channel: str, data: dict):
    """Handle a token launch request from the dashboard."""
    try:
        config = LaunchConfig(**data)
        log.info(f"Launch request: {config.symbol} ({config.name})")
        log.info(f"  Dev buy: {config.dev_buy_sol} SOL | "
                 f"Bundle: {config.bundle_wallets} wallets × {config.bundle_sol_per_wallet} SOL | "
                 f"Total: {config.total_sol_cost():.3f} SOL")

        # Validate
        errors = _validate_config(config)
        if errors:
            await bus.publish(Channels.LAUNCH_STATUS, {
                "status": "error",
                "errors": errors,
                "config": data,
                "timestamp": utcnow(),
            })
            return

        # Prepare wallets
        dev_wallet = wallets.get_dev_wallet()
        bundle_wallet_list = wallets.get_available(config.bundle_wallets)

        if not dev_wallet or len(bundle_wallet_list) < config.bundle_wallets:
            await bus.publish(Channels.LAUNCH_STATUS, {
                "status": "error",
                "errors": ["Insufficient bundle wallets"],
                "timestamp": utcnow(),
            })
            return

        # Publish preparing status
        await bus.publish(Channels.LAUNCH_STATUS, {
            "status": "preparing",
            "symbol": config.symbol,
            "dev_wallet": dev_wallet.address[:12],
            "bundle_wallets": len(bundle_wallet_list),
            "total_cost": config.total_sol_cost(),
            "timestamp": utcnow(),
        })

        # Execute the launch
        result = await _execute_launch(config, dev_wallet, bundle_wallet_list)

        if result["success"]:
            stats["total_launches"] += 1
            stats["successful_launches"] += 1
            stats["total_sol_invested"] += config.total_sol_cost()

            # Record wallet usage
            all_addrs = [dev_wallet.address] + [w.address for w in bundle_wallet_list]
            wallets.record_launch(all_addrs, config.bundle_sol_per_wallet)

            # Start monitoring
            launched = LaunchedToken(
                mint=result.get("mint", ""),
                symbol=config.symbol,
                name=config.name,
                creator_wallet=dev_wallet.address,
                bonding_curve=result.get("bonding_curve", ""),
                dev_buy_sol=config.dev_buy_sol,
                bundle_wallets=config.bundle_wallets,
                total_sol_invested=config.total_sol_cost(),
                created_at=utcnow(),
            )
            monitor.add_token(launched)

            # Enable volume bot if requested
            if config.enable_volume_bot:
                await bus.publish(Channels.VOLUME_CONTROL, {
                    "mint": result.get("mint", ""),
                    "symbol": config.symbol,
                    "action": "start",
                    "intensity": config.volume_bot_intensity,
                    "reason": "launch_config",
                })

            await bus.publish(Channels.LAUNCH_STATUS, {
                "status": "launched",
                "symbol": config.symbol,
                "mint": result.get("mint", ""),
                "signature": result.get("signature", ""),
                "total_cost": config.total_sol_cost(),
                "paper": result.get("paper", False),
                "timestamp": utcnow(),
            })

            log.info(f"LAUNCHED: {config.symbol} | mint={result.get('mint', '')[:12]} | "
                     f"cost={config.total_sol_cost():.3f} SOL | "
                     f"paper={result.get('paper', False)}")

        else:
            stats["total_launches"] += 1
            await bus.publish(Channels.LAUNCH_STATUS, {
                "status": "failed",
                "symbol": config.symbol,
                "error": result.get("error", "Unknown"),
                "timestamp": utcnow(),
            })
            log.error(f"LAUNCH FAILED: {config.symbol} — {result.get('error')}")

    except Exception as e:
        log.error(f"handle_launch_request error: {e}")
        await bus.publish(Channels.LAUNCH_STATUS, {
            "status": "error",
            "errors": [str(e)],
            "timestamp": utcnow(),
        })


async def _execute_launch(config: LaunchConfig, dev_wallet, bundle_wallets) -> dict:
    """Build and submit the launch bundle."""

    if PAPER_MODE:
        fake_mint = f"PAPER-MINT-{config.symbol}-{int(time.time())}"
        fake_bc = f"PAPER-BC-{config.symbol}-{int(time.time())}"
        log.info(f"PAPER LAUNCH: {config.symbol} | {config.bundle_wallets + 1} wallets | "
                 f"{config.total_sol_cost():.3f} SOL")
        return {
            "success": True,
            "mint": fake_mint,
            "bonding_curve": fake_bc,
            "signature": f"PAPER-SIG-{int(time.time())}",
            "paper": True,
        }

    # ── LIVE MODE ──────────────────────────────────────────────────
    # This sends the launch config to the execution engine which handles
    # actual Jito bundle construction and submission
    try:
        launch_data = {
            "name": config.name,
            "symbol": config.symbol,
            "description": config.description,
            "image_url": config.image_url,
            "twitter": config.twitter,
            "telegram": config.telegram,
            "website": config.website,
            "dev_wallet": dev_wallet.address,
            "dev_keypair": dev_wallet.keypair_path,
            "dev_buy_sol": config.dev_buy_sol,
            "bundle_wallets": [
                {"address": w.address, "keypair": w.keypair_path, "sol": config.bundle_sol_per_wallet}
                for w in bundle_wallets
            ],
            "anti_sniper_mode": config.enable_anti_sniper_mode,
        }

        # Send to executor via Redis
        await bus.publish(Channels.LAUNCH_CREATE, launch_data)

        # Wait for confirmation (with timeout)
        # In production, this would use a response channel
        log.info("Launch bundle submitted to executor — awaiting confirmation")
        return {"success": True, "mint": "", "signature": "pending"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _validate_config(config: LaunchConfig) -> list:
    """Validate launch configuration."""
    errors = []
    if not config.name or len(config.name) < 2:
        errors.append("Token name too short")
    if not config.symbol or len(config.symbol) < 2:
        errors.append("Token symbol too short")
    if len(config.symbol) > 10:
        errors.append("Token symbol too long (max 10)")
    if config.dev_buy_sol < 0.01:
        errors.append("Dev buy too small (min 0.01 SOL)")
    if config.dev_buy_sol > 10:
        errors.append("Dev buy too large (max 10 SOL)")
    if config.bundle_wallets < 1:
        errors.append("Need at least 1 bundle wallet")
    if config.bundle_wallets > 20:
        errors.append("Max 20 bundle wallets")
    if config.bundle_sol_per_wallet < 0.01:
        errors.append("Bundle SOL per wallet too small (min 0.01)")
    if config.total_sol_cost() > 50:
        errors.append(f"Total cost too high: {config.total_sol_cost():.2f} SOL (max 50)")
    return errors


# ══════════════════════════════════════════════════════════════════════════════
#  MONITORING LOOP
# ══════════════════════════════════════════════════════════════════════════════

async def monitoring_loop():
    """Periodically check all launched tokens."""

    async def curve_fetcher(bc_addr, mint):
        """Fetch curve state — reuses graduation sniper's analyzer pattern."""
        import aiohttp
        from shared.config import SOLANA_RPC_URL
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getAccountInfo",
                    "params": [bc_addr, {"encoding": "base64"}]
                }
                async with session.post(SOLANA_RPC_URL, json=payload) as resp:
                    data = await resp.json()
                    result = data.get("result", {})
                    if not result or not result.get("value"):
                        return None

                    # Minimal curve state for monitoring
                    import base64, struct
                    raw = base64.b64decode(result["value"]["data"][0])
                    if len(raw) < 48:
                        return None
                    offset = 8
                    vt = struct.unpack_from('<Q', raw, offset)[0] / 1e6; offset += 8
                    vs = struct.unpack_from('<Q', raw, offset)[0] / 1e9; offset += 8
                    rt = struct.unpack_from('<Q', raw, offset)[0] / 1e6; offset += 8
                    complete = raw[40] if len(raw) > 40 else 0

                    from shared.config import BONDING_CURVE_SUPPLY

                    class _State:
                        pass
                    s = _State()
                    s.curve_pct = min(1.0, (BONDING_CURVE_SUPPLY - rt) / BONDING_CURVE_SUPPLY)
                    s.graduated = bool(complete) or s.curve_pct >= 1.0
                    return s
        except Exception:
            return None

    while True:
        try:
            if monitor.tokens:
                await monitor.check_all(curve_fetcher)
        except Exception as e:
            log.error(f"monitoring_loop error: {e}")
        await asyncio.sleep(15)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    await bus.connect()

    await bus.subscribe(Channels.LAUNCH_CREATE, handle_launch_request)

    log.info(f"Token Launcher started | paper_mode={PAPER_MODE}")
    log.info(f"Bundle wallets available: {len(wallets.wallets)}")

    await asyncio.gather(
        monitoring_loop(),
        bus.listen(),
    )


if __name__ == "__main__":
    asyncio.run(main())


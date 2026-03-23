"""
PumpDesk v2 — Volume Bot (Bot 6)
Anti-MEV same-block buy+sell for token visibility on PumpFun.

When we launch a token, it needs to appear on PumpFun's "trending" and
"recently active" lists to attract organic buyers. Volume = visibility.

How it works:
  - Receives VOLUME_CONTROL messages from token_launcher or dashboard
  - Executes buy+sell in the SAME Jito bundle (net zero position)
  - Because both legs are in one bundle, MEV bots can't sandwich us
  - Generates visible on-chain volume without directional risk
  - Uses rotating wallets from wallet_manager to look organic

Patterns:
  - "organic": random intervals (30-120s), random sizes (0.01-0.1 SOL)
  - "boost": frequent trades (10-30s), larger sizes — for stalled tokens
  - "stealth": very small trades, long intervals — maintains minimum activity
"""

import asyncio
import json
import logging
import time
import random
import sys

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import utcnow
from shared.config import STATE_DIR, PAPER_MODE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.volume")

bus = RedisBus("volume_bot")


PATTERNS = {
    "organic": {"interval_min": 30, "interval_max": 120, "size_min": 0.01, "size_max": 0.10},
    "boost":   {"interval_min": 10, "interval_max": 30,  "size_min": 0.05, "size_max": 0.20},
    "stealth": {"interval_min": 60, "interval_max": 300, "size_min": 0.005, "size_max": 0.03},
}


class ActiveVolume:
    """An active volume generation task for a specific token."""
    def __init__(self, mint: str, symbol: str, intensity: float, pattern: str = "organic"):
        self.mint = mint
        self.symbol = symbol
        self.intensity = max(0.1, min(1.0, intensity))
        self.pattern = pattern if pattern in PATTERNS else "organic"
        self.active = True
        self.cycles_completed = 0
        self.total_volume_sol = 0.0
        self.started_at = time.time()
        self.task: asyncio.Task = None


# Active volume tasks: mint -> ActiveVolume
active_tasks: dict[str, ActiveVolume] = {}


async def handle_volume_control(channel: str, data: dict):
    """Handle volume control commands from launcher or dashboard."""
    mint = data.get("mint", "")
    action = data.get("action", "")
    symbol = data.get("symbol", "")
    intensity = data.get("intensity", 0.5)
    pattern = data.get("pattern", "organic")

    if not mint:
        return

    if action == "start":
        if mint in active_tasks and active_tasks[mint].active:
            log.info(f"Volume already active for {symbol or mint[:12]}")
            return

        vol = ActiveVolume(mint, symbol, intensity, pattern)
        vol.task = asyncio.create_task(_run_volume_loop(vol))
        active_tasks[mint] = vol
        log.info(f"Volume bot STARTED: {symbol or mint[:12]} | "
                 f"pattern={pattern} | intensity={intensity:.1f}")

    elif action == "stop":
        if mint in active_tasks:
            active_tasks[mint].active = False
            log.info(f"Volume bot STOPPED: {symbol or mint[:12]} | "
                     f"cycles={active_tasks[mint].cycles_completed} | "
                     f"volume={active_tasks[mint].total_volume_sol:.4f} SOL")
            del active_tasks[mint]

    elif action == "adjust":
        if mint in active_tasks:
            active_tasks[mint].intensity = max(0.1, min(1.0, intensity))
            active_tasks[mint].pattern = pattern if pattern in PATTERNS else active_tasks[mint].pattern
            log.info(f"Volume adjusted: {symbol or mint[:12]} | intensity={intensity:.1f}")


async def _run_volume_loop(vol: ActiveVolume):
    """Execute volume cycles for a token until stopped."""
    p = PATTERNS[vol.pattern]

    while vol.active:
        try:
            # Randomize timing and size
            interval = random.uniform(p["interval_min"], p["interval_max"])
            interval *= (1.0 / vol.intensity)  # higher intensity = shorter intervals
            size = random.uniform(p["size_min"], p["size_max"]) * vol.intensity

            await asyncio.sleep(interval)

            if not vol.active:
                break

            if PAPER_MODE:
                vol.cycles_completed += 1
                vol.total_volume_sol += size * 2  # buy + sell = 2x volume
                if vol.cycles_completed % 10 == 0:
                    log.info(f"PAPER VOLUME: {vol.symbol or vol.mint[:12]} | "
                             f"cycle {vol.cycles_completed} | "
                             f"total_vol={vol.total_volume_sol:.4f} SOL")
            else:
                # Send volume cycle command to executor
                await bus.publish(Channels.VOLUME_CONTROL, {
                    "mint": vol.mint,
                    "sol_amount": size,
                    "action": "cycle",
                })
                vol.cycles_completed += 1
                vol.total_volume_sol += size * 2

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Volume loop error for {vol.mint[:12]}: {e}")
            await asyncio.sleep(10)


async def status_reporter():
    """Publish volume bot status for dashboard."""
    while True:
        active = {
            mint: {
                "symbol": v.symbol,
                "pattern": v.pattern,
                "intensity": v.intensity,
                "cycles": v.cycles_completed,
                "volume_sol": round(v.total_volume_sol, 4),
                "uptime_min": round((time.time() - v.started_at) / 60, 1),
            }
            for mint, v in active_tasks.items() if v.active
        }
        if active:
            await bus.publish("pumpdesk:volume:status", {
                "active_tokens": len(active),
                "tokens": active,
                "timestamp": utcnow(),
            })
        await asyncio.sleep(30)


async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    await bus.connect()

    await bus.subscribe(Channels.VOLUME_CONTROL, handle_volume_control)

    log.info(f"Volume Bot started | paper_mode={PAPER_MODE}")

    await asyncio.gather(
        status_reporter(),
        bus.listen(),
    )


if __name__ == "__main__":
    asyncio.run(main())


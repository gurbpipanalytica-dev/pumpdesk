"""
PumpDesk v2 — Progressive Exit Engine Main
Subscribes to position events, manages staged exits for ALL bots.

Listens for:
  - POSITION_OPENED → starts tracking with exit plan
  - POSITION_PARTIAL → updates remaining tokens after a stage sell
  - POSITION_CLOSED → removes from tracking
  - POSITION_EMERGENCY → removes from tracking

Publishes:
  - CMD_EXIT → tells executor to sell a portion
  - CMD_EMERGENCY → tells executor to liquidate everything

Price feed:
  - Polls token prices via Solana RPC + DEX APIs
  - Caches prices in Redis for other services to use
"""

import asyncio
import json
import logging
import time
import sys

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import Position, ExitPlan, utcnow
from shared.config import STATE_DIR, SOLANA_RPC_URL
from shared import db

from exit_engine import ExitEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.progressive_exit")

bus = RedisBus("progressive_exit")

# Price cache: mint -> (timestamp, price_sol)
_price_cache: dict = {}
_CACHE_TTL = 5  # seconds


async def get_token_price(mint: str) -> float:
    """Get current token price in SOL. Uses cache + RPC fallback."""
    now = time.time()

    # Check cache
    cached = _price_cache.get(mint)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    # Check Redis cache (populated by other services)
    try:
        redis_price = await bus.cache_get(f"price:{mint}")
        if redis_price:
            price = float(redis_price)
            _price_cache[mint] = (now, price)
            return price
    except Exception:
        pass

    # Fallback: fetch from DexScreener or Bitquery
    price = await _fetch_price_dexscreener(mint)
    if price > 0:
        _price_cache[mint] = (now, price)
        await bus.cache_set(f"price:{mint}", str(price), ttl=10)

    return price


async def _fetch_price_dexscreener(mint: str) -> float:
    """Fetch token price from DexScreener API."""
    import aiohttp
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return 0.0
                data = await resp.json()
                pairs = data.get("pairs", [])
                if not pairs:
                    return 0.0
                # Use the pair with highest liquidity
                best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                price_usd = float(best.get("priceUsd", 0) or 0)
                # Convert to SOL (approximate — good enough for exit triggers)
                price_native = float(best.get("priceNative", 0) or 0)
                return price_native if price_native > 0 else price_usd / 150  # rough SOL price
    except Exception as e:
        log.debug(f"DexScreener fetch failed for {mint[:12]}: {e}")
        return 0.0


# ── Exit engine instance ───────────────────────────────────────────────────
engine = ExitEngine(bus=bus, price_feed=get_token_price)


# ══════════════════════════════════════════════════════════════════════════════
#  REDIS HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def handle_position_opened(channel: str, data: dict):
    """New position opened — start tracking it."""
    try:
        pos = Position.from_json(json.dumps(data))

        # Build exit plan from the decision's plan or use defaults
        plan_data = data.get("exit_plan") or data.get("exit_stages_remaining")
        if plan_data and isinstance(plan_data, dict):
            exit_plan = ExitPlan.from_json(json.dumps(plan_data))
        elif plan_data and isinstance(plan_data, list):
            exit_plan = ExitPlan(stages=plan_data)
        else:
            exit_plan = None  # will use defaults

        engine.add_position(pos, exit_plan)

    except Exception as e:
        log.error(f"handle_position_opened error: {e}")


async def handle_position_partial(channel: str, data: dict):
    """A stage sell completed — update remaining tokens."""
    try:
        pos_id = data.get("position_id", "")
        tokens_sold = data.get("tokens_sold", 0)
        managed = engine.positions.get(pos_id)
        if managed:
            managed.remaining_tokens = max(0, managed.remaining_tokens - tokens_sold)
            log.info(f"Partial exit confirmed: {pos_id} | "
                     f"sold {tokens_sold:.0f} | remaining {managed.remaining_tokens:.0f}")
            if managed.remaining_tokens <= 0:
                engine.remove_position(pos_id)
    except Exception as e:
        log.error(f"handle_position_partial error: {e}")


async def handle_position_closed(channel: str, data: dict):
    """Position fully closed — stop tracking."""
    pos_id = data.get("position_id", "")
    engine.remove_position(pos_id)


async def handle_position_emergency(channel: str, data: dict):
    """Emergency exit completed — stop tracking."""
    pos_id = data.get("position_id", "")
    engine.remove_position(pos_id)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    await bus.connect()

    # Subscribe to position lifecycle events
    await bus.subscribe(Channels.POSITION_OPENED, handle_position_opened)
    await bus.subscribe(Channels.POSITION_PARTIAL, handle_position_partial)
    await bus.subscribe(Channels.POSITION_CLOSED, handle_position_closed)
    await bus.subscribe(Channels.POSITION_EMERGENCY, handle_position_emergency)

    log.info("Progressive Exit Engine started")
    log.info(f"Default stages: {len(engine.positions)} positions tracking")

    # Run the exit engine price-check loop and Redis listener concurrently
    await asyncio.gather(
        engine.run(),
        bus.listen(),
    )


if __name__ == "__main__":
    asyncio.run(main())


"""
PumpDesk v2 — Social Aggregator (Engine)
Aggregates social signals from Twitter and Telegram to score token hype.

Publishes INTEL_HYPE_SCORE for the orchestrator's signal correlator.
When a token gets social buzz BEFORE it pumps on-chain, that's alpha.

Sources:
  - Twitter/X: keyword mentions, cashtag volume, influencer engagement
  - Telegram: group message velocity, channel mention spikes
  - On-chain social: PumpFun comments/replies as proxy for attention

Output: hype_score 0.0-1.0 per token, published to Redis.
"""

import asyncio
import json
import logging
import time
import sys

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import utcnow
from shared.config import STATE_DIR, PAPER_MODE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("pumpdesk.social")
bus = RedisBus("social_aggregator")

# Token hype tracking
hype_scores: dict[str, dict] = {}  # mint -> {score, mentions, velocity, sources, updated}

SCAN_INTERVAL = 60  # seconds


async def scan_pumpfun_social():
    """Scan PumpFun's native social features (comments, replies, reactions)."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            # PumpFun frontend API — get tokens sorted by activity
            url = "https://frontend-api-v2.pump.fun/coins/currently-live?limit=50&offset=0&includeNsfw=false"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return
                tokens = await resp.json()
                for t in tokens:
                    mint = t.get("mint", "")
                    if not mint:
                        continue
                    replies = int(t.get("reply_count", 0))
                    # Hype score: reply velocity is a strong social signal
                    old = hype_scores.get(mint, {})
                    old_replies = old.get("replies", 0)
                    velocity = replies - old_replies  # new replies since last scan

                    score = 0.0
                    if velocity > 20:
                        score = 0.8
                    elif velocity > 10:
                        score = 0.6
                    elif velocity > 5:
                        score = 0.4
                    elif replies > 50:
                        score = 0.3

                    if score > 0.3:
                        hype_scores[mint] = {
                            "score": score,
                            "replies": replies,
                            "velocity": velocity,
                            "symbol": t.get("symbol", ""),
                            "source": "pumpfun_replies",
                            "updated": time.time(),
                        }
                        await bus.publish(Channels.INTEL_HYPE_SCORE, {
                            "mint": mint,
                            "symbol": t.get("symbol", ""),
                            "score": score,
                            "velocity": velocity,
                            "replies": replies,
                            "timestamp": utcnow(),
                        })
    except Exception as e:
        log.debug(f"PumpFun social scan error: {e}")


async def scan_loop():
    while True:
        try:
            await scan_pumpfun_social()
            # Twitter and Telegram scanners would plug in here
            # They require API keys set up in .env
        except Exception as e:
            log.error(f"Social scan error: {e}")
        await asyncio.sleep(SCAN_INTERVAL)


async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    await bus.connect()
    log.info("Social Aggregator started")
    await asyncio.gather(scan_loop(), bus.listen())

if __name__ == "__main__":
    asyncio.run(main())


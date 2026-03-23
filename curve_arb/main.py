"""PumpDesk v2 — Service placeholder. Replace with real implementation."""
import asyncio
import logging
import sys
import os

sys.path.insert(0, "/app")
from shared.redis_bus import RedisBus

SERVICE_NAME = os.path.basename(os.path.dirname(os.path.abspath(__file__))) or "unknown"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(f"pumpdesk.{SERVICE_NAME}")


async def main():
    bus = RedisBus(SERVICE_NAME)
    await bus.connect()
    log.info(f"{SERVICE_NAME} started — waiting for implementation")
    # Keep alive
    while True:
        await asyncio.sleep(60)
        log.info(f"{SERVICE_NAME} heartbeat")


if __name__ == "__main__":
    asyncio.run(main())

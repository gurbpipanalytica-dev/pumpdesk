"""
PumpDesk v2 — Redis Pub/Sub Bus
The nervous system. Every bot publishes signals, orchestrator decides,
executor acts. All through these channels.
"""

import json
import logging
import asyncio
from typing import Callable, Optional

import redis.asyncio as aioredis

from shared.config import REDIS_URL

log = logging.getLogger("pumpdesk.bus")


class Channels:
    """All Redis pub/sub channels. One source of truth."""

    # ── Signals (bots → orchestrator) ──────────────────────────────────────
    SIGNAL_NEW_TOKEN     = "pumpdesk:signals:new_token"
    SIGNAL_CURVE         = "pumpdesk:signals:curve_progress"
    SIGNAL_WHALE         = "pumpdesk:signals:whale_trade"
    SIGNAL_ARB           = "pumpdesk:signals:arb_opportunity"
    SIGNAL_MOMENTUM      = "pumpdesk:signals:momentum_spike"
    SIGNAL_SOCIAL        = "pumpdesk:signals:social_hype"
    SIGNAL_GRADUATION    = "pumpdesk:signals:graduation"

    # ── Decisions (orchestrator → bots/executor) ───────────────────────────
    DECISION_APPROVE     = "pumpdesk:decisions:approve"
    DECISION_REJECT      = "pumpdesk:decisions:reject"

    # ── Commands (orchestrator → executor) ─────────────────────────────────
    CMD_EXECUTE          = "pumpdesk:commands:execute"
    CMD_EXIT             = "pumpdesk:commands:exit"
    CMD_EMERGENCY        = "pumpdesk:commands:emergency"

    # ── Launcher ───────────────────────────────────────────────────────────
    LAUNCH_CREATE        = "pumpdesk:launch:create"
    LAUNCH_STATUS        = "pumpdesk:launch:status"
    LAUNCH_GRADUATED     = "pumpdesk:launch:graduated"
    VOLUME_CONTROL       = "pumpdesk:launch:volume_control"

    # ── Execution confirmations ────────────────────────────────────────────
    TX_CONFIRMED         = "pumpdesk:tx:confirmed"
    TX_FAILED            = "pumpdesk:tx:failed"

    # ── Intelligence updates ───────────────────────────────────────────────
    INTEL_CREATOR_SCORE  = "pumpdesk:intel:creator_score"
    INTEL_HYPE_SCORE     = "pumpdesk:intel:hype_score"
    INTEL_GRAD_PROB      = "pumpdesk:intel:grad_probability"

    # ── Position updates ───────────────────────────────────────────────────
    POSITION_OPENED      = "pumpdesk:positions:opened"
    POSITION_PARTIAL     = "pumpdesk:positions:partial_exit"
    POSITION_CLOSED      = "pumpdesk:positions:closed"
    POSITION_EMERGENCY   = "pumpdesk:positions:emergency"


class RedisBus:
    """Async Redis pub/sub client. Every bot creates one at startup."""

    def __init__(self, service_name: str):
        self.service_name = service_name
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._handlers: dict[str, Callable] = {}

    async def connect(self):
        self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        log.info(f"[{self.service_name}] Connected to Redis")

    async def disconnect(self):
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        log.info(f"[{self.service_name}] Disconnected from Redis")

    async def publish(self, channel: str, data: dict | str):
        if isinstance(data, dict):
            data = json.dumps(data)
        await self._redis.publish(channel, data)
        log.debug(f"[{self.service_name}] Published to {channel}")

    async def subscribe(self, channel: str, handler: Callable):
        self._handlers[channel] = handler
        await self._pubsub.subscribe(channel)
        log.info(f"[{self.service_name}] Subscribed to {channel}")

    async def listen(self):
        log.info(f"[{self.service_name}] Listening on {len(self._handlers)} channels")
        async for message in self._pubsub.listen():
            if message["type"] != "message":
                continue
            channel = message["channel"]
            handler = self._handlers.get(channel)
            if handler:
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    data = message["data"]
                try:
                    await handler(channel, data)
                except Exception as e:
                    log.error(f"[{self.service_name}] Handler error on {channel}: {e}")

    async def cache_set(self, key: str, value: str, ttl: int = 300):
        await self._redis.set(key, value, ex=ttl)

    async def cache_get(self, key: str) -> Optional[str]:
        return await self._redis.get(key)

    async def cache_delete(self, key: str):
        await self._redis.delete(key)


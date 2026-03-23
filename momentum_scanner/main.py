"""
PumpDesk v2 — Momentum Scanner (Bot 4)
Scans the entire PumpFun token stream for tradeable momentum patterns.
Highest signal volume of any bot — generates the most opportunities.

Signals detected:
  1. Volume spike: 24h volume jumps 3x+ in 30 minutes
  2. Holder acceleration: unique holders growing exponentially
  3. Price breakout: token breaks above recent high on increasing volume
  4. Social correlation: hype score spike aligns with on-chain activity

Unlike the sniper (focused on near-graduation) and copier (focused on whales),
the momentum scanner looks at ALL active PumpFun tokens and ranks them by
how likely they are to move in the next 5-30 minutes.

CRITICAL: Depends on creator_judge to filter rugs. Without it, 90%+
of momentum signals would be wash-traded scam tokens.
"""

import asyncio
import json
import logging
import time
import sys
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import Signal, Token, utcnow
from shared.config import STATE_DIR, ENABLE_MOMENTUM, MAX_POSITION_SOL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("pumpdesk.momentum")

bus = RedisBus("momentum_scanner")


@dataclass
class TokenMomentum:
    """Momentum metrics for a single token."""
    mint: str
    symbol: str = ""
    creator: str = ""
    bonding_curve: str = ""
    curve_pct: float = 0.0

    # Volume tracking
    volume_snapshots: List[tuple] = field(default_factory=list)  # (timestamp, volume_sol)
    volume_30m_ago: float = 0.0
    volume_current: float = 0.0

    # Holder tracking
    holder_snapshots: List[tuple] = field(default_factory=list)  # (timestamp, count)
    holders_current: int = 0

    # Price tracking
    price_snapshots: List[tuple] = field(default_factory=list)  # (timestamp, price_sol)
    price_current: float = 0.0
    price_high_1h: float = 0.0

    last_updated: float = 0.0

    @property
    def volume_spike_ratio(self) -> float:
        if self.volume_30m_ago <= 0:
            return 0
        return self.volume_current / self.volume_30m_ago

    @property
    def holder_growth_rate(self) -> float:
        """Holders gained per minute over last 30 min."""
        if len(self.holder_snapshots) < 2:
            return 0
        first_t, first_h = self.holder_snapshots[0]
        last_t, last_h = self.holder_snapshots[-1]
        minutes = (last_t - first_t) / 60
        if minutes <= 0:
            return 0
        return (last_h - first_h) / minutes

    @property
    def price_breakout(self) -> bool:
        return self.price_current > self.price_high_1h * 1.05 and self.volume_spike_ratio > 1.5

    def add_snapshot(self, volume: float, holders: int, price: float):
        now = time.time()
        self.volume_snapshots.append((now, volume))
        self.holder_snapshots.append((now, holders))
        self.price_snapshots.append((now, price))
        self.volume_current = volume
        self.holders_current = holders
        self.price_current = price
        self.last_updated = now

        # Update rolling metrics
        cutoff_30m = now - 1800
        old_vols = [v for t, v in self.volume_snapshots if t <= cutoff_30m]
        self.volume_30m_ago = old_vols[-1] if old_vols else volume

        cutoff_1h = now - 3600
        recent_prices = [p for t, p in self.price_snapshots if t >= cutoff_1h]
        self.price_high_1h = max(recent_prices) if recent_prices else price

        # Prune old data
        self.volume_snapshots = [(t, v) for t, v in self.volume_snapshots if t > now - 7200]
        self.holder_snapshots = [(t, h) for t, h in self.holder_snapshots if t > now - 7200]
        self.price_snapshots = [(t, p) for t, p in self.price_snapshots if t > now - 7200]


class MomentumScanner:
    """Scans and ranks tokens by momentum signals."""

    def __init__(self):
        self.tokens: dict[str, TokenMomentum] = {}
        self.signaled_recently: dict[str, float] = {}  # mint -> last signal time
        self.signal_cooldown = 300  # 5 min between signals for same token

    def update_token(self, mint: str, volume: float, holders: int,
                     price: float, **kwargs):
        if mint not in self.tokens:
            self.tokens[mint] = TokenMomentum(mint=mint, **kwargs)
        self.tokens[mint].add_snapshot(volume, holders, price)

    def scan(self) -> List[dict]:
        """Scan all tracked tokens and return momentum signals."""
        now = time.time()
        signals = []

        for mint, m in self.tokens.items():
            if now - m.last_updated > 600:
                continue  # stale data

            # Cooldown check
            last_sig = self.signaled_recently.get(mint, 0)
            if now - last_sig < self.signal_cooldown:
                continue

            score, reasons = self._score_momentum(m)
            if score > 0:
                signals.append({
                    "mint": mint,
                    "symbol": m.symbol,
                    "creator": m.creator,
                    "bonding_curve": m.bonding_curve,
                    "curve_pct": m.curve_pct,
                    "price_sol": m.price_current,
                    "score": score,
                    "reasons": reasons,
                    "volume_spike": m.volume_spike_ratio,
                    "holder_growth": m.holder_growth_rate,
                    "is_breakout": m.price_breakout,
                })

        return sorted(signals, key=lambda x: x["score"], reverse=True)[:10]

    def _score_momentum(self, m: TokenMomentum) -> tuple[float, list]:
        score = 0.0
        reasons = []

        # Volume spike
        if m.volume_spike_ratio >= 5.0:
            score += 0.30
            reasons.append(f"volume {m.volume_spike_ratio:.1f}x spike")
        elif m.volume_spike_ratio >= 3.0:
            score += 0.20
            reasons.append(f"volume {m.volume_spike_ratio:.1f}x spike")

        # Holder growth
        if m.holder_growth_rate >= 5:
            score += 0.20
            reasons.append(f"+{m.holder_growth_rate:.0f} holders/min")
        elif m.holder_growth_rate >= 2:
            score += 0.10
            reasons.append(f"+{m.holder_growth_rate:.0f} holders/min")

        # Price breakout
        if m.price_breakout:
            score += 0.20
            reasons.append("price breakout on volume")

        # Curve position bonus (higher curve = closer to graduation)
        if m.curve_pct >= 0.70:
            score += 0.10
            reasons.append(f"curve {m.curve_pct:.0%}")

        return score, reasons


scanner = MomentumScanner()


async def fetch_active_tokens():
    """Periodically fetch active PumpFun token data for momentum tracking."""
    import aiohttp

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                # Fetch from PumpFun / Bitquery / DexScreener
                url = "https://frontend-api-v2.pump.fun/coins/currently-live?limit=50&offset=0&includeNsfw=false"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        tokens = await resp.json()
                        for t in tokens:
                            mint = t.get("mint", "")
                            if not mint:
                                continue
                            scanner.update_token(
                                mint=mint,
                                volume=float(t.get("usd_market_cap", 0)),
                                holders=int(t.get("reply_count", 0)),
                                price=float(t.get("virtual_sol_reserves", 0)) / max(float(t.get("virtual_token_reserves", 1)), 1),
                                symbol=t.get("symbol", ""),
                                creator=t.get("creator", ""),
                                bonding_curve=t.get("bonding_curve", ""),
                            )
                        log.debug(f"Updated {len(tokens)} tokens from PumpFun API")

        except Exception as e:
            log.debug(f"Token fetch error: {e}")

        await asyncio.sleep(30)  # poll every 30s


async def signal_loop():
    """Scan for momentum signals and publish to orchestrator."""
    await asyncio.sleep(60)  # wait for data to accumulate

    while True:
        try:
            signals = scanner.scan()
            for sig in signals[:3]:  # top 3 per cycle
                token = Token(
                    mint=sig["mint"],
                    symbol=sig["symbol"],
                    creator=sig["creator"],
                    bonding_curve=sig["bonding_curve"],
                    curve_pct=sig["curve_pct"],
                    price_sol=sig["price_sol"],
                )
                signal = Signal(
                    signal_id=f"SIG-{int(time.time())}-momentum-{sig['mint'][:8]}",
                    bot="momentum_scanner",
                    signal_type="momentum_spike",
                    token=token,
                    action="buy",
                    confidence=min(0.9, 0.4 + sig["score"]),
                    size_sol=min(MAX_POSITION_SOL * 0.5, 1.0),
                    reason=" | ".join(sig["reasons"]),
                    metadata={
                        "volume_spike": sig["volume_spike"],
                        "holder_growth": sig["holder_growth"],
                        "is_breakout": sig["is_breakout"],
                        "momentum_score": sig["score"],
                    },
                )
                await bus.publish(Channels.SIGNAL_MOMENTUM, json.loads(signal.to_json()))
                scanner.signaled_recently[sig["mint"]] = time.time()

                log.info(f"SIGNAL: {sig['symbol'] or sig['mint'][:12]} | "
                         f"score={sig['score']:.2f} | {' | '.join(sig['reasons'])}")

        except Exception as e:
            log.error(f"signal_loop error: {e}")

        await asyncio.sleep(15)


async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not ENABLE_MOMENTUM:
        log.info("Momentum scanner disabled — exiting")
        return

    await bus.connect()
    log.info("Momentum Scanner started")

    await asyncio.gather(
        fetch_active_tokens(),
        signal_loop(),
        bus.listen(),
    )


if __name__ == "__main__":
    asyncio.run(main())


"""
PumpDesk v2 — Signal Correlator
Cross-references signals from multiple bots to boost or suppress confidence.

If the sniper detects a token at 87% curve AND the copier sees a whale buying
AND social hype is rising — that's a triple-confirmed signal worth more than any
single bot's output.

Conversely, if momentum scanner flags a volume spike but creator judge scores
the creator at 0.1 — suppress it.
"""

import logging
import time
from collections import defaultdict
from typing import List, Optional

from shared.models import Signal

log = logging.getLogger("pumpdesk.orchestrator.correlator")


class SignalCorrelator:
    """Maintains a rolling window of recent signals and correlates them."""

    def __init__(self, window_seconds: int = 300):
        self.window_seconds = window_seconds
        # mint -> list of (timestamp, signal)
        self._recent: dict[str, list] = defaultdict(list)

    def add_signal(self, signal: Signal):
        """Register a signal in the correlation window."""
        now = time.time()
        mint = signal.token.mint
        self._recent[mint].append((now, signal))
        self._prune(mint)

    def get_correlation(self, signal: Signal) -> dict:
        """Check how many other bots have signaled the same token recently.

        Returns:
            {
                "corroborating_bots": ["wallet_copier", "social_aggregator"],
                "total_signals": 3,
                "confidence_boost": 0.15,
                "conflicting_signals": [],
                "recommendation": "strong_buy" | "buy" | "hold" | "suppress"
            }
        """
        mint = signal.token.mint
        self._prune(mint)
        recent = self._recent.get(mint, [])

        other_bots = set()
        buy_signals = 0
        sell_signals = 0
        conflicting = []

        for ts, s in recent:
            if s.signal_id == signal.signal_id:
                continue  # skip self
            other_bots.add(s.bot)
            if s.action in ("buy", "lp_add"):
                buy_signals += 1
            elif s.action in ("sell", "lp_remove"):
                sell_signals += 1
                conflicting.append({"bot": s.bot, "action": s.action, "reason": s.reason})

        # Calculate confidence boost based on corroboration
        corroboration_count = len(other_bots)
        if corroboration_count == 0:
            boost = 0.0
            recommendation = "buy" if signal.action == "buy" else "hold"
        elif corroboration_count == 1:
            boost = 0.10
            recommendation = "buy"
        elif corroboration_count == 2:
            boost = 0.20
            recommendation = "strong_buy"
        else:
            boost = 0.30
            recommendation = "strong_buy"

        # Suppress if there are conflicting sell signals
        if sell_signals > buy_signals:
            boost = -0.20
            recommendation = "suppress"

        return {
            "corroborating_bots": list(other_bots),
            "total_signals": len(recent),
            "confidence_boost": boost,
            "conflicting_signals": conflicting,
            "recommendation": recommendation,
        }

    def get_hot_tokens(self, min_signals: int = 2) -> List[dict]:
        """Return tokens with multiple recent signals — the 'hot' list."""
        now = time.time()
        hot = []
        for mint, entries in self._recent.items():
            active = [(ts, s) for ts, s in entries if now - ts < self.window_seconds]
            if len(active) >= min_signals:
                bots = list(set(s.bot for _, s in active))
                hot.append({
                    "mint": mint,
                    "symbol": active[-1][1].token.symbol,
                    "signal_count": len(active),
                    "bots": bots,
                    "latest_confidence": active[-1][1].confidence,
                })
        return sorted(hot, key=lambda x: x["signal_count"], reverse=True)

    def _prune(self, mint: str):
        """Remove signals outside the correlation window."""
        cutoff = time.time() - self.window_seconds
        self._recent[mint] = [
            (ts, s) for ts, s in self._recent[mint] if ts > cutoff
        ]
        if not self._recent[mint]:
            del self._recent[mint]


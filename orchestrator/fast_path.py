"""
PumpDesk v2 — Orchestrator: Fast Path Rules Engine
Deterministic go/no-go decisions in <100ms.
No AI calls — pure rules, exposure checks, blacklists, cross-signal correlation.

This is the gatekeeper. Every signal from every bot passes through here FIRST.
If the fast path approves, the signal proceeds to execution.
If the fast path needs more context, it queries intelligence engines via Redis cache.
If the fast path rejects, the signal is dead — no trade happens.
"""

import time
import logging
from typing import Optional
from dataclasses import dataclass, field

from shared.config import (
    MAX_POSITION_SOL, MAX_CONCURRENT_POSITIONS, MAX_DAILY_LOSS_SOL,
    PAPER_MODE, ENABLE_SNIPER, ENABLE_COPIER, ENABLE_ARB, ENABLE_MOMENTUM,
    ENABLE_LAUNCHER, ENABLE_VOLUME_BOT, ENABLE_ANTI_SNIPER,
    DEFAULT_EXIT_STAGES, DEFAULT_TIME_EXIT_SECONDS, EMERGENCY_EXIT_DROP_PCT,
)
from shared.models import Signal, Decision, ExitPlan, Position, utcnow

log = logging.getLogger("pumpdesk.orchestrator.fast_path")


# ══════════════════════════════════════════════════════════════════════════════
#  PORTFOLIO STATE — in-memory, updated by Redis events
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PortfolioState:
    """Live portfolio state maintained by the orchestrator."""
    open_positions: dict = field(default_factory=dict)   # position_id -> Position
    daily_pnl_sol: float = 0.0
    daily_trades: int = 0
    daily_loss_sol: float = 0.0
    total_exposure_sol: float = 0.0
    last_reset_day: str = ""

    # Intelligence cache (populated by Redis from engines)
    creator_scores: dict = field(default_factory=dict)   # creator_address -> float (0-1)
    hype_scores: dict = field(default_factory=dict)       # mint -> float (0-1)
    grad_probabilities: dict = field(default_factory=dict) # mint -> float (0-1)

    # Blacklists
    blacklisted_creators: set = field(default_factory=set)
    blacklisted_mints: set = field(default_factory=set)

    # Recent signals (dedup window)
    recent_signal_ids: set = field(default_factory=set)

    def reset_daily(self):
        today = utcnow()[:10]
        if self.last_reset_day != today:
            self.daily_pnl_sol = 0.0
            self.daily_trades = 0
            self.daily_loss_sol = 0.0
            self.last_reset_day = today
            self.recent_signal_ids.clear()
            log.info(f"Daily counters reset for {today}")


# ══════════════════════════════════════════════════════════════════════════════
#  FAST PATH RULES
# ══════════════════════════════════════════════════════════════════════════════

class FastPath:
    """Deterministic rules engine. Returns Decision in <100ms."""

    def __init__(self, state: PortfolioState):
        self.state = state

    def evaluate(self, signal: Signal) -> Decision:
        """Run all rules against a signal. Returns approved or rejected Decision."""
        start = time.monotonic()
        self.state.reset_daily()

        decision_id = f"DEC-{int(time.time())}-{signal.bot}"

        # ── Rule 1: Dedup — reject duplicate signals ───────────────────
        if signal.signal_id in self.state.recent_signal_ids:
            return self._reject(decision_id, signal, "Duplicate signal")
        self.state.recent_signal_ids.add(signal.signal_id)
        # Cap dedup window size
        if len(self.state.recent_signal_ids) > 1000:
            self.state.recent_signal_ids = set(list(self.state.recent_signal_ids)[-500:])

        # ── Rule 2: Bot enabled check ──────────────────────────────────
        bot_flags = {
            "graduation_sniper": ENABLE_SNIPER,
            "wallet_copier": ENABLE_COPIER,
            "curve_arb": ENABLE_ARB,
            "momentum_scanner": ENABLE_MOMENTUM,
            "token_launcher": ENABLE_LAUNCHER,
            "volume_bot": ENABLE_VOLUME_BOT,
            "anti_sniper": ENABLE_ANTI_SNIPER,
        }
        if not bot_flags.get(signal.bot, False):
            return self._reject(decision_id, signal, f"Bot {signal.bot} is disabled")

        # ── Rule 3: Blacklist check ────────────────────────────────────
        if signal.token.creator in self.state.blacklisted_creators:
            return self._reject(decision_id, signal, f"Creator {signal.token.creator[:8]}... blacklisted")
        if signal.token.mint in self.state.blacklisted_mints:
            return self._reject(decision_id, signal, f"Token {signal.token.mint[:8]}... blacklisted")

        # ── Rule 4: Creator reputation ─────────────────────────────────
        creator_score = self.state.creator_scores.get(signal.token.creator)
        if creator_score is not None and creator_score < 0.3:
            return self._reject(decision_id, signal,
                f"Creator score too low: {creator_score:.2f}")

        # ── Rule 5: Daily loss limit ───────────────────────────────────
        if self.state.daily_loss_sol >= MAX_DAILY_LOSS_SOL:
            return self._reject(decision_id, signal,
                f"Daily loss limit hit: {self.state.daily_loss_sol:.2f} SOL")

        # ── Rule 6: Max concurrent positions ───────────────────────────
        open_count = len(self.state.open_positions)
        if open_count >= MAX_CONCURRENT_POSITIONS:
            return self._reject(decision_id, signal,
                f"Max positions ({MAX_CONCURRENT_POSITIONS}) reached")

        # ── Rule 7: Max position size ──────────────────────────────────
        size = min(signal.size_sol, MAX_POSITION_SOL)
        if size <= 0:
            size = MAX_POSITION_SOL * 0.5  # default to half max

        # ── Rule 8: Exposure limit ─────────────────────────────────────
        remaining_capacity = (MAX_POSITION_SOL * MAX_CONCURRENT_POSITIONS) - self.state.total_exposure_sol
        if remaining_capacity <= 0:
            return self._reject(decision_id, signal, "Total exposure limit reached")
        size = min(size, remaining_capacity)

        # ── Rule 9: Confidence threshold ───────────────────────────────
        min_confidence = {
            "graduation_sniper": 0.6,
            "wallet_copier": 0.5,
            "curve_arb": 0.7,
            "momentum_scanner": 0.5,
            "token_launcher": 0.0,  # launcher doesn't need confidence
            "volume_bot": 0.0,
            "anti_sniper": 0.0,
        }
        threshold = min_confidence.get(signal.bot, 0.5)
        if signal.confidence < threshold:
            return self._reject(decision_id, signal,
                f"Confidence {signal.confidence:.2f} below threshold {threshold}")

        # ── Rule 10: Cross-signal boost ────────────────────────────────
        # If multiple bots signal the same token, increase size
        same_token_signals = sum(
            1 for pos in self.state.open_positions.values()
            if pos.mint == signal.token.mint
        )
        if same_token_signals > 0:
            # Already have a position — don't double up unless it's a different bot
            pass  # For now, allow it — the exit engine manages exposure

        # ── Build exit plan ────────────────────────────────────────────
        exit_plan = ExitPlan(
            stages=DEFAULT_EXIT_STAGES.copy(),
            time_exit_seconds=DEFAULT_TIME_EXIT_SECONDS,
            emergency_drop_pct=EMERGENCY_EXIT_DROP_PCT,
        )

        elapsed_ms = (time.monotonic() - start) * 1000
        log.info(f"APPROVED: {signal.bot} | {signal.token.symbol or signal.token.mint[:8]} | "
                 f"{size:.3f} SOL | conf={signal.confidence:.2f} | {elapsed_ms:.1f}ms")

        return Decision(
            decision_id=decision_id,
            signal_id=signal.signal_id,
            approved=True,
            reason=f"Fast path approved: {signal.reason}",
            adjusted_size_sol=size,
            exit_plan=exit_plan.__dict__,
        )

    def _reject(self, decision_id: str, signal: Signal, reason: str) -> Decision:
        log.info(f"REJECTED: {signal.bot} | {signal.token.symbol or signal.token.mint[:8]} | {reason}")
        return Decision(
            decision_id=decision_id,
            signal_id=signal.signal_id,
            approved=False,
            reason=reason,
        )


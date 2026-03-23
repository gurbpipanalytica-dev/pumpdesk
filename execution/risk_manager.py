"""
PumpDesk v2 — Execution Engine: Risk Manager
Final safety layer before any transaction hits Solana.
Validates position size, checks exposure, enforces paper mode.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from shared.config import (
    MAX_POSITION_SOL, MAX_CONCURRENT_POSITIONS, MAX_DAILY_LOSS_SOL, PAPER_MODE
)
from shared.models import Signal, Decision, Position, utcnow

log = logging.getLogger("pumpdesk.execution.risk")


@dataclass
class RiskState:
    """Live risk tracking — mirrors orchestrator's view but independent check."""
    open_position_count: int = 0
    total_exposure_sol: float = 0.0
    daily_realized_pnl: float = 0.0
    daily_loss: float = 0.0
    last_trade_time: float = 0.0
    min_trade_interval: float = 2.0  # minimum seconds between trades


class RiskManager:
    """Final safety gate. If this rejects, the TX does not get built."""

    def __init__(self):
        self.state = RiskState()

    def validate_trade(self, decision: Decision, signal: Signal) -> tuple[bool, str]:
        """Run final risk checks before building the transaction.
        Returns (approved: bool, reason: str)."""

        # ── Paper mode guard ───────────────────────────────────────────
        if PAPER_MODE:
            log.info(f"PAPER MODE: would execute {signal.action} {decision.adjusted_size_sol:.3f} SOL "
                     f"on {signal.token.symbol or signal.token.mint[:12]}")
            return True, "paper_mode"

        # ── Rate limit ─────────────────────────────────────────────────
        now = time.time()
        if now - self.state.last_trade_time < self.state.min_trade_interval:
            return False, f"Rate limited: {self.state.min_trade_interval}s between trades"

        # ── Position size sanity ───────────────────────────────────────
        size = decision.adjusted_size_sol
        if size <= 0:
            return False, "Invalid size: 0 or negative"
        if size > MAX_POSITION_SOL:
            return False, f"Size {size:.3f} exceeds max {MAX_POSITION_SOL}"

        # ── Exposure check ─────────────────────────────────────────────
        if self.state.open_position_count >= MAX_CONCURRENT_POSITIONS:
            return False, f"Max positions ({MAX_CONCURRENT_POSITIONS}) reached"

        max_total = MAX_POSITION_SOL * MAX_CONCURRENT_POSITIONS
        if self.state.total_exposure_sol + size > max_total:
            return False, f"Would exceed total exposure limit: {max_total} SOL"

        # ── Daily loss check ───────────────────────────────────────────
        if self.state.daily_loss >= MAX_DAILY_LOSS_SOL:
            return False, f"Daily loss limit reached: {self.state.daily_loss:.3f} SOL"

        self.state.last_trade_time = now
        return True, "approved"

    def on_position_opened(self, size_sol: float):
        self.state.open_position_count += 1
        self.state.total_exposure_sol += size_sol

    def on_position_closed(self, size_sol: float, pnl_sol: float):
        self.state.open_position_count = max(0, self.state.open_position_count - 1)
        self.state.total_exposure_sol = max(0, self.state.total_exposure_sol - size_sol)
        self.state.daily_realized_pnl += pnl_sol
        if pnl_sol < 0:
            self.state.daily_loss += abs(pnl_sol)


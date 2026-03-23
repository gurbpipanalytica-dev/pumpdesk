"""
PumpDesk v2 — Progressive Exit Engine: Core
Manages staged sells for every open position across all bots.

Instead of binary open/close, every position follows an exit plan:
  - Stage 1: sell 50% at 2x entry
  - Stage 2: sell 25% at 5x entry
  - Stage 3: sell 15% at 10x entry
  - Remaining 10% = moonbag (hold indefinitely or time-exit)

Also handles:
  - Time-based exits (force sell after N seconds regardless of price)
  - Emergency exits (price drops 30%+ from entry → instant liquidation)
  - Trailing stops (once a stage triggers, protect remaining with trailing %)

Every bot's positions route through here. No bot sells directly.
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional
from dataclasses import asdict

from shared.models import Position, ExitPlan, utcnow
from shared.config import (
    DEFAULT_EXIT_STAGES, DEFAULT_TIME_EXIT_SECONDS,
    EMERGENCY_EXIT_DROP_PCT, PAPER_MODE
)

log = logging.getLogger("pumpdesk.exit_engine")


class ExitEngine:
    """Monitors all open positions and triggers staged exits."""

    def __init__(self, bus, price_feed):
        """
        Args:
            bus: RedisBus instance for publishing exit commands
            price_feed: async callable(mint) -> float that returns current price in SOL
        """
        self.bus = bus
        self.price_feed = price_feed
        self.positions: Dict[str, ManagedPosition] = {}
        self.check_interval = 2.0  # check prices every 2 seconds

    def add_position(self, position: Position, exit_plan: Optional[ExitPlan] = None):
        """Register a new position for exit management."""
        if not exit_plan:
            exit_plan = ExitPlan(
                stages=DEFAULT_EXIT_STAGES.copy(),
                time_exit_seconds=DEFAULT_TIME_EXIT_SECONDS,
                emergency_drop_pct=EMERGENCY_EXIT_DROP_PCT,
            )

        managed = ManagedPosition(
            position=position,
            exit_plan=exit_plan,
            entry_time=time.time(),
            remaining_tokens=position.size_tokens,
            highest_price=position.entry_price_sol,
        )
        self.positions[position.position_id] = managed
        log.info(f"Exit engine tracking: {position.position_id} | "
                 f"{position.bot} | {position.mint[:12]} | "
                 f"{len(exit_plan.stages)} stages | "
                 f"time_exit={exit_plan.time_exit_seconds}s | "
                 f"emergency={exit_plan.emergency_drop_pct:.0%}")

    def remove_position(self, position_id: str):
        """Remove a fully closed position."""
        if position_id in self.positions:
            del self.positions[position_id]
            log.info(f"Exit engine released: {position_id}")

    async def run(self):
        """Main loop — continuously check prices and trigger exits."""
        log.info(f"Exit engine running | check_interval={self.check_interval}s")
        while True:
            try:
                await self._check_all_positions()
            except Exception as e:
                log.error(f"Exit engine cycle error: {e}")
            await asyncio.sleep(self.check_interval)

    async def _check_all_positions(self):
        """Check every managed position against its exit plan."""
        if not self.positions:
            return

        for pos_id, managed in list(self.positions.items()):
            try:
                current_price = await self.price_feed(managed.position.mint)
                if current_price <= 0:
                    continue

                managed.highest_price = max(managed.highest_price, current_price)
                managed.position.current_price_sol = current_price

                # Calculate current multiple vs entry
                entry = managed.position.entry_price_sol
                if entry <= 0:
                    continue
                multiple = current_price / entry

                # ── Check 1: Emergency exit ────────────────────────────
                drop_pct = 1.0 - (current_price / entry)
                if drop_pct >= managed.exit_plan.emergency_drop_pct:
                    await self._trigger_emergency(managed, current_price, drop_pct)
                    continue

                # ── Check 2: Time exit ─────────────────────────────────
                elapsed = time.time() - managed.entry_time
                if elapsed >= managed.exit_plan.time_exit_seconds and managed.remaining_tokens > 0:
                    await self._trigger_time_exit(managed, current_price, elapsed)
                    continue

                # ── Check 3: Staged exits ──────────────────────────────
                for stage in managed.pending_stages():
                    trigger = stage.get("trigger_multiple", 999)
                    if multiple >= trigger:
                        await self._trigger_stage_exit(managed, stage, current_price, multiple)
                        break  # only one stage per check cycle

                # ── Check 4: Trailing stop ─────────────────────────────
                if managed.exit_plan.trailing_stop_pct > 0 and managed.stages_completed > 0:
                    trail_drop = 1.0 - (current_price / managed.highest_price)
                    if trail_drop >= managed.exit_plan.trailing_stop_pct:
                        await self._trigger_trailing_stop(managed, current_price, trail_drop)

            except Exception as e:
                log.error(f"Error checking {pos_id}: {e}")

    async def _trigger_stage_exit(self, managed, stage: dict, price: float, multiple: float):
        """Execute a staged sell."""
        sell_pct = stage.get("sell_pct", 0)
        tokens_to_sell = managed.position.size_tokens * sell_pct  # always % of ORIGINAL size

        if tokens_to_sell <= 0:
            return

        from shared.redis_bus import Channels
        await self.bus.publish(Channels.CMD_EXIT, {
            "position_id": managed.position.position_id,
            "mint": managed.position.mint,
            "amount_tokens": tokens_to_sell,
            "urgency": "normal",
            "stage": stage,
            "trigger_multiple": multiple,
            "current_price": price,
        })

        managed.remaining_tokens -= tokens_to_sell
        managed.stages_completed += 1
        stage["_executed"] = True

        realized = tokens_to_sell * (price - managed.position.entry_price_sol)
        managed.total_realized_sol += realized

        log.info(f"STAGE EXIT: {managed.position.position_id} | "
                 f"sell {sell_pct:.0%} at {multiple:.1f}x | "
                 f"{tokens_to_sell:.0f} tokens | "
                 f"realized ~{realized:+.4f} SOL | "
                 f"remaining: {managed.remaining_tokens:.0f} tokens")

    async def _trigger_time_exit(self, managed, price: float, elapsed: float):
        """Force sell all remaining tokens after time limit."""
        if managed.remaining_tokens <= 0:
            return

        from shared.redis_bus import Channels
        await self.bus.publish(Channels.CMD_EXIT, {
            "position_id": managed.position.position_id,
            "mint": managed.position.mint,
            "amount_tokens": managed.remaining_tokens,
            "urgency": "high",
            "stage": {"type": "time_exit", "elapsed_seconds": elapsed},
            "current_price": price,
        })

        log.warning(f"TIME EXIT: {managed.position.position_id} | "
                    f"{elapsed:.0f}s elapsed | "
                    f"selling {managed.remaining_tokens:.0f} remaining tokens")
        managed.remaining_tokens = 0

    async def _trigger_emergency(self, managed, price: float, drop_pct: float):
        """Emergency liquidation — price dropped too far."""
        if managed.remaining_tokens <= 0:
            return

        from shared.redis_bus import Channels
        await self.bus.publish(Channels.CMD_EMERGENCY, {
            "position_id": managed.position.position_id,
            "mint": managed.position.mint,
            "amount_tokens": managed.remaining_tokens,
            "drop_pct": drop_pct,
            "current_price": price,
        })

        log.warning(f"EMERGENCY EXIT: {managed.position.position_id} | "
                    f"price dropped {drop_pct:.1%} | "
                    f"liquidating {managed.remaining_tokens:.0f} tokens")
        managed.remaining_tokens = 0

    async def _trigger_trailing_stop(self, managed, price: float, trail_drop: float):
        """Trailing stop hit — protect profits after a stage exit."""
        if managed.remaining_tokens <= 0:
            return

        from shared.redis_bus import Channels
        await self.bus.publish(Channels.CMD_EXIT, {
            "position_id": managed.position.position_id,
            "mint": managed.position.mint,
            "amount_tokens": managed.remaining_tokens,
            "urgency": "high",
            "stage": {"type": "trailing_stop", "drop_from_high": trail_drop},
            "current_price": price,
        })

        log.info(f"TRAILING STOP: {managed.position.position_id} | "
                 f"dropped {trail_drop:.1%} from high | "
                 f"selling {managed.remaining_tokens:.0f} tokens")
        managed.remaining_tokens = 0

    def get_status(self) -> List[dict]:
        """Return status of all managed positions for the dashboard."""
        statuses = []
        for pos_id, m in self.positions.items():
            entry = m.position.entry_price_sol
            current = m.position.current_price_sol
            multiple = current / entry if entry > 0 else 0
            statuses.append({
                "position_id": pos_id,
                "bot": m.position.bot,
                "mint": m.position.mint[:12],
                "entry_price": entry,
                "current_price": current,
                "multiple": round(multiple, 2),
                "remaining_tokens": m.remaining_tokens,
                "original_tokens": m.position.size_tokens,
                "stages_completed": m.stages_completed,
                "stages_total": len(m.exit_plan.stages),
                "total_realized_sol": round(m.total_realized_sol, 6),
                "age_seconds": round(time.time() - m.entry_time),
                "highest_price": m.highest_price,
            })
        return statuses


class ManagedPosition:
    """Internal wrapper around a Position with exit tracking state."""

    def __init__(self, position: Position, exit_plan: ExitPlan,
                 entry_time: float, remaining_tokens: float, highest_price: float):
        self.position = position
        self.exit_plan = exit_plan
        self.entry_time = entry_time
        self.remaining_tokens = remaining_tokens
        self.highest_price = highest_price
        self.stages_completed = 0
        self.total_realized_sol = 0.0

    def pending_stages(self) -> List[dict]:
        """Return stages that haven't been executed yet."""
        return [s for s in self.exit_plan.stages if not s.get("_executed")]


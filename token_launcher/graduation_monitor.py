"""
PumpDesk v2 — Token Launcher: Graduation Monitor
Tracks launched tokens through their bonding curve lifecycle.

After we launch a token, we need to:
  1. Monitor curve progress — is it filling?
  2. If curve stalls, trigger volume bot to boost visibility
  3. If curve approaches 100%, prepare for graduation
  4. On graduation: earn creator fees (0.3-0.95% of all future trading)
  5. Post-graduation: decide whether to hold LP or sell position

A graduated token with sustained volume is a perpetual revenue stream
through creator fees. This is the highest long-term ROI strategy.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from shared.redis_bus import RedisBus, Channels
from shared.models import utcnow

log = logging.getLogger("pumpdesk.launcher.monitor")


@dataclass
class LaunchedToken:
    """A token we created and are monitoring through graduation."""
    mint: str
    symbol: str
    name: str
    creator_wallet: str
    bonding_curve: str
    dev_buy_sol: float
    bundle_wallets: int
    total_sol_invested: float
    curve_pct: float = 0.0
    status: str = "live"           # live | stalled | graduating | graduated | dead
    created_at: str = ""
    graduated_at: str = ""
    volume_bot_active: bool = False

    # Revenue tracking
    creator_fee_earned: float = 0.0
    total_sells_sol: float = 0.0
    pnl_sol: float = 0.0

    # Stall detection
    last_curve_change: float = 0.0
    stall_minutes: float = 0.0

    @property
    def near_graduation(self) -> bool:
        return self.curve_pct >= 0.90

    @property
    def stalled(self) -> bool:
        return self.stall_minutes > 15 and self.curve_pct < 0.50


class GraduationMonitor:
    """Monitors all launched tokens and manages their lifecycle."""

    def __init__(self, bus: RedisBus):
        self.bus = bus
        self.tokens: Dict[str, LaunchedToken] = {}

    def add_token(self, token: LaunchedToken):
        self.tokens[token.mint] = token
        token.last_curve_change = time.time()
        log.info(f"Monitoring launched token: {token.symbol} ({token.mint[:12]})")

    async def check_all(self, curve_fetcher):
        """Check all launched tokens — call periodically."""
        for mint, token in list(self.tokens.items()):
            if token.status in ("graduated", "dead"):
                continue

            try:
                state = await curve_fetcher(token.bonding_curve, mint)
                if not state:
                    continue

                old_pct = token.curve_pct
                token.curve_pct = state.curve_pct

                # Track stall
                if abs(state.curve_pct - old_pct) > 0.001:
                    token.last_curve_change = time.time()
                    token.stall_minutes = 0
                else:
                    token.stall_minutes = (time.time() - token.last_curve_change) / 60

                # Status transitions
                if state.graduated:
                    await self._on_graduated(token)
                elif token.stalled and not token.volume_bot_active:
                    await self._on_stalled(token)
                elif token.near_graduation:
                    token.status = "graduating"
                    log.info(f"{token.symbol}: approaching graduation at {token.curve_pct:.1%}")

            except Exception as e:
                log.error(f"Error checking {token.symbol}: {e}")

    async def _on_graduated(self, token: LaunchedToken):
        """Token graduated to PumpSwap — creator fees are now active."""
        token.status = "graduated"
        token.graduated_at = utcnow()

        await self.bus.publish(Channels.LAUNCH_GRADUATED, {
            "mint": token.mint,
            "symbol": token.symbol,
            "total_invested": token.total_sol_invested,
            "timestamp": utcnow(),
        })

        log.info(f"GRADUATED: {token.symbol} | invested={token.total_sol_invested:.3f} SOL | "
                 f"creator fees now active (0.3-0.95%)")

    async def _on_stalled(self, token: LaunchedToken):
        """Curve stalled — request volume bot activation."""
        token.status = "stalled"

        await self.bus.publish(Channels.VOLUME_CONTROL, {
            "mint": token.mint,
            "symbol": token.symbol,
            "action": "start",
            "intensity": 0.5,
            "reason": f"Stalled at {token.curve_pct:.1%} for {token.stall_minutes:.0f}min",
        })

        token.volume_bot_active = True
        log.warning(f"STALLED: {token.symbol} at {token.curve_pct:.1%} — requesting volume bot")

    def get_portfolio(self) -> list:
        """Return all launched tokens for dashboard."""
        return [
            {
                "mint": t.mint[:12],
                "symbol": t.symbol,
                "status": t.status,
                "curve_pct": round(t.curve_pct, 3),
                "invested_sol": t.total_sol_invested,
                "pnl_sol": t.pnl_sol,
                "creator_fee_earned": t.creator_fee_earned,
                "stall_minutes": round(t.stall_minutes),
                "volume_bot": t.volume_bot_active,
            }
            for t in self.tokens.values()
        ]


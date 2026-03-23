"""
PumpDesk v2 — Graduation Sniper: Curve Analyzer
Reads bonding curve account state to calculate % completion,
velocity (how fast the curve is filling), holder count trends,
and estimated time to graduation.

PumpFun bonding curve mechanics:
  - 800M tokens on the curve out of 1B total supply
  - Tokens priced on an exponential curve — early buyers get cheapest
  - When 800M are sold (curve 100%), token graduates to PumpSwap at ~$69K mcap
  - Graduation fee: 0.015 SOL from liquidity
  - Post-graduation: LP tokens burned, open AMM trading begins

Our edge: buying at 85-95% curve when graduation is near-certain but
the price hasn't fully reflected the PumpSwap listing premium yet.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List

from shared.config import (
    BONDING_CURVE_SUPPLY, TOTAL_TOKEN_SUPPLY,
    PUMPFUN_GRADUATION_MCAP_USD, SOLANA_RPC_URL
)

log = logging.getLogger("pumpdesk.sniper.curve")


@dataclass
class CurveState:
    """Snapshot of a bonding curve's state at a point in time."""
    mint: str
    bonding_curve: str
    curve_pct: float = 0.0           # 0.0 to 1.0
    tokens_sold: float = 0.0         # how many of the 800M have been bought
    tokens_remaining: float = 0.0
    virtual_sol_reserves: float = 0.0
    virtual_token_reserves: float = 0.0
    real_sol_reserves: float = 0.0
    real_token_reserves: float = 0.0
    price_sol: float = 0.0           # current price per token in SOL
    mcap_usd: float = 0.0
    unique_holders: int = 0
    creator: str = ""
    created_at_slot: int = 0
    last_trade_slot: int = 0
    slot: int = 0
    timestamp: float = 0.0

    @property
    def near_graduation(self) -> bool:
        return self.curve_pct >= 0.85

    @property
    def very_near(self) -> bool:
        return self.curve_pct >= 0.95

    @property
    def graduated(self) -> bool:
        return self.curve_pct >= 1.0


@dataclass
class CurveVelocity:
    """Tracks how fast a bonding curve is filling over time."""
    mint: str
    snapshots: List[tuple] = field(default_factory=list)  # (timestamp, curve_pct)
    max_snapshots: int = 60

    def add(self, pct: float):
        now = time.time()
        self.snapshots.append((now, pct))
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots = self.snapshots[-self.max_snapshots:]

    @property
    def pct_per_minute(self) -> float:
        """How many percentage points the curve fills per minute."""
        if len(self.snapshots) < 2:
            return 0.0
        first_t, first_pct = self.snapshots[0]
        last_t, last_pct = self.snapshots[-1]
        elapsed_min = (last_t - first_t) / 60
        if elapsed_min <= 0:
            return 0.0
        return (last_pct - first_pct) / elapsed_min

    @property
    def est_minutes_to_graduation(self) -> float:
        """Estimated minutes until curve hits 100%."""
        vel = self.pct_per_minute
        if vel <= 0:
            return float('inf')
        remaining = 1.0 - (self.snapshots[-1][1] if self.snapshots else 0)
        return remaining / vel

    @property
    def accelerating(self) -> bool:
        """Is the velocity increasing? (demand accelerating)"""
        if len(self.snapshots) < 10:
            return False
        mid = len(self.snapshots) // 2
        first_half = self.snapshots[:mid]
        second_half = self.snapshots[mid:]

        def half_velocity(snaps):
            if len(snaps) < 2:
                return 0
            dt = snaps[-1][0] - snaps[0][0]
            dp = snaps[-1][1] - snaps[0][1]
            return dp / dt if dt > 0 else 0

        return half_velocity(second_half) > half_velocity(first_half) * 1.2


class CurveAnalyzer:
    """Fetches and analyzes PumpFun bonding curve states."""

    def __init__(self):
        self.velocities: dict[str, CurveVelocity] = {}

    async def fetch_curve_state(self, bonding_curve_address: str, mint: str) -> Optional[CurveState]:
        """Fetch the current state of a bonding curve account via RPC."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getAccountInfo",
                    "params": [bonding_curve_address, {"encoding": "base64"}]
                }
                async with session.post(SOLANA_RPC_URL, json=payload) as resp:
                    data = await resp.json()
                    result = data.get("result")
                    if not result or not result.get("value"):
                        return None

                    account_data = result["value"]["data"]
                    slot = result.get("context", {}).get("slot", 0)

                    # Parse the bonding curve account data
                    # PumpFun uses Anchor — account has 8-byte discriminator + fields
                    state = self._parse_curve_account(account_data, mint, bonding_curve_address, slot)
                    if state:
                        self._update_velocity(state)
                    return state

        except Exception as e:
            log.error(f"fetch_curve_state failed for {bonding_curve_address[:12]}: {e}")
            return None

    def _parse_curve_account(self, data: list, mint: str, bc_addr: str, slot: int) -> Optional[CurveState]:
        """Parse PumpFun bonding curve account data.
        Account layout (Anchor, after 8-byte discriminator):
          - virtual_token_reserves: u64
          - virtual_sol_reserves: u64
          - real_token_reserves: u64
          - real_sol_reserves: u64
          - token_total_supply: u64
          - complete: bool
        """
        import base64
        import struct

        try:
            if isinstance(data, list) and len(data) >= 1:
                raw = base64.b64decode(data[0])
            else:
                return None

            if len(raw) < 8 + 40:  # discriminator + 5 u64s
                return None

            # Skip 8-byte Anchor discriminator
            offset = 8
            virtual_token = struct.unpack_from('<Q', raw, offset)[0]; offset += 8
            virtual_sol = struct.unpack_from('<Q', raw, offset)[0]; offset += 8
            real_token = struct.unpack_from('<Q', raw, offset)[0]; offset += 8
            real_sol = struct.unpack_from('<Q', raw, offset)[0]; offset += 8
            token_supply = struct.unpack_from('<Q', raw, offset)[0]; offset += 8
            complete = raw[offset] if offset < len(raw) else 0

            # PumpFun tokens are 6 decimals
            vt = virtual_token / 1e6
            vs = virtual_sol / 1e9  # SOL is 9 decimals
            rt = real_token / 1e6
            rs = real_sol / 1e9

            # Calculate curve completion
            tokens_sold = BONDING_CURVE_SUPPLY - rt
            curve_pct = tokens_sold / BONDING_CURVE_SUPPLY if BONDING_CURVE_SUPPLY > 0 else 0
            curve_pct = min(1.0, max(0.0, curve_pct))

            # Current price from virtual reserves (constant product)
            price_sol = vs / vt if vt > 0 else 0

            if complete:
                curve_pct = 1.0

            return CurveState(
                mint=mint,
                bonding_curve=bc_addr,
                curve_pct=curve_pct,
                tokens_sold=tokens_sold,
                tokens_remaining=rt,
                virtual_sol_reserves=vs,
                virtual_token_reserves=vt,
                real_sol_reserves=rs,
                real_token_reserves=rt,
                price_sol=price_sol,
                slot=slot,
                timestamp=time.time(),
            )

        except Exception as e:
            log.error(f"_parse_curve_account error: {e}")
            return None

    def _update_velocity(self, state: CurveState):
        """Track velocity for this mint."""
        if state.mint not in self.velocities:
            self.velocities[state.mint] = CurveVelocity(mint=state.mint)
        self.velocities[state.mint].add(state.curve_pct)

    def get_velocity(self, mint: str) -> Optional[CurveVelocity]:
        return self.velocities.get(mint)

    def should_snipe(self, state: CurveState) -> tuple[bool, float, str]:
        """Determine if this token is worth sniping.
        Returns (should_buy, confidence, reason)."""

        if state.graduated:
            return False, 0, "Already graduated"

        if state.curve_pct < 0.85:
            return False, 0, f"Too early: {state.curve_pct:.1%}"

        vel = self.get_velocity(state.mint)
        confidence = 0.5  # base

        reasons = []

        # Higher curve % = higher confidence
        if state.curve_pct >= 0.95:
            confidence += 0.25
            reasons.append(f"curve {state.curve_pct:.1%}")
        elif state.curve_pct >= 0.90:
            confidence += 0.15
            reasons.append(f"curve {state.curve_pct:.1%}")
        else:
            confidence += 0.05
            reasons.append(f"curve {state.curve_pct:.1%}")

        # Velocity bonus
        if vel:
            if vel.pct_per_minute > 0.01:
                confidence += 0.10
                reasons.append(f"fast fill {vel.pct_per_minute:.3f}%/min")
            if vel.accelerating:
                confidence += 0.10
                reasons.append("accelerating")
            eta = vel.est_minutes_to_graduation
            if 0 < eta < 10:
                confidence += 0.05
                reasons.append(f"ETA {eta:.0f}min")

        # SOL reserves as proxy for real demand
        if state.real_sol_reserves > 50:
            confidence += 0.05
            reasons.append(f"{state.real_sol_reserves:.0f} SOL in curve")

        confidence = min(1.0, confidence)
        reason = " | ".join(reasons)

        return True, confidence, reason


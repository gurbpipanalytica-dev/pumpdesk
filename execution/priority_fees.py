"""
PumpDesk v2 — Execution Engine: Priority Fee Manager
Dynamically calculates optimal priority fees based on network congestion.
Too low = transaction dropped. Too high = wasted SOL.
"""

import logging
import time
from typing import Optional

from execution.solana_client import SolanaClient

log = logging.getLogger("pumpdesk.execution.fees")


class PriorityFeeManager:
    """Tracks recent fee levels and recommends optimal priority fees."""

    def __init__(self, solana: SolanaClient):
        self.solana = solana
        self._fee_cache: list = []  # (timestamp, fee_estimate)
        self._cache_ttl = 10  # refresh every 10 seconds

    async def get_optimal_fee(self, urgency: str = "normal") -> int:
        """Get recommended priority fee in microlamports per compute unit.

        urgency:
            - "low": bottom 25th percentile — for LP farming, non-urgent
            - "normal": median — for standard trades
            - "high": 75th percentile — for copy trades, time-sensitive
            - "critical": 90th percentile — for graduation snipes, arb
        """
        fees = await self._get_recent_fees()
        if not fees:
            # Fallback defaults when no data available
            defaults = {"low": 1_000, "normal": 5_000, "high": 25_000, "critical": 100_000}
            return defaults.get(urgency, 5_000)

        fees_sorted = sorted(fees)
        n = len(fees_sorted)

        percentiles = {
            "low": fees_sorted[max(0, n // 4)],
            "normal": fees_sorted[n // 2],
            "high": fees_sorted[min(n - 1, n * 3 // 4)],
            "critical": fees_sorted[min(n - 1, n * 9 // 10)],
        }

        fee = percentiles.get(urgency, percentiles["normal"])
        log.debug(f"Priority fee ({urgency}): {fee} microlamports/CU")
        return fee

    async def _get_recent_fees(self) -> list:
        """Fetch recent priority fee levels from the network."""
        now = time.time()

        # Return cached if fresh
        if self._fee_cache and (now - self._fee_cache[0][0]) < self._cache_ttl:
            return [f for _, f in self._fee_cache]

        try:
            data = await self.solana.rpc_call("getRecentPrioritizationFees")
            result = data.get("result", [])
            fees = [entry.get("prioritizationFee", 0) for entry in result if entry.get("prioritizationFee", 0) > 0]
            if fees:
                self._fee_cache = [(now, f) for f in fees]
            return fees
        except Exception as e:
            log.warning(f"Failed to fetch priority fees: {e}")
            return [f for _, f in self._fee_cache]  # return stale cache

    def estimate_tx_cost_sol(self, compute_units: int, priority_fee: int) -> float:
        """Estimate total transaction cost in SOL.
        Base fee (5000 lamports) + priority fee."""
        base_fee = 5000  # lamports
        priority_cost = (compute_units * priority_fee) / 1_000_000  # microlamports to lamports
        total_lamports = base_fee + priority_cost
        return total_lamports / 1_000_000_000


"""
PumpDesk v2 — Jito Backrun Arb: Route Calculator
Finds profitable backrun arbitrage routes after detecting a large trade.

How backrunning works:
  1. Someone sells 250M BONK for 100 USDC on Raydium
  2. This creates a temporary price imbalance — BONK is now cheaper on Raydium
  3. We buy BONK cheap on Raydium and sell it at the old (higher) price on Orca
  4. Profit = price difference minus fees and Jito tip
  5. All done in a single Jito bundle, right after their trade

Route types:
  - 2-hop: Buy on DEX_A → Sell on DEX_B (same pair, different venue)
  - 3-hop: Buy on DEX_A → Swap on DEX_B → Sell on DEX_C (triangular)

Based on Jito Labs' open-source reference implementation.
"""

import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from jito_backrunner.pool_tracker import PoolTracker, PoolState

log = logging.getLogger("pumpdesk.backrunner.routes")

# SOL and USDC mints — the two main quote currencies
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

QUOTE_MINTS = {SOL_MINT, USDC_MINT}


@dataclass
class ArbRoute:
    """A calculated arbitrage route with expected profit."""
    route_type: str              # "2hop" | "3hop"
    hops: List[dict]             # [{pool, input_mint, output_mint, amount_in, amount_out}, ...]
    input_mint: str              # what we start with (usually SOL or USDC)
    input_amount: float          # how much we put in
    output_amount: float         # how much we get back
    profit: float                # output - input
    profit_pct: float            # profit / input
    estimated_fees_sol: float    # Jito tip + tx fees
    net_profit: float            # profit - fees
    latency_ms: float = 0.0

    @property
    def profitable(self) -> bool:
        return self.net_profit > 0


class RouteCalculator:
    """Calculates profitable backrun routes from a detected trade."""

    def __init__(self, pool_tracker: PoolTracker):
        self.pools = pool_tracker
        self.min_profit_sol = 0.001    # minimum profit to execute (0.001 SOL)
        self.jito_tip_sol = 0.00001    # Jito tip (adjustable)
        self.tx_fee_sol = 0.000005     # base tx fee
        self.num_steps = 20            # granularity of amount search

    def find_backrun(self, trade_mint: str, trade_quote: str,
                     trade_amount: float, trade_direction: str) -> Optional[ArbRoute]:
        """Find the best backrun route for a detected trade.

        Args:
            trade_mint: the token that was traded (e.g., BONK mint)
            trade_quote: the quote currency (SOL or USDC)
            trade_amount: size of the original trade in quote currency
            trade_direction: "buy" or "sell" — what the original trader did

        Returns:
            Best profitable ArbRoute, or None if no arb exists.
        """
        start = time.monotonic()

        # The backrun trades in the OPPOSITE direction of the original trade
        # If someone sold BONK, we BUY BONK (it's now cheaper) then sell elsewhere
        # If someone bought BONK, we SELL BONK (it's now more expensive) then buy elsewhere
        
        routes = []

        # Try 2-hop routes
        two_hops = self._find_2hop_routes(trade_mint, trade_quote, trade_amount, trade_direction)
        routes.extend(two_hops)

        # Try 3-hop routes (triangular via SOL or USDC bridge)
        three_hops = self._find_3hop_routes(trade_mint, trade_quote, trade_amount, trade_direction)
        routes.extend(three_hops)

        # Pick the best profitable route
        profitable = [r for r in routes if r.profitable]
        if not profitable:
            return None

        best = max(profitable, key=lambda r: r.net_profit)
        best.latency_ms = (time.monotonic() - start) * 1000

        log.info(f"Backrun found: {best.route_type} | "
                 f"profit={best.net_profit:.6f} SOL ({best.profit_pct:.2%}) | "
                 f"{best.latency_ms:.1f}ms")

        return best

    def _find_2hop_routes(self, mint: str, quote: str,
                          amount: float, direction: str) -> List[ArbRoute]:
        """Find 2-hop routes: buy on one DEX, sell on another."""
        routes = []
        pools = self.pools.get_pools_for_pair(mint, quote)

        if len(pools) < 2:
            return routes

        # For each pair of pools, check if buying on one and selling on the other is profitable
        for i, buy_pool in enumerate(pools):
            for j, sell_pool in enumerate(pools):
                if i == j:
                    continue

                # Search for optimal input amount
                best_profit = 0
                best_amount = 0

                for step in range(1, self.num_steps + 1):
                    test_amount = (amount * step) / self.num_steps

                    # Buy mint with quote on buy_pool
                    mint_received = buy_pool.get_output(test_amount, input_is_a=(buy_pool.token_a_mint == quote))

                    if mint_received <= 0:
                        continue

                    # Sell mint for quote on sell_pool
                    quote_received = sell_pool.get_output(mint_received, input_is_a=(sell_pool.token_a_mint == mint))

                    profit = quote_received - test_amount
                    if profit > best_profit:
                        best_profit = profit
                        best_amount = test_amount

                if best_profit > 0:
                    fees = self.jito_tip_sol + self.tx_fee_sol
                    net = best_profit - fees

                    routes.append(ArbRoute(
                        route_type="2hop",
                        hops=[
                            {"pool": buy_pool.pool_address, "dex": buy_pool.dex,
                             "input_mint": quote, "output_mint": mint, "amount_in": best_amount},
                            {"pool": sell_pool.pool_address, "dex": sell_pool.dex,
                             "input_mint": mint, "output_mint": quote},
                        ],
                        input_mint=quote,
                        input_amount=best_amount,
                        output_amount=best_amount + best_profit,
                        profit=best_profit,
                        profit_pct=best_profit / best_amount if best_amount > 0 else 0,
                        estimated_fees_sol=fees,
                        net_profit=net,
                    ))

        return routes

    def _find_3hop_routes(self, mint: str, quote: str,
                          amount: float, direction: str) -> List[ArbRoute]:
        """Find 3-hop triangular routes via a bridge currency.
        Example: USDC → BONK (Raydium) → SOL (Orca) → USDC (Raydium)"""
        routes = []

        # Determine bridge currency
        bridges = [m for m in QUOTE_MINTS if m != quote]

        for bridge in bridges:
            # Hop 1: quote → mint
            pools_1 = self.pools.get_pools_for_pair(mint, quote)
            # Hop 2: mint → bridge
            pools_2 = self.pools.get_pools_for_pair(mint, bridge)
            # Hop 3: bridge → quote
            pools_3 = self.pools.get_pools_for_pair(bridge, quote)

            if not pools_1 or not pools_2 or not pools_3:
                continue

            # Use best pool for each hop
            p1 = max(pools_1, key=lambda p: p.reserve_a + p.reserve_b)
            p2 = max(pools_2, key=lambda p: p.reserve_a + p.reserve_b)
            p3 = max(pools_3, key=lambda p: p.reserve_a + p.reserve_b)

            # Search optimal amount
            best_profit = 0
            best_amount = 0

            for step in range(1, self.num_steps + 1):
                test_amount = (amount * step) / self.num_steps

                out_1 = p1.get_output(test_amount, input_is_a=(p1.token_a_mint == quote))
                if out_1 <= 0:
                    continue
                out_2 = p2.get_output(out_1, input_is_a=(p2.token_a_mint == mint))
                if out_2 <= 0:
                    continue
                out_3 = p3.get_output(out_2, input_is_a=(p3.token_a_mint == bridge))

                profit = out_3 - test_amount
                if profit > best_profit:
                    best_profit = profit
                    best_amount = test_amount

            if best_profit > 0:
                fees = self.jito_tip_sol + (self.tx_fee_sol * 2)  # more hops = more fees
                net = best_profit - fees

                routes.append(ArbRoute(
                    route_type="3hop",
                    hops=[
                        {"pool": p1.pool_address, "dex": p1.dex, "input_mint": quote, "output_mint": mint},
                        {"pool": p2.pool_address, "dex": p2.dex, "input_mint": mint, "output_mint": bridge},
                        {"pool": p3.pool_address, "dex": p3.dex, "input_mint": bridge, "output_mint": quote},
                    ],
                    input_mint=quote,
                    input_amount=best_amount,
                    output_amount=best_amount + best_profit,
                    profit=best_profit,
                    profit_pct=best_profit / best_amount if best_amount > 0 else 0,
                    estimated_fees_sol=fees,
                    net_profit=net,
                ))

        return routes


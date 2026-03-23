"""
PumpDesk v2 — Jito Backrun Arb: Pool Tracker
Maintains real-time state of all DEX pool accounts across Solana.
Uses Geyser gRPC (if available) or WebSocket subscriptions to track:
  - Raydium AMM v4 + CLMM pools
  - Orca Whirlpools
  - PumpSwap constant-product pools
  - Meteora DLMM pools

Every pool update feeds into the route calculator for accurate arb math.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from shared.config import SOLANA_WS_URL, GEYSER_GRPC_URL

log = logging.getLogger("pumpdesk.backrunner.pools")

# Known DEX program IDs on Solana
DEX_PROGRAMS = {
    "raydium_amm":   "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "raydium_clmm":  "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "orca_whirlpool": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
    "meteora_dlmm":  "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
    "pumpswap":      "",  # filled from config
}


@dataclass
class PoolState:
    """Real-time state of a DEX liquidity pool."""
    pool_address: str
    dex: str                          # raydium_amm | raydium_clmm | orca | meteora | pumpswap
    token_a_mint: str = ""
    token_b_mint: str = ""
    token_a_vault: str = ""           # vault account holding token A
    token_b_vault: str = ""           # vault account holding token B
    reserve_a: float = 0.0            # current reserve of token A
    reserve_b: float = 0.0            # current reserve of token B
    fee_bps: int = 30                 # pool fee in basis points (default 0.3%)
    last_updated: float = 0.0
    slot: int = 0

    @property
    def stale(self) -> bool:
        return time.time() - self.last_updated > 30

    def get_price_a_in_b(self) -> float:
        """Price of token A denominated in token B (constant product)."""
        if self.reserve_a <= 0:
            return 0.0
        return self.reserve_b / self.reserve_a

    def get_output(self, input_amount: float, input_is_a: bool) -> float:
        """Calculate output amount for a given input (constant product AMM).
        Includes fee deduction."""
        if input_is_a:
            reserve_in, reserve_out = self.reserve_a, self.reserve_b
        else:
            reserve_in, reserve_out = self.reserve_b, self.reserve_a

        if reserve_in <= 0 or reserve_out <= 0:
            return 0.0

        fee_multiplier = 1 - (self.fee_bps / 10000)
        amount_in_after_fee = input_amount * fee_multiplier
        output = (reserve_out * amount_in_after_fee) / (reserve_in + amount_in_after_fee)
        return output


class PoolTracker:
    """Tracks all DEX pool states in real-time."""

    def __init__(self):
        self.pools: Dict[str, PoolState] = {}
        # Mint pair index: (mint_a, mint_b) -> [pool_address, ...]
        self.pair_index: Dict[tuple, list] = {}
        # Vault to pool mapping for fast updates
        self.vault_to_pool: Dict[str, str] = {}

    def register_pool(self, pool: PoolState):
        """Add or update a pool in the tracker."""
        self.pools[pool.pool_address] = pool

        # Index by mint pair (both directions)
        pair = (pool.token_a_mint, pool.token_b_mint)
        pair_rev = (pool.token_b_mint, pool.token_a_mint)
        for p in (pair, pair_rev):
            if p not in self.pair_index:
                self.pair_index[p] = []
            if pool.pool_address not in self.pair_index[p]:
                self.pair_index[p].append(pool.pool_address)

        # Map vaults to pool for balance update routing
        if pool.token_a_vault:
            self.vault_to_pool[pool.token_a_vault] = pool.pool_address
        if pool.token_b_vault:
            self.vault_to_pool[pool.token_b_vault] = pool.pool_address

    def update_vault_balance(self, vault_address: str, new_balance: float, slot: int):
        """Called when a vault balance changes (from Geyser/WS subscription)."""
        pool_addr = self.vault_to_pool.get(vault_address)
        if not pool_addr:
            return
        pool = self.pools.get(pool_addr)
        if not pool:
            return
        if vault_address == pool.token_a_vault:
            pool.reserve_a = new_balance
        elif vault_address == pool.token_b_vault:
            pool.reserve_b = new_balance
        pool.last_updated = time.time()
        pool.slot = slot

    def get_pools_for_pair(self, mint_a: str, mint_b: str) -> list[PoolState]:
        """Get all pools that trade a specific pair."""
        pair = (mint_a, mint_b)
        addresses = self.pair_index.get(pair, [])
        return [self.pools[a] for a in addresses if a in self.pools and not self.pools[a].stale]

    def get_best_pool_for_pair(self, mint_a: str, mint_b: str) -> Optional[PoolState]:
        """Get the pool with the most liquidity for a pair."""
        pools = self.get_pools_for_pair(mint_a, mint_b)
        if not pools:
            return None
        return max(pools, key=lambda p: p.reserve_a + p.reserve_b)

    def get_all_vaults(self) -> list[str]:
        """Get all vault addresses for subscription."""
        return list(self.vault_to_pool.keys())

    def stats(self) -> dict:
        active = sum(1 for p in self.pools.values() if not p.stale)
        return {
            "total_pools": len(self.pools),
            "active_pools": active,
            "pairs_indexed": len(self.pair_index),
            "vaults_tracked": len(self.vault_to_pool),
        }


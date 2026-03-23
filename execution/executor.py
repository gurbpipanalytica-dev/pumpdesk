"""
PumpDesk v2 — Execution Engine: Jito Bundle Executor
Builds and submits Jito bundles for atomic transaction execution.
Supports: single buys, single sells, bundled launches (create + multi-wallet buy),
and same-block buy+sell for volume bot.

In paper mode, simulates everything without hitting Solana.
"""

import logging
import json
import time
import aiohttp
from typing import Optional, List
from dataclasses import dataclass

from shared.config import (
    JITO_BLOCK_ENGINE_URL, JITO_TIP_LAMPORTS, PAPER_MODE,
    PUMPFUN_PROGRAM_ID
)
from shared.models import Signal, Decision, Position, utcnow

log = logging.getLogger("pumpdesk.execution.executor")


@dataclass
class TradeResult:
    """Result of a trade execution attempt."""
    success: bool
    signature: str = ""
    error: str = ""
    size_sol: float = 0.0
    size_tokens: float = 0.0
    price_sol: float = 0.0
    fees_sol: float = 0.0
    latency_ms: float = 0.0
    paper: bool = False


class JitoExecutor:
    """Builds and submits transactions via Jito block engine."""

    def __init__(self, solana_client, priority_fee_manager, risk_manager):
        self.solana = solana_client
        self.fees = priority_fee_manager
        self.risk = risk_manager
        self._session: Optional[aiohttp.ClientSession] = None
        self._jito_url = JITO_BLOCK_ENGINE_URL

    async def connect(self):
        self._session = aiohttp.ClientSession()
        log.info(f"Jito executor connected: {self._jito_url}")

    async def disconnect(self):
        if self._session:
            await self._session.close()

    # ══════════════════════════════════════════════════════════════════════════
    #  BUY — single token purchase (used by sniper, copier, momentum, arb)
    # ══════════════════════════════════════════════════════════════════════════

    async def execute_buy(self, decision: Decision, signal: Signal) -> TradeResult:
        """Execute a buy order for a PumpFun/PumpSwap token."""
        start = time.monotonic()

        # Final risk check
        approved, reason = self.risk.validate_trade(decision, signal)
        if not approved and reason != "paper_mode":
            return TradeResult(success=False, error=f"Risk rejected: {reason}")

        size_sol = decision.adjusted_size_sol
        mint = signal.token.mint
        is_graduated = signal.token.is_graduated

        if PAPER_MODE:
            # Simulate the trade
            elapsed = (time.monotonic() - start) * 1000
            simulated_tokens = size_sol / max(signal.token.price_sol, 0.000001)
            log.info(f"PAPER BUY: {size_sol:.4f} SOL → {simulated_tokens:.0f} tokens "
                     f"({signal.token.symbol or mint[:12]}) | {elapsed:.1f}ms")
            self.risk.on_position_opened(size_sol)
            return TradeResult(
                success=True,
                signature=f"PAPER-{int(time.time())}",
                size_sol=size_sol,
                size_tokens=simulated_tokens,
                price_sol=signal.token.price_sol,
                latency_ms=elapsed,
                paper=True,
            )

        # ── LIVE MODE ──────────────────────────────────────────────────
        try:
            priority_fee = await self.fees.get_optimal_fee(
                urgency="critical" if signal.bot in ("graduation_sniper", "curve_arb") else "high"
            )

            if is_graduated:
                result = await self._buy_pumpswap(mint, size_sol, priority_fee)
            else:
                result = await self._buy_pumpfun(mint, size_sol, priority_fee)

            elapsed = (time.monotonic() - start) * 1000
            result.latency_ms = elapsed

            if result.success:
                self.risk.on_position_opened(size_sol)
                log.info(f"BUY OK: {size_sol:.4f} SOL | {signal.token.symbol or mint[:12]} | "
                         f"sig={result.signature[:16]}... | {elapsed:.1f}ms")
            else:
                log.error(f"BUY FAILED: {result.error} | {signal.token.symbol or mint[:12]}")

            return result

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            log.error(f"BUY EXCEPTION: {e} | {elapsed:.1f}ms")
            return TradeResult(success=False, error=str(e), latency_ms=elapsed)

    # ══════════════════════════════════════════════════════════════════════════
    #  SELL — single token sell (used by progressive exit engine)
    # ══════════════════════════════════════════════════════════════════════════

    async def execute_sell(self, mint: str, amount_tokens: float, 
                           urgency: str = "high") -> TradeResult:
        """Execute a sell order."""
        start = time.monotonic()

        if PAPER_MODE:
            elapsed = (time.monotonic() - start) * 1000
            log.info(f"PAPER SELL: {amount_tokens:.0f} tokens ({mint[:12]}) | {elapsed:.1f}ms")
            return TradeResult(
                success=True,
                signature=f"PAPER-SELL-{int(time.time())}",
                size_tokens=amount_tokens,
                latency_ms=elapsed,
                paper=True,
            )

        try:
            priority_fee = await self.fees.get_optimal_fee(urgency=urgency)
            result = await self._sell_token(mint, amount_tokens, priority_fee)
            elapsed = (time.monotonic() - start) * 1000
            result.latency_ms = elapsed

            if result.success:
                log.info(f"SELL OK: {amount_tokens:.0f} tokens | {mint[:12]} | "
                         f"sig={result.signature[:16]}... | {elapsed:.1f}ms")
            return result

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            log.error(f"SELL EXCEPTION: {e}")
            return TradeResult(success=False, error=str(e), latency_ms=elapsed)

    # ══════════════════════════════════════════════════════════════════════════
    #  BUNDLE LAUNCH — create token + multi-wallet buy (token launcher)
    # ══════════════════════════════════════════════════════════════════════════

    async def execute_bundle_launch(self, launch_config: dict) -> TradeResult:
        """Atomic Jito bundle: create token + dev buy + N wallet buys in one block."""
        start = time.monotonic()

        if PAPER_MODE:
            elapsed = (time.monotonic() - start) * 1000
            total_sol = launch_config.get("dev_buy_sol", 0) + (
                launch_config.get("bundle_wallets", 0) * launch_config.get("bundle_sol_per_wallet", 0)
            )
            log.info(f"PAPER LAUNCH: {launch_config.get('symbol','?')} | "
                     f"{launch_config.get('bundle_wallets',0)+1} wallets | "
                     f"{total_sol:.3f} SOL total | {elapsed:.1f}ms")
            return TradeResult(
                success=True,
                signature=f"PAPER-LAUNCH-{int(time.time())}",
                size_sol=total_sol,
                latency_ms=elapsed,
                paper=True,
            )

        # Live bundle construction would go here:
        # 1. Create token instruction (PumpFun program)
        # 2. Dev wallet buy instruction
        # 3. N additional wallet buy instructions
        # 4. Jito tip instruction
        # 5. Bundle all into one Jito bundle
        # 6. Submit to block engine
        log.warning("Live bundle launch not yet implemented — use paper mode")
        return TradeResult(success=False, error="Live launch not implemented yet")

    # ══════════════════════════════════════════════════════════════════════════
    #  VOLUME — same-block buy+sell for anti-MEV volume generation
    # ══════════════════════════════════════════════════════════════════════════

    async def execute_volume_cycle(self, mint: str, sol_amount: float) -> TradeResult:
        """Buy and sell in the same block via Jito bundle. Net zero position."""
        start = time.monotonic()

        if PAPER_MODE:
            elapsed = (time.monotonic() - start) * 1000
            log.info(f"PAPER VOLUME: {sol_amount:.4f} SOL cycle on {mint[:12]} | {elapsed:.1f}ms")
            return TradeResult(
                success=True,
                signature=f"PAPER-VOL-{int(time.time())}",
                size_sol=sol_amount,
                latency_ms=elapsed,
                paper=True,
            )

        # Live: bundle buy+sell in same Jito bundle
        log.warning("Live volume cycle not yet implemented")
        return TradeResult(success=False, error="Live volume not implemented yet")

    # ══════════════════════════════════════════════════════════════════════════
    #  INTERNAL — protocol-specific transaction builders
    # ══════════════════════════════════════════════════════════════════════════

    async def _buy_pumpfun(self, mint: str, sol_amount: float, priority_fee: int) -> TradeResult:
        """Build and submit a PumpFun bonding curve buy transaction."""
        # This is where the actual PumpFun program instruction gets built:
        # 1. Get bonding curve + associated bonding curve accounts
        # 2. Build buy instruction with SOL amount and slippage
        # 3. Add compute budget + priority fee instructions
        # 4. Add Jito tip instruction
        # 5. Sign and submit via Jito bundle
        #
        # For now, placeholder — will implement with solders/solana-py
        log.warning("_buy_pumpfun: live implementation pending")
        return TradeResult(success=False, error="PumpFun buy not implemented yet")

    async def _buy_pumpswap(self, mint: str, sol_amount: float, priority_fee: int) -> TradeResult:
        """Build and submit a PumpSwap AMM buy transaction."""
        # PumpSwap uses constant product AMM (like Uniswap v2):
        # 1. Get pool accounts for the mint
        # 2. Calculate expected output with slippage
        # 3. Build swap instruction
        # 4. Add compute budget + priority fee
        # 5. Sign and submit
        log.warning("_buy_pumpswap: live implementation pending")
        return TradeResult(success=False, error="PumpSwap buy not implemented yet")

    async def _sell_token(self, mint: str, token_amount: float, priority_fee: int) -> TradeResult:
        """Build and submit a sell transaction (works for both PumpFun and PumpSwap)."""
        # 1. Check if token is still on bonding curve or graduated
        # 2. Build appropriate sell instruction
        # 3. Add compute budget + priority fee
        # 4. Sign and submit
        log.warning("_sell_token: live implementation pending")
        return TradeResult(success=False, error="Sell not implemented yet")

    async def _submit_jito_bundle(self, transactions: list) -> str:
        """Submit a bundle of transactions to Jito block engine.
        Returns bundle ID or empty string on failure."""
        try:
            url = f"{self._jito_url}/api/v1/bundles"
            payload = {"jsonrpc": "2.0", "id": 1, "method": "sendBundle", "params": [transactions]}
            async with self._session.post(url, json=payload) as resp:
                data = await resp.json()
                bundle_id = data.get("result", "")
                if bundle_id:
                    log.info(f"Jito bundle submitted: {bundle_id}")
                else:
                    log.error(f"Jito bundle failed: {data}")
                return bundle_id
        except Exception as e:
            log.error(f"Jito submission error: {e}")
            return ""


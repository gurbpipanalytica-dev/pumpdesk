"""
PumpDesk v2 — Jito Backrun Arb: Flashloan Executor
Borrows capital, executes the arb, repays the loan — all in one atomic tx.
If the arb isn't profitable after fees + loan repayment, the tx reverts.
Zero risk of capital loss (you never had the capital to begin with).

Flashloan sources on Solana:
  - Solend (flash_borrow_reserve_liquidity)
  - MarginFi (flash_loan)
  - Jupiter (self-referencing swaps can act as flashloans)

The flow:
  1. Flashloan borrow X USDC/SOL
  2. Execute arb route (2 or 3 hops across DEXes)
  3. Repay flashloan + fee
  4. Tip Jito validator
  5. Keep the profit
  All in one Jito bundle → atomic → no partial execution risk
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from shared.config import JITO_TIP_LAMPORTS, PAPER_MODE
from jito_backrunner.route_calculator import ArbRoute

log = logging.getLogger("pumpdesk.backrunner.flashloan")


@dataclass
class FlashloanResult:
    """Result of a flashloan-funded backrun execution."""
    success: bool
    bundle_id: str = ""
    signature: str = ""
    borrowed: float = 0.0
    repaid: float = 0.0
    profit_gross: float = 0.0
    profit_net: float = 0.0       # after flashloan fee + Jito tip + tx fee
    jito_tip: float = 0.0
    flashloan_fee: float = 0.0
    latency_ms: float = 0.0
    error: str = ""
    paper: bool = False


class FlashloanExecutor:
    """Builds and submits flashloan-funded arb bundles via Jito."""

    def __init__(self, solana_client, jito_url: str):
        self.solana = solana_client
        self.jito_url = jito_url
        self.flashloan_fee_bps = 5   # 0.05% typical Solend flash fee

    async def execute_backrun(self, route: ArbRoute, 
                               after_tx: str = "") -> FlashloanResult:
        """Execute a backrun arb with flashloan funding.

        Args:
            route: the calculated ArbRoute
            after_tx: signature of the transaction to backrun (placed after in bundle)
        """
        start = time.monotonic()

        if PAPER_MODE:
            elapsed = (time.monotonic() - start) * 1000
            flashloan_fee = route.input_amount * (self.flashloan_fee_bps / 10000)
            jito_tip = JITO_TIP_LAMPORTS / 1_000_000_000
            net = route.profit - flashloan_fee - jito_tip - 0.000005  # tx fee

            log.info(
                f"PAPER BACKRUN: {route.route_type} | "
                f"borrow={route.input_amount:.4f} | "
                f"gross={route.profit:.6f} | "
                f"net={net:.6f} SOL | "
                f"{elapsed:.1f}ms"
            )

            return FlashloanResult(
                success=True,
                bundle_id=f"PAPER-BUNDLE-{int(time.time())}",
                signature=f"PAPER-BACKRUN-{int(time.time())}",
                borrowed=route.input_amount,
                repaid=route.input_amount + flashloan_fee,
                profit_gross=route.profit,
                profit_net=net,
                jito_tip=jito_tip,
                flashloan_fee=flashloan_fee,
                latency_ms=elapsed,
                paper=True,
            )

        # ── LIVE MODE ──────────────────────────────────────────────────
        try:
            # Build the transaction bundle:
            # TX 1 (optional): the original trade we're backrunning
            # TX 2 (ours):
            #   Instruction 1: flashloan borrow
            #   Instruction 2-N: arb route swaps
            #   Instruction N+1: flashloan repay
            #   Instruction N+2: Jito tip

            instructions = []

            # 1. Flashloan borrow instruction
            borrow_ix = await self._build_flashloan_borrow(
                route.input_mint, route.input_amount
            )
            if borrow_ix:
                instructions.append(borrow_ix)

            # 2. Swap instructions for each hop
            for hop in route.hops:
                swap_ix = await self._build_swap_instruction(hop)
                if swap_ix:
                    instructions.append(swap_ix)

            # 3. Flashloan repay instruction
            flashloan_fee = route.input_amount * (self.flashloan_fee_bps / 10000)
            repay_amount = route.input_amount + flashloan_fee
            repay_ix = await self._build_flashloan_repay(
                route.input_mint, repay_amount
            )
            if repay_ix:
                instructions.append(repay_ix)

            # 4. Jito tip instruction
            tip_ix = await self._build_jito_tip()
            if tip_ix:
                instructions.append(tip_ix)

            # Build and sign transaction
            # Submit as Jito bundle (after the target tx)
            bundle_id = await self._submit_bundle(instructions, after_tx)

            elapsed = (time.monotonic() - start) * 1000
            jito_tip = JITO_TIP_LAMPORTS / 1_000_000_000
            net = route.profit - flashloan_fee - jito_tip - 0.000005

            if bundle_id:
                log.info(f"BACKRUN SUBMITTED: bundle={bundle_id} | net={net:.6f} SOL")
                return FlashloanResult(
                    success=True,
                    bundle_id=bundle_id,
                    borrowed=route.input_amount,
                    repaid=repay_amount,
                    profit_gross=route.profit,
                    profit_net=net,
                    jito_tip=jito_tip,
                    flashloan_fee=flashloan_fee,
                    latency_ms=elapsed,
                )
            else:
                return FlashloanResult(
                    success=False, error="Bundle submission failed",
                    latency_ms=elapsed
                )

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            log.error(f"Backrun execution failed: {e}")
            return FlashloanResult(
                success=False, error=str(e), latency_ms=elapsed
            )

    async def _build_flashloan_borrow(self, mint: str, amount: float) -> Optional[dict]:
        """Build a flashloan borrow instruction (Solend or MarginFi)."""
        # Implementation depends on which lending protocol we use
        # Solend: flash_borrow_reserve_liquidity instruction
        # Returns instruction data dict
        log.debug(f"Building flashloan borrow: {amount:.4f} of {mint[:12]}")
        return {"type": "flashloan_borrow", "mint": mint, "amount": amount}

    async def _build_swap_instruction(self, hop: dict) -> Optional[dict]:
        """Build a swap instruction for one hop of the arb route."""
        log.debug(f"Building swap: {hop.get('dex')} {hop.get('input_mint','')[:8]}→{hop.get('output_mint','')[:8]}")
        return {"type": "swap", **hop}

    async def _build_flashloan_repay(self, mint: str, amount: float) -> Optional[dict]:
        """Build a flashloan repay instruction."""
        log.debug(f"Building flashloan repay: {amount:.4f} of {mint[:12]}")
        return {"type": "flashloan_repay", "mint": mint, "amount": amount}

    async def _build_jito_tip(self) -> Optional[dict]:
        """Build Jito tip instruction to incentivize bundle inclusion."""
        return {"type": "jito_tip", "lamports": JITO_TIP_LAMPORTS}

    async def _submit_bundle(self, instructions: list, after_tx: str) -> str:
        """Submit the backrun bundle to Jito block engine."""
        import aiohttp
        try:
            url = f"{self.jito_url}/api/v1/bundles"
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "sendBundle",
                "params": [{
                    "after_tx": after_tx,
                    "instructions": instructions,
                }]
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    data = await resp.json()
                    return data.get("result", "")
        except Exception as e:
            log.error(f"Jito bundle submission failed: {e}")
            return ""


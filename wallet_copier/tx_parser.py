"""
PumpDesk v2 — Wallet Copier: Transaction Parser
Parses Solana transactions to detect PumpFun/PumpSwap trades.
Extracts: token mint, action (buy/sell), SOL amount, token amount.

This is the critical piece — if we can't parse the tx correctly,
we copy the wrong thing or miss trades entirely.
"""

import logging
import json
import base64
from typing import Optional
from dataclasses import dataclass

from shared.config import PUMPFUN_PROGRAM_ID, PUMPSWAP_PROGRAM_ID

log = logging.getLogger("pumpdesk.copier.parser")

# PumpFun instruction discriminators (first 8 bytes of Anchor IDL)
# These identify which instruction was called
PUMPFUN_BUY_DISCRIMINATOR = bytes([102, 6, 61, 18, 1, 218, 235, 234])
PUMPFUN_SELL_DISCRIMINATOR = bytes([51, 230, 133, 164, 1, 127, 131, 173])
PUMPFUN_CREATE_DISCRIMINATOR = bytes([24, 30, 200, 40, 5, 28, 7, 119])


@dataclass
class ParsedTrade:
    """A parsed trade from a Solana transaction."""
    wallet: str              # who made the trade
    mint: str                # token mint address
    action: str              # "buy" | "sell" | "create"
    sol_amount: float        # SOL involved
    token_amount: float      # tokens involved
    platform: str            # "pumpfun" | "pumpswap"
    bonding_curve: str = ""  # bonding curve account (PumpFun only)
    pool: str = ""           # pool account (PumpSwap only)
    signature: str = ""      # transaction signature
    slot: int = 0
    timestamp: int = 0


def parse_transaction(tx_data: dict, watched_addresses: set) -> Optional[ParsedTrade]:
    """Parse a Solana transaction and extract PumpFun/PumpSwap trade info.

    Args:
        tx_data: raw transaction data from WebSocket/Geyser
        watched_addresses: set of wallet addresses we're monitoring

    Returns:
        ParsedTrade if this is a relevant trade by a watched wallet, None otherwise.
    """
    try:
        tx = tx_data.get("transaction", {})
        meta = tx_data.get("meta", {})

        if not tx or not meta:
            return None

        # Check for errors — skip failed txs
        if meta.get("err") is not None:
            return None

        message = tx.get("message", {})
        account_keys = message.get("accountKeys", [])

        if not account_keys:
            return None

        # Check if any watched wallet is in this transaction
        signer = account_keys[0] if account_keys else ""
        if signer not in watched_addresses:
            return None

        # Check if PumpFun or PumpSwap program is involved
        instructions = message.get("instructions", [])
        inner_instructions = meta.get("innerInstructions", [])

        for ix in instructions:
            program_idx = ix.get("programIdIndex", -1)
            if program_idx < 0 or program_idx >= len(account_keys):
                continue

            program_id = account_keys[program_idx]

            if program_id == PUMPFUN_PROGRAM_ID:
                return _parse_pumpfun_ix(ix, account_keys, signer, meta, tx_data)

            if PUMPSWAP_PROGRAM_ID and program_id == PUMPSWAP_PROGRAM_ID:
                return _parse_pumpswap_ix(ix, account_keys, signer, meta, tx_data)

        return None

    except Exception as e:
        log.debug(f"Parse error (non-critical): {e}")
        return None


def _parse_pumpfun_ix(ix: dict, accounts: list, signer: str,
                       meta: dict, tx_data: dict) -> Optional[ParsedTrade]:
    """Parse a PumpFun program instruction."""
    try:
        data_b64 = ix.get("data", "")
        if not data_b64:
            return None

        data = base64.b64decode(data_b64)
        if len(data) < 8:
            return None

        discriminator = data[:8]
        ix_accounts = ix.get("accounts", [])

        # Determine action from discriminator
        if discriminator == PUMPFUN_BUY_DISCRIMINATOR:
            action = "buy"
        elif discriminator == PUMPFUN_SELL_DISCRIMINATOR:
            action = "sell"
        elif discriminator == PUMPFUN_CREATE_DISCRIMINATOR:
            action = "create"
        else:
            return None

        # Extract mint from account list
        # PumpFun buy/sell account layout:
        # [0] = global, [1] = fee_recipient, [2] = mint, [3] = bonding_curve,
        # [4] = associated_bonding_curve, [5] = associated_user, [6] = user, ...
        mint = ""
        bonding_curve = ""
        if len(ix_accounts) > 4:
            mint_idx = ix_accounts[2] if len(ix_accounts) > 2 else -1
            bc_idx = ix_accounts[3] if len(ix_accounts) > 3 else -1
            if 0 <= mint_idx < len(accounts):
                mint = accounts[mint_idx]
            if 0 <= bc_idx < len(accounts):
                bonding_curve = accounts[bc_idx]

        # Extract SOL amount from balance changes
        sol_amount = _get_sol_change(signer, accounts, meta)

        # Extract token amount from token balance changes
        token_amount = _get_token_change(signer, mint, meta)

        if not mint:
            return None

        return ParsedTrade(
            wallet=signer,
            mint=mint,
            action=action,
            sol_amount=abs(sol_amount),
            token_amount=abs(token_amount),
            platform="pumpfun",
            bonding_curve=bonding_curve,
            signature=tx_data.get("signature", ""),
            slot=tx_data.get("slot", 0),
        )

    except Exception as e:
        log.debug(f"PumpFun parse error: {e}")
        return None


def _parse_pumpswap_ix(ix: dict, accounts: list, signer: str,
                        meta: dict, tx_data: dict) -> Optional[ParsedTrade]:
    """Parse a PumpSwap AMM instruction."""
    # PumpSwap uses constant product AMM — swap instructions
    # The account layout differs from PumpFun
    # For now, detect buy/sell from SOL balance change direction
    try:
        sol_change = _get_sol_change(signer, accounts, meta)

        # If SOL decreased, it's a buy (SOL → tokens)
        # If SOL increased, it's a sell (tokens → SOL)
        action = "buy" if sol_change < 0 else "sell"

        # Extract mint from token balance changes
        token_balances = meta.get("postTokenBalances", [])
        mint = ""
        token_amount = 0.0
        for tb in token_balances:
            owner = tb.get("owner", "")
            if owner == signer:
                mint = tb.get("mint", "")
                ui_amount = tb.get("uiTokenAmount", {}).get("uiAmount", 0)
                token_amount = float(ui_amount or 0)
                break

        if not mint:
            return None

        return ParsedTrade(
            wallet=signer,
            mint=mint,
            action=action,
            sol_amount=abs(sol_change),
            token_amount=abs(token_amount),
            platform="pumpswap",
            signature=tx_data.get("signature", ""),
            slot=tx_data.get("slot", 0),
        )

    except Exception as e:
        log.debug(f"PumpSwap parse error: {e}")
        return None


def _get_sol_change(wallet: str, accounts: list, meta: dict) -> float:
    """Get SOL balance change for a wallet from transaction meta."""
    try:
        pre = meta.get("preBalances", [])
        post = meta.get("postBalances", [])
        idx = accounts.index(wallet) if wallet in accounts else -1
        if idx >= 0 and idx < len(pre) and idx < len(post):
            return (post[idx] - pre[idx]) / 1_000_000_000  # lamports to SOL
    except (ValueError, IndexError):
        pass
    return 0.0


def _get_token_change(wallet: str, mint: str, meta: dict) -> float:
    """Get token balance change for a wallet from transaction meta."""
    try:
        pre_balances = {
            (b.get("owner"), b.get("mint")): float(b.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
            for b in meta.get("preTokenBalances", [])
        }
        post_balances = {
            (b.get("owner"), b.get("mint")): float(b.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
            for b in meta.get("postTokenBalances", [])
        }
        pre = pre_balances.get((wallet, mint), 0)
        post = post_balances.get((wallet, mint), 0)
        return post - pre
    except Exception:
        return 0.0


"""
PumpDesk v2 — Solana Utilities
Keypair helpers, transaction decoding, balance checks.
"""

import logging
from shared.config import SOLANA_RPC_URL, WALLET_PRIVATE_KEY

log = logging.getLogger("pumpdesk.solana")


def get_keypair_from_secret(secret: str):
    try:
        from solders.keypair import Keypair
        import json
        if secret.startswith("["):
            return Keypair.from_bytes(bytes(json.loads(secret)))
        import base58
        return Keypair.from_bytes(base58.b58decode(secret))
    except Exception as e:
        log.error(f"Failed to parse keypair: {e}")
        return None


def get_wallet_keypair():
    if not WALLET_PRIVATE_KEY:
        log.warning("No WALLET_PRIVATE_KEY set")
        return None
    return get_keypair_from_secret(WALLET_PRIVATE_KEY)


async def get_sol_balance(address: str) -> float:
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
            async with session.post(SOLANA_RPC_URL, json=payload) as resp:
                data = await resp.json()
                return data.get("result", {}).get("value", 0) / 1_000_000_000
    except Exception as e:
        log.error(f"get_sol_balance failed: {e}")
        return 0.0


async def get_token_balance(wallet: str, mint: str) -> float:
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [wallet, {"mint": mint}, {"encoding": "jsonParsed"}]
            }
            async with session.post(SOLANA_RPC_URL, json=payload) as resp:
                data = await resp.json()
                accounts = data.get("result", {}).get("value", [])
                if not accounts:
                    return 0.0
                info = accounts[0]["account"]["data"]["parsed"]["info"]
                return float(info["tokenAmount"]["uiAmount"] or 0)
    except Exception as e:
        log.error(f"get_token_balance failed: {e}")
        return 0.0


def lamports_to_sol(lamports: int) -> float:
    return lamports / 1_000_000_000

def sol_to_lamports(sol: float) -> int:
    return int(sol * 1_000_000_000)


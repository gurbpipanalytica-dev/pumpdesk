"""
PumpDesk v2 — Execution Engine: Solana Client
Connection pool for RPC, WebSocket, and Geyser gRPC.
Every other execution module imports from here.
"""

import logging
import aiohttp
from typing import Optional

from shared.config import SOLANA_RPC_URL, SOLANA_WS_URL, GEYSER_GRPC_URL

log = logging.getLogger("pumpdesk.execution.solana")


class SolanaClient:
    """Manages Solana RPC connections for the execution engine."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._rpc_url = SOLANA_RPC_URL
        self._ws_url = SOLANA_WS_URL

    async def connect(self):
        self._session = aiohttp.ClientSession()
        log.info(f"Solana client connected: {self._rpc_url}")

    async def disconnect(self):
        if self._session:
            await self._session.close()

    async def rpc_call(self, method: str, params: list = None) -> dict:
        """Make a JSON-RPC call to Solana."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }
        async with self._session.post(self._rpc_url, json=payload) as resp:
            data = await resp.json()
            if "error" in data:
                log.error(f"RPC error [{method}]: {data['error']}")
            return data

    async def get_balance(self, address: str) -> float:
        """Get SOL balance in SOL (not lamports)."""
        data = await self.rpc_call("getBalance", [address])
        lamports = data.get("result", {}).get("value", 0)
        return lamports / 1_000_000_000

    async def get_latest_blockhash(self) -> str:
        """Get recent blockhash for transaction construction."""
        data = await self.rpc_call("getLatestBlockhash", [{"commitment": "finalized"}])
        return data.get("result", {}).get("value", {}).get("blockhash", "")

    async def send_transaction(self, tx_base64: str, skip_preflight: bool = True) -> str:
        """Submit a signed transaction. Returns signature or empty string."""
        opts = {"skipPreflight": skip_preflight, "encoding": "base64"}
        data = await self.rpc_call("sendTransaction", [tx_base64, opts])
        sig = data.get("result", "")
        if sig:
            log.info(f"TX sent: {sig[:16]}...")
        return sig

    async def confirm_transaction(self, signature: str, timeout: int = 30) -> bool:
        """Poll for transaction confirmation."""
        import asyncio
        for _ in range(timeout):
            data = await self.rpc_call("getSignatureStatuses", [[signature]])
            statuses = data.get("result", {}).get("value", [None])
            if statuses and statuses[0]:
                status = statuses[0]
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    if status.get("err") is None:
                        log.info(f"TX confirmed: {signature[:16]}...")
                        return True
                    else:
                        log.error(f"TX failed on-chain: {signature[:16]}... err={status['err']}")
                        return False
            await asyncio.sleep(1)
        log.warning(f"TX confirmation timeout: {signature[:16]}...")
        return False

    async def get_token_accounts(self, wallet: str, mint: str) -> list:
        """Get token accounts for a wallet + mint pair."""
        data = await self.rpc_call("getTokenAccountsByOwner", [
            wallet,
            {"mint": mint},
            {"encoding": "jsonParsed"}
        ])
        return data.get("result", {}).get("value", [])


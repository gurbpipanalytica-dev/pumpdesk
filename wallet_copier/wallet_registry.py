"""
PumpDesk v2 — Wallet Copier: Wallet Registry
Manages tracked wallets, their performance history, and copy configurations.
This is the intelligence behind WHICH wallets to follow — the most important
decision in copy trading.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from pathlib import Path

from shared.config import STATE_DIR

log = logging.getLogger("pumpdesk.copier.registry")

STATE_FILE = STATE_DIR / "copier_wallets.json"


@dataclass
class TrackedWallet:
    """A wallet we're monitoring for copy trading."""
    address: str
    name: str = ""
    copy_enabled: bool = True
    copy_size_sol: float = 0.5         # how much SOL per copied trade
    max_copy_sol: float = 2.0          # max per single copy
    min_copy_sol: float = 0.05         # ignore tiny trades
    copy_delay_seconds: float = 1.0    # wait before copying (avoid front-run detection)
    platforms: List[str] = field(default_factory=lambda: ["pumpfun", "pumpswap"])

    # Performance tracking
    total_trades_seen: int = 0
    total_trades_copied: int = 0
    profitable_copies: int = 0
    total_pnl_sol: float = 0.0
    win_rate: float = 0.0
    avg_hold_seconds: float = 0.0

    # Activity tracking
    last_trade_at: str = ""
    last_copied_at: str = ""
    consecutive_losses: int = 0

    # Auto-disable thresholds
    max_consecutive_losses: int = 5    # disable after N losses in a row
    min_win_rate: float = 0.35         # disable if win rate drops below this

    # Metadata
    notes: str = ""
    added_at: str = ""
    source: str = ""                   # how we found this wallet: "leaderboard", "manual", "discovered"

    def should_copy(self) -> bool:
        """Check if this wallet is eligible for copy trading right now."""
        if not self.copy_enabled:
            return False
        if self.consecutive_losses >= self.max_consecutive_losses:
            log.warning(f"[{self.name or self.address[:12]}] Auto-disabled: {self.consecutive_losses} consecutive losses")
            return False
        if self.total_trades_copied > 20 and self.win_rate < self.min_win_rate:
            log.warning(f"[{self.name or self.address[:12]}] Auto-disabled: win rate {self.win_rate:.1%} below {self.min_win_rate:.1%}")
            return False
        return True

    def record_copy_result(self, pnl_sol: float):
        """Update stats after a copied trade closes."""
        self.total_trades_copied += 1
        self.total_pnl_sol += pnl_sol
        if pnl_sol > 0:
            self.profitable_copies += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        if self.total_trades_copied > 0:
            self.win_rate = self.profitable_copies / self.total_trades_copied


class WalletRegistry:
    """Manages the collection of tracked wallets with persistence."""

    def __init__(self):
        self.wallets: dict[str, TrackedWallet] = {}
        self._load()

    def add(self, wallet: TrackedWallet) -> bool:
        if wallet.address in self.wallets:
            log.info(f"Wallet already tracked: {wallet.address[:12]}")
            return False
        self.wallets[wallet.address] = wallet
        self._save()
        log.info(f"Wallet added: {wallet.name or wallet.address[:12]} | copy={wallet.copy_enabled}")
        return True

    def remove(self, address: str) -> bool:
        if address in self.wallets:
            name = self.wallets[address].name or address[:12]
            del self.wallets[address]
            self._save()
            log.info(f"Wallet removed: {name}")
            return True
        return False

    def get(self, address: str) -> Optional[TrackedWallet]:
        return self.wallets.get(address)

    def get_copyable(self) -> List[TrackedWallet]:
        """Return wallets that are currently eligible for copying."""
        return [w for w in self.wallets.values() if w.should_copy()]

    def get_all_addresses(self) -> List[str]:
        return list(self.wallets.keys())

    def update_trade_seen(self, address: str):
        w = self.wallets.get(address)
        if w:
            w.total_trades_seen += 1

    def _save(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            data = {addr: asdict(w) for addr, w in self.wallets.items()}
            STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"Failed to save wallet registry: {e}")

    def _load(self):
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text())
                for addr, d in data.items():
                    self.wallets[addr] = TrackedWallet(**d)
                log.info(f"Loaded {len(self.wallets)} tracked wallets")
        except Exception as e:
            log.warning(f"Failed to load wallet registry: {e}")


# ── DEFAULT WALLETS (starter set — replace with your own research) ──────────
DEFAULT_WALLETS = [
    TrackedWallet(
        address="",  # Fill with real Solana address
        name="alpha_whale_1",
        copy_size_sol=0.5,
        source="manual",
        notes="Consistent PumpFun early buyer. Research before enabling.",
        copy_enabled=False,  # disabled by default — enable after verification
    ),
]


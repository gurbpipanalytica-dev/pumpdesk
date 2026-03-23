"""
PumpDesk v2 — Token Launcher: Wallet Manager
Manages the pool of wallets used for bundled token launches.

On PumpFun, a bundled launch works like this:
  TX 1: Create token (dev wallet — this is the "creator")
  TX 2: Dev wallet buys first (sets initial price position)
  TX 3-N: Bundle wallets buy in the same Jito bundle

All TXs land in one block — atomic. From the outside it looks like
organic demand from multiple wallets, but we control them all.

This module handles:
  - Generating and storing keypairs for bundle wallets
  - Distributing SOL from treasury to bundle wallets pre-launch
  - Collecting profits back to treasury post-launch
  - Rotating wallets to avoid on-chain fingerprinting
"""

import logging
import json
import time
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from shared.config import STATE_DIR

log = logging.getLogger("pumpdesk.launcher.wallets")

WALLETS_FILE = STATE_DIR / "launcher_wallets.json"


@dataclass
class BundleWallet:
    """A wallet used in bundle launches."""
    address: str
    keypair_path: str         # path to keypair JSON file
    label: str = ""
    total_launches: int = 0
    total_sol_spent: float = 0.0
    total_sol_recovered: float = 0.0
    last_used: str = ""
    active: bool = True


class WalletManager:
    """Manages bundle wallets for token launches."""

    def __init__(self, wallet_dir: Optional[Path] = None):
        self.wallet_dir = wallet_dir or (STATE_DIR / "bundle_wallets")
        self.wallets: List[BundleWallet] = []
        self._load()

    def get_available(self, count: int) -> List[BundleWallet]:
        """Get N available wallets for a launch. Creates if needed."""
        available = [w for w in self.wallets if w.active]
        while len(available) < count:
            new_wallet = self._create_wallet(f"bundle_{len(self.wallets)}")
            if new_wallet:
                self.wallets.append(new_wallet)
                available.append(new_wallet)
            else:
                break
        return available[:count]

    def record_launch(self, addresses: List[str], sol_per_wallet: float):
        """Record that wallets were used in a launch."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for w in self.wallets:
            if w.address in addresses:
                w.total_launches += 1
                w.total_sol_spent += sol_per_wallet
                w.last_used = now
        self._save()

    def get_dev_wallet(self) -> Optional[BundleWallet]:
        """Get the primary dev wallet (creator wallet for launches)."""
        for w in self.wallets:
            if w.label == "dev_primary" and w.active:
                return w
        # Create one if doesn't exist
        dev = self._create_wallet("dev_primary")
        if dev:
            self.wallets.append(dev)
            self._save()
        return dev

    def _create_wallet(self, label: str) -> Optional[BundleWallet]:
        """Generate a new Solana keypair for bundling."""
        try:
            from solders.keypair import Keypair
            import base58

            kp = Keypair()
            address = str(kp.pubkey())

            self.wallet_dir.mkdir(parents=True, exist_ok=True)
            kp_path = self.wallet_dir / f"{label}.json"
            kp_path.write_text(json.dumps(list(bytes(kp))))

            log.info(f"Created bundle wallet: {label} ({address[:12]}...)")
            return BundleWallet(
                address=address,
                keypair_path=str(kp_path),
                label=label,
            )
        except ImportError:
            # solders not installed — create placeholder
            placeholder_addr = f"PLACEHOLDER_{label}_{int(time.time())}"
            log.warning(f"solders not available — created placeholder wallet: {label}")
            return BundleWallet(
                address=placeholder_addr,
                keypair_path="",
                label=label,
            )
        except Exception as e:
            log.error(f"Failed to create wallet {label}: {e}")
            return None

    def _save(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            data = [asdict(w) for w in self.wallets]
            WALLETS_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"Failed to save wallets: {e}")

    def _load(self):
        try:
            if WALLETS_FILE.exists():
                data = json.loads(WALLETS_FILE.read_text())
                self.wallets = [BundleWallet(**d) for d in data]
                log.info(f"Loaded {len(self.wallets)} bundle wallets")
        except Exception as e:
            log.warning(f"Failed to load wallets: {e}")


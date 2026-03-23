"""
PumpDesk v2 — Core Data Models
Every bot and engine uses these dataclasses for type-safe communication.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List
from datetime import datetime, timezone
import json


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
#  TOKENS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Token:
    """A PumpFun token — either discovered or created by us."""
    mint: str
    name: str = ""
    symbol: str = ""
    creator: str = ""
    bonding_curve: str = ""
    associated_bonding_curve: str = ""
    curve_pct: float = 0.0
    mcap_usd: float = 0.0
    price_sol: float = 0.0
    price_usd: float = 0.0
    volume_24h: float = 0.0
    unique_holders: int = 0
    is_graduated: bool = False
    pumpswap_pool: str = ""
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Token":
        return cls(**json.loads(raw))


# ══════════════════════════════════════════════════════════════════════════════
#  SIGNALS — bots publish these to Redis
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    """A trading signal published by any bot to the Redis bus."""
    signal_id: str
    bot: str
    signal_type: str  # new_token | curve_progress | whale_trade | arb_opportunity | momentum_spike | graduation
    token: Token
    action: str       # buy | sell | lp_add | lp_remove
    confidence: float = 0.0
    size_sol: float = 0.0
    reason: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Signal":
        d = json.loads(raw)
        d["token"] = Token(**d["token"])
        return cls(**d)


# ══════════════════════════════════════════════════════════════════════════════
#  DECISIONS — orchestrator responds to signals
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Decision:
    """Orchestrator's response to a Signal."""
    decision_id: str
    signal_id: str
    approved: bool
    reason: str = ""
    adjusted_size_sol: float = 0.0
    exit_plan: dict = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Decision":
        return cls(**json.loads(raw))


# ══════════════════════════════════════════════════════════════════════════════
#  POSITIONS — managed by the progressive exit engine
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    """An open trading position."""
    position_id: str
    bot: str
    mint: str
    side: str = "long"
    entry_price_sol: float = 0.0
    entry_price_usd: float = 0.0
    size_tokens: float = 0.0
    size_sol: float = 0.0
    current_price_sol: float = 0.0
    unrealized_pnl_sol: float = 0.0
    realized_pnl_sol: float = 0.0
    exit_stages_completed: List[dict] = field(default_factory=list)
    exit_stages_remaining: List[dict] = field(default_factory=list)
    status: str = "open"  # open | partial_exit | closed | emergency_exit
    opened_at: str = field(default_factory=utcnow)
    closed_at: Optional[str] = None
    tx_signatures: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Position":
        return cls(**json.loads(raw))


# ══════════════════════════════════════════════════════════════════════════════
#  LAUNCH CONFIG — for the Token Launcher (Bot 5)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LaunchConfig:
    """Configuration for launching a new token."""
    name: str
    symbol: str
    description: str = ""
    image_url: str = ""
    twitter: str = ""
    telegram: str = ""
    website: str = ""
    dev_buy_sol: float = 0.1
    bundle_wallets: int = 5
    bundle_sol_per_wallet: float = 0.05
    enable_volume_bot: bool = False
    volume_bot_intensity: float = 0.5
    enable_anti_sniper_mode: bool = False
    created_at: str = field(default_factory=utcnow)

    def total_sol_cost(self) -> float:
        return self.dev_buy_sol + (self.bundle_wallets * self.bundle_sol_per_wallet)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "LaunchConfig":
        return cls(**json.loads(raw))


# ══════════════════════════════════════════════════════════════════════════════
#  EXIT PLAN — attached to every position
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExitPlan:
    """Progressive exit configuration."""
    stages: List[dict] = field(default_factory=list)
    time_exit_seconds: int = 300
    emergency_drop_pct: float = 0.30
    trailing_stop_pct: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "ExitPlan":
        return cls(**json.loads(raw))


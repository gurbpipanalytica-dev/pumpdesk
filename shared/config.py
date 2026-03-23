"""
PumpDesk v2 — Global Configuration
All env vars, constants, and feature flags.
Every bot and engine imports from here.
"""

import os
from pathlib import Path

# ── PATHS ───────────────────────────────────────────────────────────────────
STATE_DIR = Path(os.environ.get("STATE_DIR", "/app/state"))
LOGS_DIR = Path(os.environ.get("LOGS_DIR", "/app/logs"))

# ── SOLANA ──────────────────────────────────────────────────────────────────
SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
SOLANA_WS_URL = os.environ.get("SOLANA_WS_URL", "wss://api.mainnet-beta.solana.com")
GEYSER_GRPC_URL = os.environ.get("GEYSER_GRPC_URL", "")
GEYSER_TOKEN = os.environ.get("GEYSER_TOKEN", "")

# ── WALLET ──────────────────────────────────────────────────────────────────
WALLET_PRIVATE_KEY = os.environ.get("WALLET_PRIVATE_KEY", "")

# ── JITO ────────────────────────────────────────────────────────────────────
JITO_BLOCK_ENGINE_URL = os.environ.get("JITO_BLOCK_ENGINE_URL", "https://mainnet.block-engine.jito.wtf")
JITO_TIP_LAMPORTS = int(os.environ.get("JITO_TIP_LAMPORTS", "10000"))

# ── PUMPFUN ─────────────────────────────────────────────────────────────────
PUMPFUN_PROGRAM_ID = os.environ.get("PUMPFUN_PROGRAM_ID", "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
PUMPSWAP_PROGRAM_ID = os.environ.get("PUMPSWAP_PROGRAM_ID", "")
PUMPFUN_CREATE_FEE_SOL = 0.0
PUMPFUN_GRADUATION_FEE_SOL = 0.015
PUMPFUN_GRADUATION_MCAP_USD = 69_000
BONDING_CURVE_SUPPLY = 800_000_000
TOTAL_TOKEN_SUPPLY = 1_000_000_000
PUMPSWAP_TRADE_FEE = 0.0025
PUMPSWAP_LP_FEE_SHARE = 0.0020
PUMPSWAP_PROTOCOL_FEE = 0.0005
CREATOR_FEE_MIN = 0.003
CREATOR_FEE_MAX = 0.0095

# ── REDIS ───────────────────────────────────────────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# ── SUPABASE ────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ── ANTHROPIC ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── RISK CONTROLS ───────────────────────────────────────────────────────────
MAX_POSITION_SOL = float(os.environ.get("MAX_POSITION_SOL", "2.0"))
MAX_CONCURRENT_POSITIONS = int(os.environ.get("MAX_CONCURRENT_POSITIONS", "5"))
MAX_DAILY_LOSS_SOL = float(os.environ.get("MAX_DAILY_LOSS_SOL", "5.0"))
PAPER_MODE = os.environ.get("PAPER_MODE", "true").lower() == "true"

# ── BOT FEATURE FLAGS ──────────────────────────────────────────────────────
ENABLE_SNIPER = os.environ.get("ENABLE_SNIPER", "true").lower() == "true"
ENABLE_COPIER = os.environ.get("ENABLE_COPIER", "true").lower() == "true"
ENABLE_ARB = os.environ.get("ENABLE_ARB", "true").lower() == "true"
ENABLE_MOMENTUM = os.environ.get("ENABLE_MOMENTUM", "true").lower() == "true"
ENABLE_LAUNCHER = os.environ.get("ENABLE_LAUNCHER", "false").lower() == "true"
ENABLE_VOLUME_BOT = os.environ.get("ENABLE_VOLUME_BOT", "false").lower() == "true"
ENABLE_ANTI_SNIPER = os.environ.get("ENABLE_ANTI_SNIPER", "false").lower() == "true"

# ── PROGRESSIVE EXIT DEFAULTS ──────────────────────────────────────────────
DEFAULT_EXIT_STAGES = [
    {"trigger_multiple": 2.0, "sell_pct": 0.50},
    {"trigger_multiple": 5.0, "sell_pct": 0.25},
    {"trigger_multiple": 10.0, "sell_pct": 0.15},
]
DEFAULT_TIME_EXIT_SECONDS = 300
EMERGENCY_EXIT_DROP_PCT = 0.30


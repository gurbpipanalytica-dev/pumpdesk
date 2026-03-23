"""
PumpDesk v2 — Supabase Client
Persists trades, positions, snapshots, launched tokens.
"""

import logging
from typing import Optional, List
from shared.config import SUPABASE_URL, SUPABASE_KEY

log = logging.getLogger("pumpdesk.db")
_client = None
_available = False


def get_client():
    global _client, _available
    if _client is not None:
        return _client
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.warning("Supabase not configured — persistence disabled")
        _available = False
        return None
    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _available = True
        log.info("Supabase connected")
        return _client
    except Exception as e:
        log.warning(f"Supabase unavailable: {e}")
        _available = False
        return None


def is_available() -> bool:
    if _client is None:
        get_client()
    return _available


def log_trade(trade: dict):
    c = get_client()
    if not c: return
    try: c.table("trades").insert(trade).execute()
    except Exception as e: log.error(f"log_trade failed: {e}")


def get_recent_trades(bot: Optional[str] = None, limit: int = 50) -> List[dict]:
    c = get_client()
    if not c: return []
    try:
        q = c.table("trades").select("*").order("created_at", desc=True).limit(limit)
        if bot: q = q.eq("bot", bot)
        return q.execute().data or []
    except Exception as e:
        log.error(f"get_recent_trades failed: {e}")
        return []


def upsert_position(position: dict):
    c = get_client()
    if not c: return
    try: c.table("positions").upsert(position, on_conflict="position_id").execute()
    except Exception as e: log.error(f"upsert_position failed: {e}")


def get_open_positions(bot: Optional[str] = None) -> List[dict]:
    c = get_client()
    if not c: return []
    try:
        q = c.table("positions").select("*").in_("status", ["open", "partial_exit"])
        if bot: q = q.eq("bot", bot)
        return q.execute().data or []
    except Exception as e:
        log.error(f"get_open_positions failed: {e}")
        return []


def log_launched_token(token: dict):
    c = get_client()
    if not c: return
    try: c.table("launched_tokens").insert(token).execute()
    except Exception as e: log.error(f"log_launched_token failed: {e}")


def get_launched_tokens() -> List[dict]:
    c = get_client()
    if not c: return []
    try: return c.table("launched_tokens").select("*").order("created_at", desc=True).execute().data or []
    except Exception as e:
        log.error(f"get_launched_tokens failed: {e}")
        return []


def save_snapshot(snapshot: dict):
    c = get_client()
    if not c: return
    try: c.table("snapshots").insert(snapshot).execute()
    except Exception as e: log.error(f"save_snapshot failed: {e}")


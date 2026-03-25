# PumpDesk v2 — Supabase Setup

## Quick Setup (5 minutes)

1. Go to [supabase.com](https://supabase.com) → Create new project
2. Copy your **Project URL** and **service_role key** (Settings → API)
3. Paste into `/tmp/pumpdesk_push/.env`:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...  (service_role key, NOT anon key)
   ```
4. Go to **SQL Editor** → New Query → paste `migration.sql` → Run
5. (Optional) Paste `seed.sql` → Run — populates demo data

## Tables Created

| Table | Purpose | Rows from Seed |
|-------|---------|----------------|
| `trades` | Every buy/sell executed | 24 |
| `positions` | Open/closed positions | 2 |
| `launched_tokens` | Tokens we created | 1 |
| `snapshots` | AI assessments, system state | 1 |

## Views Created

| View | Purpose |
|------|---------|
| `bot_pnl_summary` | Per-bot P&L, win rate, trade count |
| `daily_pnl` | Daily aggregated P&L |

## Important Notes

- Use **service_role** key (not anon) — the backend needs full table access
- RLS is enabled but service_role bypasses it
- The `positions` table uses `upsert` on `position_id` for real-time updates
- All money values are in SOL (numeric with 8 decimal precision)


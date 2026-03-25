-- ═══════════════════════════════════════════════════════════════════════════
--  PUMPDESK v2 — SUPABASE MIGRATION
--  Run this in your Supabase SQL Editor (Dashboard → SQL Editor → New Query)
--  Creates: trades, positions, launched_tokens, snapshots
-- ═══════════════════════════════════════════════════════════════════════════

-- ── TRADES ─────────────────────────────────────────────────────────────────
-- Every executed trade (buy/sell) logged by the execution engine
CREATE TABLE IF NOT EXISTS trades (
  id            bigint generated always as identity primary key,
  trade_id      text unique,
  bot           text not null,                    -- graduation_sniper, wallet_copier, etc
  mint          text not null,                    -- token mint address
  action        text not null default 'buy',      -- buy | sell
  side          text default 'long',
  size_sol      numeric(18,8) default 0,
  size_tokens   numeric(24,4) default 0,
  price_sol     numeric(18,12) default 0,
  price_usd     numeric(18,6) default 0,
  realized_pnl_sol numeric(18,8) default 0,
  fee_sol       numeric(18,8) default 0,
  signal_id     text,
  decision_id   text,
  reason        text default '',
  signal_type   text default '',
  tx_signature  text default '',
  position_id   text,
  paper_mode    boolean default true,
  metadata      jsonb default '{}',
  created_at    timestamptz default now()
);

-- Indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_trades_bot ON trades(bot);
CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at desc);
CREATE INDEX IF NOT EXISTS idx_trades_mint ON trades(mint);
CREATE INDEX IF NOT EXISTS idx_trades_position ON trades(position_id);

-- ── POSITIONS ──────────────────────────────────────────────────────────────
-- Active/closed positions managed by the progressive exit engine
CREATE TABLE IF NOT EXISTS positions (
  id                      bigint generated always as identity primary key,
  position_id             text unique not null,
  bot                     text not null,
  mint                    text not null,
  side                    text default 'long',
  entry_price_sol         numeric(18,12) default 0,
  entry_price_usd         numeric(18,6) default 0,
  size_tokens             numeric(24,4) default 0,
  size_sol                numeric(18,8) default 0,
  current_price_sol       numeric(18,12) default 0,
  unrealized_pnl_sol      numeric(18,8) default 0,
  realized_pnl_sol        numeric(18,8) default 0,
  exit_stages_completed   jsonb default '[]',
  exit_stages_remaining   jsonb default '[]',
  status                  text default 'open',     -- open | partial_exit | closed | emergency_exit
  opened_at               timestamptz default now(),
  closed_at               timestamptz,
  tx_signatures           jsonb default '[]',
  paper_mode              boolean default true,
  metadata                jsonb default '{}',
  created_at              timestamptz default now(),
  updated_at              timestamptz default now()
);

CREATE INDEX IF NOT EXISTS idx_positions_bot ON positions(bot);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_mint ON positions(mint);

-- ── LAUNCHED TOKENS ────────────────────────────────────────────────────────
-- Tokens created by our Token Launcher bot
CREATE TABLE IF NOT EXISTS launched_tokens (
  id                  bigint generated always as identity primary key,
  mint                text unique,
  name                text default '',
  symbol              text default '',
  description         text default '',
  image_url           text default '',
  twitter             text default '',
  telegram            text default '',
  website             text default '',
  creator             text default '',               -- our dev wallet
  bonding_curve       text default '',
  dev_buy_sol         numeric(18,8) default 0,
  bundle_wallets      int default 0,
  bundle_sol_per_wallet numeric(18,8) default 0,
  total_cost_sol      numeric(18,8) default 0,
  status              text default 'preparing',      -- preparing | launched | graduating | graduated | failed | dead
  curve_pct           numeric(8,4) default 0,
  mcap_usd            numeric(18,2) default 0,
  pumpswap_pool       text default '',
  creator_fee_earned_sol numeric(18,8) default 0,
  volume_bot_enabled  boolean default false,
  tx_signature        text default '',
  paper_mode          boolean default true,
  metadata            jsonb default '{}',
  created_at          timestamptz default now(),
  graduated_at        timestamptz
);

CREATE INDEX IF NOT EXISTS idx_launched_status ON launched_tokens(status);

-- ── SNAPSHOTS ──────────────────────────────────────────────────────────────
-- Periodic system snapshots (AI assessments, portfolio state)
CREATE TABLE IF NOT EXISTS snapshots (
  id          bigint generated always as identity primary key,
  type        text not null,                       -- ai_assessment | portfolio_state | daily_summary
  data        jsonb default '{}',
  created_at  timestamptz default now()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_type ON snapshots(type);
CREATE INDEX IF NOT EXISTS idx_snapshots_created ON snapshots(created_at desc);

-- ── ROW LEVEL SECURITY ─────────────────────────────────────────────────────
-- Enable RLS but allow service role full access
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE launched_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;

-- Service role policies (the backend uses service_role key)
CREATE POLICY "Service role full access on trades" ON trades FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access on positions" ON positions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access on launched_tokens" ON launched_tokens FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access on snapshots" ON snapshots FOR ALL USING (true) WITH CHECK (true);

-- ── FUNCTIONS ──────────────────────────────────────────────────────────────
-- Auto-update updated_at on positions
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ language plpgsql;

CREATE TRIGGER positions_updated_at
  BEFORE UPDATE ON positions
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── VIEWS ──────────────────────────────────────────────────────────────────
-- Handy view: per-bot P&L summary
CREATE OR REPLACE VIEW bot_pnl_summary AS
SELECT
  bot,
  count(*) as trade_count,
  count(*) filter (where realized_pnl_sol > 0) as wins,
  count(*) filter (where realized_pnl_sol < 0) as losses,
  round(sum(realized_pnl_sol)::numeric, 4) as total_pnl_sol,
  round(avg(realized_pnl_sol)::numeric, 6) as avg_pnl_sol,
  round((count(*) filter (where realized_pnl_sol > 0))::numeric / nullif(count(*), 0), 3) as win_rate,
  max(created_at) as last_trade_at
FROM trades
WHERE action = 'sell'
GROUP BY bot
ORDER BY total_pnl_sol desc;

-- Handy view: daily P&L
CREATE OR REPLACE VIEW daily_pnl AS
SELECT
  date_trunc('day', created_at)::date as day,
  count(*) as trades,
  round(sum(realized_pnl_sol)::numeric, 4) as pnl_sol,
  count(distinct bot) as active_bots
FROM trades
WHERE action = 'sell'
GROUP BY 1
ORDER BY 1 desc;


-- ═══════════════════════════════════════════════════════════════════════════
--  PUMPDESK v2 — SEED DATA (Paper Mode Demo)
--  Optional: run after migration.sql to populate dashboard with sample data
-- ═══════════════════════════════════════════════════════════════════════════

-- Sample trades showing how each bot operates
INSERT INTO trades (trade_id, bot, mint, action, size_sol, price_sol, realized_pnl_sol, reason, signal_type, paper_mode, created_at) VALUES
  ('t001', 'graduation_sniper', '7xKpN3mR9vQ2a4bJ8cLd5eHf6gYi', 'buy',  0.15, 0.000000420, 0,     'Curve at 94.2%, graduation imminent', 'curve_progress', true, now() - interval '6 hours'),
  ('t002', 'graduation_sniper', '7xKpN3mR9vQ2a4bJ8cLd5eHf6gYi', 'sell', 0.15, 0.000000680, 0.093, 'Graduated → PumpSwap, exit stage 1 (50%)', 'graduation', true, now() - interval '5 hours 45 minutes'),
  ('t003', 'graduation_sniper', '3nBzwQ9rT5sU8vX1yZ2aC4bD6eF7', 'buy',  0.20, 0.000000310, 0,     'Curve at 91.8%', 'curve_progress', true, now() - interval '4 hours'),
  ('t004', 'graduation_sniper', '3nBzwQ9rT5sU8vX1yZ2aC4bD6eF7', 'sell', 0.20, 0.000000155, -0.10, 'Emergency exit: -50% drawdown', 'emergency', true, now() - interval '3 hours 30 minutes'),
  ('t005', 'graduation_sniper', '9vFabL4pK8mN2qR5sT7uW3xY6zA1', 'buy',  0.12, 0.000000520, 0,     'Curve at 97.1%, high confidence', 'curve_progress', true, now() - interval '2 hours'),
  ('t006', 'graduation_sniper', '9vFabL4pK8mN2qR5sT7uW3xY6zA1', 'sell', 0.12, 0.000000890, 0.085, 'Graduated, exit stage 1', 'graduation', true, now() - interval '1 hour 45 minutes'),

  ('t007', 'wallet_copier', '5qJdxM7rN4pK2sL8vB3cW6yT9zA1', 'buy',  0.30, 0.000001200, 0,     'Copied Alpha Whale #1 buy', 'whale_trade', true, now() - interval '5 hours'),
  ('t008', 'wallet_copier', '5qJdxM7rN4pK2sL8vB3cW6yT9zA1', 'sell', 0.30, 0.000001500, 0.075, 'Whale exited, mirrored sell', 'whale_trade', true, now() - interval '4 hours 20 minutes'),
  ('t009', 'wallet_copier', '8kPnyT2qM6rL4sN9vB1cW3xY5zA7', 'buy',  0.25, 0.000000800, 0,     'Copied Sniper Bot wallet', 'whale_trade', true, now() - interval '3 hours'),
  ('t010', 'wallet_copier', '8kPnyT2qM6rL4sN9vB1cW3xY5zA7', 'sell', 0.25, 0.000001100, 0.094, 'Whale profit-taking, mirrored', 'whale_trade', true, now() - interval '2 hours 30 minutes'),

  ('t011', 'multi_dex_arb', '2mRzwK9sN6pL4rT8vB3cX5yW7zA1', 'buy',  0.50, 0.000002100, 0,     'Raydium price < PumpSwap by 3.2%', 'arb_opportunity', true, now() - interval '4 hours'),
  ('t012', 'multi_dex_arb', '2mRzwK9sN6pL4rT8vB3cX5yW7zA1', 'sell', 0.50, 0.000002166, 0.016, 'Sold on PumpSwap, 3.2% arb captured', 'arb_opportunity', true, now() - interval '4 hours'),
  ('t013', 'multi_dex_arb', '4tHncN6wP8mK2sL5rT9vB1cX3yW7', 'buy',  0.80, 0.000003400, 0,     'Jupiter vs Orca spread 2.8%', 'arb_opportunity', true, now() - interval '2 hours'),
  ('t014', 'multi_dex_arb', '4tHncN6wP8mK2sL5rT9vB1cX3yW7', 'sell', 0.80, 0.000003495, 0.022, 'Arb closed, 2.8% net', 'arb_opportunity', true, now() - interval '2 hours'),

  ('t015', 'jito_backrunner', 'BkR7nM3pL9sN4rT6vX2cW8yA5zA1', 'buy',  1.20, 0.000005200, 0,     'Backrun: large swap on Raydium detected', 'arb_opportunity', true, now() - interval '3 hours'),
  ('t016', 'jito_backrunner', 'BkR7nM3pL9sN4rT6vX2cW8yA5zA1', 'sell', 1.20, 0.000005330, 0.030, 'Backrun arb captured via Jito bundle', 'arb_opportunity', true, now() - interval '3 hours'),
  ('t017', 'jito_backrunner', 'Fq2K8mN5pL3sR7vT9xB1cW4yA6zA', 'buy',  0.90, 0.000004100, 0,     'Large swap backrun opportunity', 'arb_opportunity', true, now() - interval '1 hour'),
  ('t018', 'jito_backrunner', 'Fq2K8mN5pL3sR7vT9xB1cW4yA6zA', 'sell', 0.90, 0.000004220, 0.026, 'Backrun profit locked', 'arb_opportunity', true, now() - interval '1 hour'),

  ('t019', 'momentum_scanner', 'Mx5N8pL2sR4vT7xB9cW1yA3zA6kQ', 'buy',  0.18, 0.000000090, 0,     'Volume spike 420% + price +35% in 2min', 'momentum_spike', true, now() - interval '90 minutes'),
  ('t020', 'momentum_scanner', 'Mx5N8pL2sR4vT7xB9cW1yA3zA6kQ', 'sell', 0.18, 0.000000120, 0.060, 'Momentum exit at 2x target', 'momentum_spike', true, now() - interval '80 minutes'),
  ('t021', 'momentum_scanner', 'Px3N6pL8sR2vT4xB7cW9yA1zA5kQ', 'buy',  0.15, 0.000000150, 0,     'Volume + social signal convergence', 'momentum_spike', true, now() - interval '45 minutes'),
  ('t022', 'momentum_scanner', 'Px3N6pL8sR2vT4xB7cW9yA1zA5kQ', 'sell', 0.15, 0.000000105, -0.043, 'Momentum faded, stop loss hit', 'momentum_spike', true, now() - interval '35 minutes'),

  ('t023', 'liquidation_bot', 'So1endEp8mN5pL3sR7vT9xB1cW4yA', 'buy',  2.00, 0.000000001, 0,     'Flashloan liquidation: MarginFi HF=0.98', 'liquidation', true, now() - interval '2 hours'),
  ('t024', 'liquidation_bot', 'So1endEp8mN5pL3sR7vT9xB1cW4yA', 'sell', 2.00, 0.000000001, 0.180, 'Liquidation bonus captured (9%)', 'liquidation', true, now() - interval '2 hours');

-- Sample open position
INSERT INTO positions (position_id, bot, mint, side, entry_price_sol, size_sol, size_tokens, current_price_sol, unrealized_pnl_sol, status, paper_mode, opened_at) VALUES
  ('pos001', 'graduation_sniper', '9vFabL4pK8mN2qR5sT7uW3xY6zA1', 'long', 0.000000520, 0.12, 230769, 0.000000650, 0.030, 'open', true, now() - interval '2 hours'),
  ('pos002', 'wallet_copier', 'Dx4N7pL1sR3vT5xB8cW2yA9zA6kQ', 'long', 0.000001800, 0.25, 138888, 0.000001950, 0.021, 'open', true, now() - interval '40 minutes');

-- Sample launched token
INSERT INTO launched_tokens (mint, name, symbol, description, dev_buy_sol, bundle_wallets, bundle_sol_per_wallet, total_cost_sol, status, curve_pct, volume_bot_enabled, paper_mode, created_at) VALUES
  ('PD3sK7mN5pL2rT8vX4cW1yA9zA6B', 'PumpDesk Alpha', 'PDESK', 'AI-powered Solana alpha desk', 0.1, 5, 0.05, 0.35, 'launched', 42.3, true, true, now() - interval '12 hours');

-- Sample AI assessment snapshot
INSERT INTO snapshots (type, data, created_at) VALUES
  ('ai_assessment', '{"market_regime": "bullish_volatile", "recommendation": "Graduation sniper performing well — 2/3 trades profitable. Backrunner generating consistent small gains. Recommend increasing momentum scanner position sizes to 0.25 SOL given recent 60% win rate. Watch wallet copier — Alpha Whale #1 showing signs of rotating into new tokens.", "risk_level": "moderate", "suggested_actions": ["increase_momentum_size", "monitor_whale_rotation", "keep_arb_active"], "confidence": 0.78}', now() - interval '5 minutes');


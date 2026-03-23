# PumpDesk v2 — Project Context for Chat Continuity
# Last updated: 2026-03-23
# Use this file to onboard a new chat session

## WHAT THIS IS
PumpDesk is a full-scale Solana alpha desk — not just PumpFun, but MEV + DeFi yield.
Evolved from the Polydesk project (Polymarket trading desk on the same VPS).
Repo: github.com/gurbpipanalytica-dev/pumpdesk (PRIVATE)
VPS: api.gurbcapital.com (root via SSH — has GitHub PAT for pushing)
Staged code: /tmp/pumpdesk_push (git repo, pushes to GitHub from here)

## 4 REVENUE STREAMS
1. PumpFun Trading (reactive) — sniper, copier, arb, momentum
2. PumpFun Creating (generative) — token launcher, volume bot, anti-sniper
3. Solana MEV — Jito backrun arb, liquidation bot
4. DeFi Yield — JLP delta-neutral, lending rate arb

## ARCHITECTURE
- 20 Docker services communicating via Redis pub/sub
- Orchestrator: two-tier decision engine (fast path <100ms rules + slow path Claude AI)
- Every bot publishes signals → orchestrator approves/rejects → executor handles Solana tx
- Progressive exit engine manages all positions (staged sells, emergency exits)
- 5-tab React dashboard: Trading Desk, Token Launcher, MEV+DeFi, Intelligence, Settings

## BUILD PROGRESS — 10/19 TASKS DONE (5,843 lines real code)

### DONE:
1. shared/ (config, models, redis_bus, db, solana_utils) — 548 lines
2. orchestrator/ (main, fast_path, slow_path, signal_correlator) — 811 lines
3. execution/ (executor, solana_client, priority_fees, risk_manager) — 804 lines
4. wallet_copier/ (main, tx_parser, wallet_registry) — 691 lines
5. engines/progressive_exit/ (exit_engine, main) — 452 lines
6. jito_backrunner/ (main, route_calculator, pool_tracker, flashloan) — 934 lines
7. graduation_sniper/ (main, curve_analyzer) — 632 lines
8. engines/creator_judge/ (main) — 264 lines
9. yield_optimizer/ (main) — 241 lines
10. momentum_scanner/ (main) — 293 lines

### REMAINING (build order):
11. token_launcher/ (Bot 5) — create + Jito bundle launch + creator fees
12. volume_bot/ (Bot 6) — anti-MEV same-block buy+sell for visibility
13. liquidation_bot/ (Bot 9) — flashloan liquidations on Kamino/Solend/Drift
14. engines/social_aggregator/ — Twitter + Telegram hype scoring
15. multi_dex_arb/ (Bot 3, renamed from curve_arb) — full Raydium/Orca/Jupiter routing
16. anti_sniper/ (Bot 7) — create bait tokens, sell into sniper auto-buys
17. engines/graduation_oracle/ — ML graduation probability prediction
18. engines/lp_farmer/ — PumpSwap LP provision + lending rate arb
19. frontend/ — 5-tab React dashboard (Vercel deployment)

## KEY TECHNICAL DECISIONS
- Python for all bots (speed-critical paths would upgrade to Rust later)
- Redis pub/sub replaces Polydesk's file-based IPC (/app/state JSON files)
- 24 Redis channels defined in shared/redis_bus.py Channels class
- All bots are signal generators — orchestrator is the only decision maker
- No bot executes trades directly — all go through execution/ service
- Paper mode enabled by default (PAPER_MODE=true in .env)
- Jito bundles for atomic execution (backrun, launch, volume)
- DexScreener API for price feed in progressive exit engine
- PumpFun program ID: 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P
- Bonding curve: 800M tokens, graduates at ~$69K mcap to PumpSwap

## HOW TO PUSH CODE
GitHub MCP is broken (token expired). Push via VPS:
  cd /tmp/pumpdesk_push
  # write files with ssh:ssh-write-chunk
  git add -A && git commit -m "message" && git push

## REPO STRUCTURE (20 Docker services)
pumpdesk/
├── shared/                    # common libs (config, models, redis_bus, db, solana_utils)
├── orchestrator/              # brain (fast_path, slow_path, signal_correlator, FastAPI)
├── execution/                 # Jito bundles (executor, solana_client, priority_fees, risk_manager)
├── graduation_sniper/         # Bot 1 (curve_analyzer, main)
├── wallet_copier/             # Bot 2 (tx_parser, wallet_registry, main)
├── curve_arb/                 # Bot 3 stub (will rename to multi_dex_arb)
├── momentum_scanner/          # Bot 4 (main)
├── token_launcher/            # Bot 5 stub
├── volume_bot/                # Bot 6 stub
├── anti_sniper/               # Bot 7 stub
├── jito_backrunner/           # Bot 8 (pool_tracker, route_calculator, flashloan, main)
├── liquidation_bot/           # Bot 9 stub
├── yield_optimizer/           # Bot 10 (main)
├── engines/progressive_exit/  # exit_engine, main
├── engines/creator_judge/     # main
├── engines/social_aggregator/ # stub
├── engines/graduation_oracle/ # stub
├── engines/lp_farmer/         # stub
├── nginx/                     # reverse proxy
├── frontend/                  # React dashboard (not started)
├── docker-compose.yml         # 20 services
├── .env.example
└── deploy.sh

## NEXT ACTION
Build task 11: token_launcher/ (Bot 5)
Then continue through tasks 12-19 in order.


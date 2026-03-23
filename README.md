# PumpDesk v2

Full-spectrum PumpFun trading + token launching operation.

## Architecture

- **16 Docker services** communicating via Redis pub/sub
- **7 bots**: 4 trading (sniper, copier, arb, momentum) + 3 creator (launcher, volume, anti-sniper)
- **5 engines**: progressive exit, creator judge, social aggregator, graduation oracle, LP farmer
- **1 orchestrator**: two-tier decision engine (fast path <100ms + Claude AI slow path)
- **1 executor**: Jito bundle construction + priority fee optimization
- **4-tab React dashboard**: Trading Desk, Token Launcher, Intelligence, Settings

## Quick Start

```bash
cp .env.example .env
# Fill in your keys
docker compose up -d --build
```

## Build Order

1. `shared/` — models, Redis bus, config ✅
2. `orchestrator/` — fast path + slow path + API
3. `execution/` — Jito bundles + risk manager  
4. Bots one by one, each plugging into the bus
5. Engines one by one
6. Frontend tabs


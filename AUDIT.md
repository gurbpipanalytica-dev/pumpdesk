# PumpDesk v2 — Live Code Audit
> Audited from live repo on 2026-04-29. All findings based on direct file reads, not static analysis assumptions.

---

## Scores

| Category | Score | Notes |
|---|---|---|
| Architecture | 8/10 | Clean signal → orchestrator → executor pipeline, Redis pub/sub, two-tier decision engine |
| Security | 5/10 | Private key in plain env var, orchestrator port exposed with no auth |
| Implementation | 4/10 | All live Solana tx builders are stubs; only paper mode works |
| Operational | 2/10 | No healthchecks, no Redis AOF, no monitoring, no circuit breakers |
| Testing | 0/10 | No test files found anywhere in repo |

---

## Critical Findings (P0 — Fix Before Any Real Money)

### 1. Wrong Claude model name — slow path is dead in production

**File:** `orchestrator/slow_path.py`, line 80

```python
# BROKEN — this model string does not exist
model="claude-sonnet-4-6"

# CORRECT
model="claude-sonnet-4-20250514"
```

Every 5-minute AI strategy cycle hits the Anthropic API and receives a 400/404 error. The exception handler catches it and returns `{"status": "error"}`. The Claude strategic layer is entirely non-functional. Parameter adjustments, risk assessments, and market regime detection are all silently not happening.

**Fix:** One-line change in `slow_path.py`.

---

### 2. Executor is stubs — no live trades possible

**File:** `execution/executor.py`

The following methods all return `TradeResult(success=False, error="... not implemented yet")` in live mode:

- `_buy_pumpfun()` — bonding curve buys
- `_buy_pumpswap()` — graduated AMM buys
- `_sell_token()` — all sells
- `execute_bundle_launch()` — token creation bundles
- `execute_volume_cycle()` — volume bot buy+sell

Paper mode works correctly. Live mode: zero trades can execute. The architecture is sound — the Jito bundle submission path (`_submit_jito_bundle`) is implemented — but the instruction builders that feed it are missing.

**What needs building:** PumpFun bonding curve buy instruction (requires bonding curve PDA derivation + `buy` discriminator), PumpSwap swap instruction (constant product AMM), and a generic sell that detects bonding curve vs graduated state.

---

### 3. Redis has no AOF persistence — state resets on every restart

**File:** `docker-compose.yml`, Redis service

```yaml
command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
# Missing: --appendonly yes --appendfsync everysec
```

Default Redis persistence is RDB snapshots only, which may not save on a crash. More importantly, `allkeys-lru` eviction is configured, meaning Redis will actively delete keys under memory pressure. On any restart:

- All open positions are gone
- Daily loss counters reset (risk limits stop working)
- Creator/token blacklists cleared
- Reputation scores evicted

The system will re-enter positions it already holds and blow past daily loss limits it thinks it hasn't hit.

**Fix:**
```yaml
command: redis-server --appendonly yes --appendfsync everysec --maxmemory 256mb --maxmemory-policy allkeys-lru
```

---

### 4. No healthchecks — dead services stay "running"

**File:** `docker-compose.yml`

Zero `healthcheck:` blocks on any of the 20 services. Docker will report all containers as `Up` even if the process inside has deadlocked, OOM'd, or is stuck in an infinite retry loop.

The orchestrator in particular has no `/health` endpoint exposed. If it dies, all bots continue publishing signals to a dead consumer — signals pile up in Redis, nothing executes, no alert fires.

**Fix:** Add healthchecks and a `/health` endpoint to the orchestrator FastAPI app:

```yaml
# docker-compose.yml
orchestrator:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8765/health"]
    interval: 30s
    timeout: 5s
    retries: 3
```

---

## Previous Review — Corrections

### config.py syntax errors: FALSE

The prior review claimed `shared/config.py` had corrupted merge artifacts and broken syntax on lines 18, 35, 37, 49. **This is not present in the live repo.** The file is clean, valid Python with correct `os.environ.get()` calls throughout. No `TOTALTOKENSUPPLY=***` or `os.env...EN` patterns exist.

This was likely from a stale diff or a different branch. Do not waste time "fixing" config.py syntax.

---

## Warnings (P1 — Before Live Funds)

### Wallet private key in plain env var

**File:** `shared/config.py`, `.env.example`

```python
WALLET_PRIVATE_KEY = os.environ.get("WALLET_PRIVATE_KEY", "")
```

Readable from `/proc/self/environ` by any process in the container, visible in `docker inspect`, and logged by many orchestration platforms. Acceptable for dev/paper. Unacceptable once real funds land on this wallet.

**Minimum fix:** Inject via Docker secret, not env var. Longer term: KMS or encrypted keystore with key derivation.

---

### Fast path silently resizes zero-size signals

**File:** `orchestrator/fast_path.py`, Rule 7

```python
size = min(signal.size_sol, MAX_POSITION_SOL)
if size <= 0:
    size = MAX_POSITION_SOL * 0.5  # should be: return self._reject(...)
```

A bot publishing `size_sol=0` is signalling an error condition. The correct response is rejection. Instead, the system opens a half-max position. This can cause unexpected exposure if a bot has a bug in its sizing logic.

---

### Jito mempool subscription requires paid tier

**File:** `jito_backrunner/main.py`

The backrunner constructs a WebSocket URL to `wss://mainnet.block-engine.jito.wtf/api/v1/mempool`. This endpoint is not public — it requires whitelisted IP and authentication from Jito Labs (paid partnership). The connection will be refused in production. Contact Jito for access before treating this module as functional.

---

### Orchestrator port exposed with no authentication

**File:** `docker-compose.yml`

```yaml
ports: ["8766:8765"]
```

The orchestrator FastAPI is reachable on the VPS host network. There is no JWT, API key, or HMAC auth on any endpoint. If the VPS firewall has any gap, the orchestrator (including all position state and the signal injection endpoint) is publicly accessible.

---

### Broad exception handling in wallet_copier

**File:** `wallet_copier/main.py`

```python
except Exception as e:
    log.error(f"WS message error: {e}")
```

This catches `KeyboardInterrupt`, `SystemExit`, `MemoryError`, and assertion errors — silently swallowing signals that should propagate. Use specific exception types: `except (json.JSONDecodeError, KeyError, ValueError)`.

---

## Module Status (Live Assessment)

| Module | Status | Notes |
|---|---|---|
| `shared/config.py` | ✅ Working | Clean, no syntax errors |
| `shared/models.py` | ✅ Working | Not reviewed in depth, no issues found |
| `shared/redis_bus.py` | ✅ Working | Clean pub/sub abstraction |
| `orchestrator/fast_path.py` | ✅ Working | Solid rule engine, good latency measurement |
| `orchestrator/slow_path.py` | ❌ Broken | Wrong model name — AI cycles all fail |
| `orchestrator/signal_correlator.py` | ✅ Working | Not reviewed in depth |
| `execution/executor.py` | ⚠️ Paper only | All live tx builders are stubs |
| `execution/risk_manager.py` | ✅ Working | Simple stateful checks |
| `execution/solana_client.py` | ⚠️ Partial | Exists, feeds into unimplemented builders |
| `wallet_copier/` | ⚠️ Partial | WS logic works, no tx execution |
| `jito_backrunner/` | ❌ Blocked | Mempool needs Jito partnership |
| `graduation_sniper/` | ⚠️ Partial | Signal generation likely works, no execution |
| `momentum_scanner/` | ⚠️ Partial | Same as above |
| `yield_optimizer/` | ⚠️ Unknown | Not audited |
| `engines/progressive_exit/` | ⚠️ Partial | Exit logic present, calls unimplemented sell |
| Stub modules (7) | ❌ Empty | `token_launcher`, `volume_bot`, `anti_sniper`, `liquidation_bot`, `social_aggregator`, `graduation_oracle`, `lp_farmer` |

---

## Fix Priority Order

### P0 — Do these now, before anything else

1. **Fix model name** in `orchestrator/slow_path.py`: `claude-sonnet-4-6` → `claude-sonnet-4-20250514`
2. **Add Redis AOF** to `docker-compose.yml`: `--appendonly yes --appendfsync everysec`
3. **Add healthchecks** to `docker-compose.yml` and a `/health` route in orchestrator
4. **Fix fast_path Rule 7** to reject zero-size signals instead of defaulting to half-max

### P1 — Before live funds

5. **Implement `_buy_pumpfun`** in `executor.py` using `solders` + PumpFun program IDL
6. **Implement `_sell_token`** in `executor.py`
7. **Add orchestrator API authentication** (API key header minimum, JWT preferred)
8. **Restrict wallet private key** to Docker secret or encrypted store
9. **Narrow exception handling** in `wallet_copier/main.py`

### P2 — Before MEV modules go live

10. **Contact Jito Labs** for mempool access — paid tier required, cannot be worked around
11. **Rewrite pool tracker** using on-chain event subscriptions (WebSocket subscription limit is ~100 per connection, not viable for multi-DEX at scale)
12. **Implement or remove flashloan module** — currently referenced but not functional

### P3 — Production readiness

13. **Add Prometheus metrics** endpoint: positions, PnL, latency per bot, daily loss %
14. **Add circuit breakers** for RPC failures, Redis disconnects, Jito submission failures
15. **Write tests** — at minimum unit tests for fast_path rule engine and risk_manager

---

## Bottom Line

The architecture is genuinely good — the signal/orchestrator/executor split is clean, Redis pub/sub is the right IPC choice, and the two-tier decision engine (fast rules + slow AI) is well-designed. The slow path model name bug and the missing executor implementation are the two things that make this a paper trading system with a production-looking shell. Fix those two and the system becomes real.

Do not deploy with real funds until executor.py has working transaction builders and the Redis AOF fix is in.

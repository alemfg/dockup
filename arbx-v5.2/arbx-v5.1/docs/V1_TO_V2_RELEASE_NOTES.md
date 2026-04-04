# ArbitrageEngine v2.0.0 — Release Notes

> **Branch:** `v2`  
> **Previous version:** `v1` (monolithic)  
> **Release type:** Major — breaking architecture change  
> **Date:** March 2026

---

## Overview

v2 is a complete architectural overhaul of the ArbitrageEngine.

The core engine logic (strategies, analysis, alerts, simulator) is preserved and significantly improved, but the runtime architecture has been rebuilt from the ground up around a **distributed worker model** — the single most important change in this release.

In v1, the brain collected market data, ran analysis, and managed everything in a single process on a single machine. In v2, **the brain never connects to exchanges.** Lightweight worker processes handle all exchange connectivity and stream data to the brain via a Redis message bus. Workers can run on any machine, anywhere on the internet.

---

## What Changed

### Architecture — Monolith → Distributed

**v1**
```
Engine (single process)
  └── Scheduler
        ├── Collectors (Binance, Kraken, ...)
        ├── Strategies (spatial, triangular, ...)
        └── Analysis
```

**v2**
```
Workers (any machine, any number)
  └── stream prices via Redis → Brain (central)
                                  ├── Analysis Engine
                                  ├── Strategy Scanner
                                  ├── Fleet Monitor
                                  └── API + Dashboard
```

This change enables:
- Workers deployed on machines geographically close to exchanges for lower latency
- Multiple workers per exchange for load distribution
- Automatic failover when a worker gets IP-blocked
- Independent worker scaling without touching the brain

---

## New Features

### 1. Distributed Worker Architecture

Each exchange now has its own dedicated worker process. Workers are:
- Self-contained — one exchange, one or more pairs, configurable via environment variables
- Deployable anywhere — local machine, remote server, cloud VM, Docker container
- Self-classifying — workers detect their own error type (IP block, rate limit, overload) and report it in heartbeats
- Stateless — a replacement worker can start from scratch and be fully operational in seconds

**New files:**
- `worker/worker.py` — full worker implementation
- `scripts/run_worker.py` — worker entry point
- `scripts/generate_worker.py` — credential generator for new workers

### 2. Redis Streams Message Bus

All brain↔worker communication now flows through Redis Streams — an append-only, consumer-group-aware message queue built into Redis (already a dependency in v1).

**12 named streams:**

| Stream | Direction | Content |
|---|---|---|
| `stream:prices` | Worker → Brain | Price ticks |
| `stream:candles` | Worker → Brain | OHLCV candle data (1M, 15M, 1H) |
| `stream:orderbooks` | Worker → Brain | Bid/ask snapshots |
| `stream:heartbeats` | Worker → Brain | Worker health reports |
| `stream:registration` | Worker → Brain | Worker startup announcement |
| `stream:orders` | Brain → Worker | Order execution commands |
| `stream:order_results` | Worker → Brain | Trade execution feedback |
| `stream:balances` | Worker → Brain | Exchange balance updates |
| `stream:spawn_requests` | Brain → Manager | Request to spawn a new worker |
| `stream:worker_commands` | Brain → Worker | Kill, reassign, restart |
| `stream:signals` | Brain → API | Analysis signal outputs |
| `stream:events` | Brain → API | System event log |

**New files:**
- `messaging/bus.py` — Redis Streams abstraction with typed publishers
- `messaging/models.py` — all shared dataclasses (replaces scattered models from v1)

### 3. Worker Fleet Health Management

The brain now continuously monitors every worker and automatically responds to failures without human intervention.

**Conditions detected and handled:**

| Condition | Detection | Automatic Response |
|---|---|---|
| IP blocked | 403/418 in error report | Spawn replacement on different machine |
| Rate limited | 429 in error report | Spawn companion worker, split pairs |
| Worker overloaded | CPU >85% or RAM >800MB | Spawn companion, split pairs |
| Data gone stale | No ticks for 30s | Spawn parallel probe worker |
| Worker crashed | Heartbeat TTL expired | Respawn on different machine |
| High latency | Latency >2000ms | Advisory suggestion |

Typical recovery time for IP block or crash: **5–15 seconds, fully automated.**

**New files:**
- `brain/fleet/monitor.py` — heartbeat consumer, error classifier, action producer
- `worker_manager/manager.py` — Docker spawn daemon running on each machine

### 4. Per-Context Analysis Engine

In v1, all pairs shared the same analysis with the same settings. In v2, every `(exchange, pair)` combination gets its own independent analysis context with:
- Separate price history buffer (500 ticks)
- Per-candle-timeframe history (1M, 15M, 1H)
- Resolved plugin configuration from a 4-level hierarchy
- Independent signal output

**Context config hierarchy (most specific wins):**
```
global defaults → exchange override → pair override → context override
```

Example: disable ARIMA for DOGE, enable gas plugin for Uniswap, all without touching any Python code.

New contexts are created automatically the first time a worker streams data for a new pair — zero configuration needed.

**New files:**
- `analysis/context_engine.py` — context lifecycle management and plugin execution

### 5. Modular Analysis Plugin System

In v1, all analysis was hardcoded in `signal_aggregator.py`. In v2, every analysis module is a self-registering plugin.

**Adding a new plugin requires exactly three steps:**
1. Create a file implementing `AnalysisPlugin`
2. Add `@register` decorator
3. Enable in `config.yaml`

No other code changes — the aggregator automatically discovers and runs it.

**Plugins ship with v2:**

| Plugin | Purpose | Default |
|---|---|---|
| `rsi` | Relative Strength Index | ✅ enabled |
| `macd` | MACD line + signal | ✅ enabled |
| `bollinger_bands` | Volatility bands | ✅ enabled |
| `pattern_detector` | Double top/bottom, trends, S/R | ✅ enabled |
| `arima_predictor` | AR(1) short-term price direction | ✅ enabled |
| `lstm_predictor` | Neural network prediction | ⏸ opt-in |
| `sentiment` | Crypto Fear & Greed Index | ⏸ opt-in |

Each plugin is individually toggleable per-pair and per-exchange via config.

**New files:**
- `analysis/plugins/registry.py` — `@register` decorator and `get_enabled()`
- `analysis/plugins/cr_9am/cr_plugin.py` — 9AM CR model (see below)

### 6. 9AM CR Model (ICT Candle Range Theory)

The most significant new analysis capability in v2. A complete implementation of the ICT Candle Range Theory intraday model.

**What it does:**

The model identifies high-probability intraday reversals using nested timeframe ranges:

1. At 8:00 AM NY — records the 1-hour candle range (HTF, outer boundary)
2. At 9:00 AM NY — records the 15-minute candle range (LTF, inner target)
3. Monitors 1-minute candles for a sweep (wick beyond LTF range, close back inside)
4. After sweep — detects Break of Structure (BOS), Order Block (OB), and Fair Value Gap (FVG)
5. Confirms entry when OB/FVG overlap in discount/premium zone
6. Sets TP1 at opposite end of LTF range, TP2 at opposite end of HTF range

**Setup quality scoring:**

| Element | Score |
|---|---|
| Sweep confirmed | +0.20 |
| BOS confirmed | +0.20 |
| Order Block present | +0.15 |
| FVG confirmed (2nd candle close) | +0.20 |
| IFVG + OB alignment | +0.10 |
| Price in discount/premium | +0.15 |

**Output includes:** Entry price, entry zone, TP1, TP2, stop loss, R:R ratios for both targets, all confirmed structure elements, quality score and confidence label.

**Works on:** Crypto pairs (BTC/USDT, ETH/USDT) and forex pairs (EUR/USD).

**Time-gated:** The plugin only runs during the 9:00–10:00 AM NY window. Outside this window it returns no signals, consuming zero resources.

**New files:**
- `analysis/plugins/cr_9am/cr_plugin.py` — RangeBuilder, SweepDetector, StructureDetector, EntryValidator, plugin

### 7. Multi-Layer Security

Workers in v1 had no authentication. In v2, any worker operating over the internet uses multiple security layers to authenticate with the brain.

**Security layers:**

| Layer | Mechanism | Protects Against |
|---|---|---|
| mTLS | X.509 certificates signed by shared CA | Unknown workers, MITM |
| Worker registry | Brain maintains list of known workers | Unregistered connections |
| HMAC-SHA256 | Every message signed with per-worker key | Tampered messages |
| Nonce + timestamp | UUID nonce + 30s window | Replay attacks |
| Permission scopes | Per-worker allowed pairs, order limits | Compromised workers |
| Multi-IP detection | Simultaneous connections → auto-revoke | Credential theft |

**Worker lifecycle:**
1. Admin generates credentials with `python scripts/generate_worker.py`
2. Secret key transferred securely to worker machine
3. Worker registered in brain via `POST /api/security/workers/register`
4. Every message from worker is verified before processing
5. Compromised worker can be instantly revoked via `POST /api/security/workers/{id}/revoke`

**New files:**
- `brain/security/auth_manager.py` — full authentication and authorization manager
- `scripts/generate_worker.py` — admin credential generator

### 8. Expanded FastAPI Layer

v1 had 9 routes. v2 has 19 REST routes plus 3 WebSocket streams.

**New routes:**

| Endpoint | Description |
|---|---|
| `GET /api/fleet/workers` | Live worker fleet status |
| `GET /api/fleet/workers/{id}` | Single worker inspection |
| `GET /api/fleet/events` | Fleet event log |
| `GET /api/fleet/coverage` | Exchange × pair coverage map |
| `POST /api/fleet/workers/{id}/kill` | Kill a specific worker |
| `POST /api/fleet/workers/{id}/restart` | Restart a worker |
| `POST /api/workers/spawn` | Dynamically spawn a new worker |
| `GET /api/analysis/contexts` | All active analysis contexts |
| `GET /api/analysis/signals` | All current analysis signals |
| `GET /api/analysis/signals/{exchange}/{pair}` | Specific context signal |
| `GET /api/market/spreads` | Cross-exchange spread table |
| `GET /api/cr/signals` | Today's 9AM CR setups |
| `POST /api/security/workers/register` | Register new worker |
| `POST /api/security/workers/{id}/revoke` | Revoke worker credentials |
| `WS /ws/market` | Live price + spread stream |
| `WS /ws/fleet` | Live fleet health stream |
| `WS /ws/signals` | Live analysis + CR signals stream |

### 9. Redesigned Dashboard (8 Panels → 9 Panels)

The React/Vite dashboard has been completely rebuilt around the distributed architecture.

**New panels:**

| Panel | Description |
|---|---|
| **Fleet Health** | Live worker grid with status, latency, CPU, actions (kill/restart) |
| **Worker Inspector** | Deep dive into single worker — live prices, error history, performance metrics |
| **Market Feed** | Cross-exchange spread table with sortable columns, sourced from all workers |
| **9AM CR Model** | Live CR setups with range visualization, structure elements, R:R display |
| **Analysis Contexts** | Per-(exchange×pair) plugin scores with dot indicators |
| **Coverage Map** | Exchange × pair grid showing which worker covers each combination |
| **Security** | Registered workers, credential expiry, rejection log |
| **Event Log** | Filterable real-time system events (INFO / WARNING / ERROR / CRITICAL) |
| **Balances** | Fund distribution per exchange (unchanged from v1) |

### 10. Worker Manager Daemon

A new lightweight daemon that runs on each machine in the fleet. It subscribes to spawn requests from the brain and starts Docker containers automatically.

Handles the `avoid_machine` field — if the brain requests a worker on a different machine (e.g., because the current one is IP-blocked), the manager on the blocked machine ignores the request while managers on other machines compete to handle it.

**New files:**
- `worker_manager/manager.py`
- `scripts/run_worker_manager.py`

### 11. Docker Compose Expanded

v1 had 6 Docker services. v2 has 10.

**Added services:**
- `worker-binance` — Binance price collector worker
- `worker-kraken` — Kraken price collector worker
- `worker-uniswap` — Uniswap DEX collector worker
- `arb-worker-manager` — Worker spawn daemon

All worker containers run with security constraints: `--read-only`, `--cap-drop ALL`, `--memory 256m`, `--cpus 0.5`.

---

## What Was Preserved from v1

Everything listed below was carried forward from v1 with improvements:

- All 7 arbitrage strategies (spatial, triangular, DEX, cross-chain, flash loan simulation, FX, multi-country)
- Opportunity scoring and ranking engine (now uses per-context market signals instead of global)
- Trading simulator (dry-run P&L with fees, slippage, gas)
- Balance manager and rebalance suggestions
- Redis opportunity cache with TTL deduplication
- PostgreSQL persistence with all original tables
- Alert system (console, ntfy, email, webhook, Slack)
- Prometheus metrics
- All CEX collectors (Binance, Kraken, Coinbase, Bybit) — now inside workers
- All DEX collectors (Uniswap, SushiSwap, PancakeSwap, Curve) — now inside workers
- Forex collector — now inside a dedicated worker
- Makefile developer workflow
- `requirements.txt`, `.gitignore`, `.env.example`

---

## Breaking Changes

These v1 patterns no longer apply in v2:

**Engine entry point changed:**
```bash
# v1
python scripts/run_engine.py

# v2
python -m scripts.run_brain          # brain
python -m scripts.run_worker         # worker (set EXCHANGE + PAIRS env vars)
```

**Collectors no longer run inside the brain.** They are now workers. You must start at least one worker for the brain to receive market data.

**Config structure changed.** The `engine:` section is now `brain:`. The `collectors:` section is removed (workers are configured via environment variables, not config.yaml). See `config/config.yaml` for the new structure.

**Analysis config changed.** The `analysis.indicators.*` flat structure is replaced with `analysis.plugins.*` supporting per-plugin weight and params. Existing boolean toggles (e.g., `analysis.prediction.arima: true`) are replaced with `analysis.plugins.arima_predictor.enabled: true`.

---

## Migration Guide

### From v1 local setup

1. Pull the `v2` branch
2. Run `pip install -r requirements.txt` (new dependencies: `pytz`)
3. Copy `config/.env.example` to `config/.env` and update values
4. Update `config/config.yaml` — use the new v2 template as reference
5. Start Redis if not already running
6. Start the brain: `python -m scripts.run_brain`
7. Start at least one worker: `EXCHANGE=binance PAIRS=BTC/USDT,ETH/USDT python -m scripts.run_worker`

### From v1 Docker

```bash
# Stop v1
docker compose -f docker/docker-compose.yml down

# Pull v2
git checkout v2
git pull

# Rebuild and start
make docker-up
```

All previous Redis and PostgreSQL data is compatible — no schema migration needed.

---

## Test Coverage

All 18 tests pass on v2:

```
tests/test_v2.py::test_config_loads_defaults              PASSED
tests/test_v2.py::test_cr_range_properties                PASSED
tests/test_v2.py::test_cr_signal_risk_reward              PASSED
tests/test_v2.py::test_worker_heartbeat_to_dict           PASSED
tests/test_v2.py::test_auth_manager_register_and_verify   PASSED
tests/test_v2.py::test_auth_manager_rejects_replay        PASSED
tests/test_v2.py::test_auth_manager_rejects_unknown_worker PASSED
tests/test_v2.py::test_auth_manager_permission_checks     PASSED
tests/test_v2.py::test_auth_manager_revoke                PASSED
tests/test_v2.py::test_fleet_worker_state_dead_detection  PASSED
tests/test_v2.py::test_fleet_error_classification         PASSED
tests/test_v2.py::test_cr_range_builder_htf               PASSED
tests/test_v2.py::test_cr_range_builder_ltf               PASSED
tests/test_v2.py::test_sweep_detector_low_sweep           PASSED
tests/test_v2.py::test_fvg_detection_bullish              PASSED
tests/test_v2.py::test_entry_validator_produces_long_setup PASSED
tests/test_v2.py::test_context_engine_auto_creates_context PASSED
tests/test_v2.py::test_context_engine_multiple_contexts   PASSED

18 passed in 0.76s
```

---

## New Files Summary

```
brain/
  brain.py                       Brain main entry point
  security/auth_manager.py       mTLS, HMAC, nonce/replay, permissions
  fleet/monitor.py               Heartbeat tracking, error classification
  stream/subscriber.py           Consumes all 8 worker streams

worker/
  worker.py                      Self-contained exchange worker

worker_manager/
  manager.py                     Docker spawn daemon

messaging/
  bus.py                         Redis Streams message bus
  models.py                      All shared dataclasses
  logging.py                     Shared structured logger

analysis/
  context_engine.py              Per-(exchange×pair) context management
  plugins/registry.py            Self-registering plugin system
  plugins/cr_9am/cr_plugin.py    9AM CR model (RangeBuilder, SweepDetector,
                                 StructureDetector, EntryValidator)

storage/
  market_state.py                Unified in-memory market data store

api/routes/
  fleet.py                       Worker fleet management
  workers.py                     Dynamic worker spawning
  analysis.py                    Context and signal inspection
  market.py                      Live prices and spreads
  security.py                    Credential management
  cr_signals.py                  9AM CR setup endpoint
  websocket.py                   3 live WebSocket streams

frontend/src/components/
  FleetHealth.jsx                Worker grid with actions
  WorkerInspector.jsx            Single worker deep-dive
  CRPanel.jsx                    9AM CR model with range visual
  AnalysisContexts.jsx           Per-context plugin scores
  CoverageMap.jsx                Exchange × pair grid
  SecurityPanel.jsx              Worker credentials panel
  EventLog.jsx                   Filterable real-time events
  MarketFeed.jsx                 Cross-exchange spread table

scripts/
  run_brain.py                   Brain entry point
  run_worker.py                  Worker entry point
  run_worker_manager.py          Worker manager entry point
  generate_worker.py             Admin credential generator

docs/
  INSTALL_AND_DEPLOYMENT.md      Complete operational guide
  SYSTEM_DESCRIPTION.md          Full technical reference
```

---

*ArbitrageEngine v2.0.0*

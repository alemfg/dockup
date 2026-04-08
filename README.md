<div align="center">

```
    ___    ____  ____ _  __
   /   |  / __ \/ __ ) \/ /
  / /| | / /_/ / __  |\  /
 / ___ |/ _, _/ /_/ / / /
/_/  |_/_/ |_/_____/ /_/

DISTRIBUTED ARBITRAGE INTELLIGENCE
```

**ARBX v6.7** — A self-hosted, distributed cryptocurrency arbitrage intelligence system.  
Scans 13+ exchanges simultaneously, detects profitable opportunities in real-time,  
and executes trades automatically with full risk management.

[![Python](https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green?style=flat-square)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61dafb?style=flat-square&logo=react)](https://reactjs.org)
[![Redis](https://img.shields.io/badge/Redis-7-red?style=flat-square&logo=redis)](https://redis.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker)](https://docker.com)

</div>

---

## Table of Contents

- [What is ARBX?](#what-is-arbx)
- [Architecture Overview](#architecture-overview)
- [How Data Flows](#how-data-flows)
- [Core Components](#core-components)
- [Arbitrage Modules](#arbitrage-modules)
- [Analysis Modules](#analysis-modules)
- [Risk & Decision System](#risk--decision-system)
- [Vault & Security](#vault--security)
- [Rate Limit Management](#rate-limit-management)
- [Alert System](#alert-system)
- [Dashboard & UI](#dashboard--ui)
- [Technology Stack](#technology-stack)
- [Configuration Reference](#configuration-reference)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Monitoring](#monitoring)
- [FAQ](#faq)

---

## What is ARBX?

ARBX is a **personal, self-hosted distributed arbitrage intelligence system** built for cryptocurrency markets. It connects to multiple exchanges simultaneously, streams real-time price data, detects profitable arbitrage opportunities across several strategy types, and can execute trades automatically.

### Key Capabilities

| Capability | Detail |
|---|---|
| **Exchanges** | 13+ CEX (Binance, Kraken, Bybit, MEXC, KuCoin, Gate.io, OKX, Bitget, HTX, Phemex, WhiteBit, LBank, BitMart) + DEX (Uniswap, SushiSwap, PancakeSwap, Curve) |
| **Pairs** | ALL spot pairs with USDT/USDC/BTC/ETH quote (configurable), up to 400+ per exchange |
| **Strategies** | Spatial, Triangular, Graph (Bellman-Ford + Floyd-Warshall), DEX, Cross-chain, FX |
| **Analysis** | CR 9AM model, RSI, MACD, Bollinger Bands, context engine |
| **Execution** | Simulate mode (log only) or Live mode (real orders via CCXT) |
| **Risk** | Daily loss limits, drawdown circuit breaker, per-exchange exposure caps |
| **Alerts** | ntfy, Slack, Discord, Telegram, Email, Webhook — per-category control |

### What ARBX is NOT

- Not a high-frequency trading system (tick interval: 2s minimum)
- Not a DeFi / MEV bot (though DEX data is collected)
- Not a signal provider service — it is fully self-contained

---

## Architecture Overview

ARBX follows a **distributed brain + worker** architecture. The brain never connects to exchanges directly. Lightweight workers stream price data to the brain via Redis Streams, keeping the core logic clean and exchange-agnostic.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ARBX SYSTEM                                    │
│                                                                             │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                         DOCKER NETWORK (arb-net)                    │  │
│   │                                                                      │  │
│   │  ┌──────────┐    ┌──────────┐    ┌──────────────────────────────┐  │  │
│   │  │  nginx   │    │ React/   │    │         BRAIN                │  │  │
│   │  │  :3005   │◄───│  Vite    │    │   FastAPI + asyncio          │  │  │
│   │  │  proxy   │    │ frontend │    │   ┌──────────────────────┐   │  │  │
│   │  └────┬─────┘    └──────────┘    │   │  Stream Subscriber   │   │  │  │
│   │       │ /api/    /api/ws/        │   │  Decision Engine     │   │  │  │
│   │       ▼                          │   │  Fleet Monitor       │   │  │  │
│   │  ┌──────────────────────────┐    │   │  Auto Spawner        │   │  │  │
│   │  │      REDIS :6379         │    │   │  Graph Arbitrage     │   │  │  │
│   │  │   Redis Streams          │◄───┤   │  Risk Manager        │   │  │  │
│   │  │  ─────────────────────   │    │   │  Alert Sender        │   │  │  │
│   │  │  stream:prices           │    │   └──────────────────────┘   │  │  │
│   │  │  stream:heartbeats       │    │   Port :8000 REST + WS       │  │  │
│   │  │  stream:registrations    │    │   Port :9090 Prometheus      │  │  │
│   │  │  stream:orders           │    └──────────────────────────────┘  │  │
│   │  │  stream:spawn            │                    ▲                  │  │
│   │  │  stream:candles          │                    │                  │  │
│   │  │  stream:balances         │    ┌───────────────┴──────────────┐  │  │
│   │  └────────────┬─────────────┘    │      WORKER MANAGER          │  │  │
│   │               │                  │  Spawns worker containers     │  │  │
│   │               │ publish          │  via Docker socket API        │  │  │
│   │               ▼                  └──────────────────────────────┘  │  │
│   │  ┌────────────────────────────────────────────────────────────┐    │  │
│   │  │                    WORKER FLEET                            │    │  │
│   │  │                                                            │    │  │
│   │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │    │  │
│   │  │  │ worker   │  │ worker   │  │ worker   │  │ worker   │  │    │  │
│   │  │  │ binance  │  │ kraken   │  │  bybit   │  │  mexc    │  │    │  │
│   │  │  │ slot0    │  │ slot0    │  │  slot0   │  │  slot0   │  │    │  │
│   │  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │    │  │
│   │  │       └─────────────┴──────────────┴──────────────┘        │    │  │
│   │  │                    fetch_tickers() ← CCXT                  │    │  │
│   │  │                   (1 call per exchange per tick)            │    │  │
│   │  └────────────────────────────────────────────────────────────┘    │  │
│   │                                                                      │  │
│   │  ┌─────────────────────────────────────────┐                        │  │
│   │  │           POSTGRESQL :5432              │                        │  │
│   │  │  arbx_config  │  api_keys  │  wallets   │                        │  │
│   │  │  fee_tables   │  order_log │  positions │                        │  │
│   │  └─────────────────────────────────────────┘                        │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
               EXCHANGE A      EXCHANGE B      EXCHANGE C
               Binance         Kraken          Bybit
               (public API)    (public API)    (public API)
```

---

## How Data Flows

### Price Collection Pipeline

```
EXCHANGE                  WORKER                    BRAIN
─────────                 ──────                    ─────

REST API ──► fetch_tickers(pairs)   1 call / tick
              │   returns all prices at once
              │   (was: 200 calls → now: 1 call)
              ▼
         Token Bucket ──► rate_limit guard
         (per exchange)   blocks if budget exceeded
              │
              ▼
         publish_price_tick() × N pairs
              │
              ▼
         Redis Stream ──────────────────────────────► StreamSubscriber
         stream:prices                                      │
                                                            ▼
                                                     MarketState.update_price()
                                                            │
                                                    ┌───────┴────────┐
                                                    │ Outlier Filter │
                                                    │ ratio > 10x?   │
                                                    │ → reject       │
                                                    └───────┬────────┘
                                                            │ accepted
                                                            ▼
                                                     _prices[ex:pair] = {
                                                       price, timestamp,
                                                       worker_id, updated_at
                                                     }
                                                            │
                                               ┌────────────┼────────────┐
                                               ▼            ▼            ▼
                                          Spatial      Graph Arb    Analysis
                                          Scanner      Engine       Engine
```

### Decision Pipeline

```
SIGNAL SOURCE              DECISION ENGINE             OUTPUT
─────────────              ───────────────             ──────

SpatialSpread ────────────►                           
GraphArbPath  ────────────► 1. TradingMode gate ────► DISABLED → drop
CR9AMSignal   ────────────►    (disabled/simulate/    
MarketSignal  ────────────►     live)                 
                            │                         
                            ▼                         
                           2. Exchange enabled? ─────► No → drop
                            │                         
                            ▼                         
                           3. Risk Manager ──────────► Circuit breaker
                            │  - daily loss limit        triggered → halt
                            │  - drawdown %              + alert
                            │  - consecutive losses      
                            │  - exchange exposure       
                            ▼                         
                           4. Strategy rules ────────► Below threshold → drop
                            │  - min profit %            
                            │  - min risk/reward         
                            │  - cooldown check          
                            │  - max concurrent orders   
                            ▼                         
                           5. OrderCommand ──────────► SIMULATE: log to DB
                            │                            + alert "opportunity"
                            └───────────────────────► LIVE: publish to
                                                         stream:orders
                                                         → worker executes
                                                         via CCXT
```

### Worker Lifecycle

```
Brain starts
    │
    ▼
AutoSpawner._build_plan()
    │  reads EXCHANGES= env var
    │  resolves pairs for each exchange
    │  applies rate-limit cap:
    │    max_workers = floor(rpm_budget / reqs_per_worker)
    │  splits pairs into balanced chunks
    ▼
Publishes SPAWN messages to stream:spawn
    │
    ▼
WorkerManager receives SPAWN
    │  reads .env + .env.local
    │  injects API keys from Vault
    │  docker run arbx-worker:latest
    ▼
Worker container starts
    │  reads EXCHANGE, PAIRS, API_KEY from env
    │  initialises CCXT client (if API key present)
    │  publishes registration to stream:registrations
    ▼
FleetMonitor registers worker
    │  starts heartbeat TTL timer (45s)
    │  updates fleet health dashboard
    ▼
Worker tick loop (every TICK_INTERVAL_MS=2000)
    │  fetch_tickers(all_pairs) → 1 HTTP call
    │  publish N price ticks to stream:prices
    │  heartbeat every 10s to stream:heartbeats
    ▼
AutoSpawner watch loop (every 60s)
    │  checks live fleet vs expected plan
    │  re-spawns any missing slots
```

---

## Core Components

### Brain (`brain/brain.py`)

The central coordinator. Runs as a long-lived asyncio process inside Docker. Never makes exchange API calls directly.

**Responsibilities:**
- Subscribes to all Redis Streams via `StreamSubscriber`
- Runs the spatial arbitrage scanner loop (every 2s)
- Coordinates the graph arbitrage engine (every 5s Bellman-Ford, every 45s Floyd-Warshall)
- Drives the analysis context engine
- Monitors the fleet and triggers re-spawns
- Exposes the REST API and WebSocket endpoints via FastAPI

**Key internal loops:**

| Loop | Interval | Purpose |
|---|---|---|
| `_spatial_scan_loop` | 2s | Scan all pairs for cross-exchange spreads |
| `_graph_arb_loop` | 5s | Run Bellman-Ford on currency graph |
| `_fw_loop` | 45s | Run Floyd-Warshall as a full cross-check |
| `_fleet_watch_loop` | 60s | Auto-respawn missing workers |
| `_heartbeat_monitor` | 10s | Mark workers dead if TTL expires |

### Workers (`worker/worker.py`)

Lightweight, stateless exchange connectors. Each worker is a separate Docker container. Workers never communicate with each other — only with the brain via Redis Streams.

**What a worker does:**

```
startup:
  1. Read EXCHANGE, PAIRS, API_KEY from environment
  2. Initialise CCXT async client (if API key present)
  3. Register with brain via stream:registrations
  4. Start parallel async loops

loops (all running concurrently via asyncio.gather):
  _tick_loop         → fetch_tickers() + publish prices (every 2s)
  _heartbeat_loop    → publish status + metrics (every 10s)
  _balance_loop      → fetch_balance() (every 60s, API key required)
  _candle_loop       → fetch_ohlcv() (every 60s, initial 200 candles)
  _order_sync_loop   → fetch_open_orders() per pair (every 30s)
  _command_listener  → receive brain commands via stream:worker_commands
```

**Commands a worker accepts:**

| Command | Effect |
|---|---|
| `kill` | Graceful shutdown |
| `pause` | Suspend price ticks (stays connected) |
| `resume` | Resume price ticks |
| `reload_config` | Re-read env vars, apply new tick interval |
| `set_tick_interval` | Change poll rate (rate-limit throttle) |
| `reassign_pairs` | Switch to a new pair list |
| `sync_orders` | Immediate order sync cycle |
| `fetch_balance` | Immediate balance fetch |
| `execute_order` | Place a trade via CCXT |

### WorkerManager (`worker_manager/manager.py`)

Listens on `stream:spawn` and translates SPAWN messages into `docker run` commands via the Docker socket API. Runs as a separate container with access to `/var/run/docker.sock`.

**Flow:**
1. Receives `{ action: "SPAWN", exchange, pairs, worker_id, api_key, api_secret }` from stream
2. Loads base env from `.env` + `.env.local`
3. Injects Vault credentials (api_key, api_secret, passphrase) into container env
4. Calls `docker run arbx-worker:latest` with all env vars

### AutoSpawner (`brain/auto_spawner.py`)

Runs inside the brain process. Reads `EXCHANGES=` config and maintains the fleet:

```
EXCHANGES=binance,kraken,bybit,mexc,bitmart,kucoin,gateio,...
BINANCE_PAIRS=ALL  →  resolves to ~400 pairs
PAIRS_WORKER_SIZE=200  →  splits into 2 workers × 200 pairs

Rate-limit cap:
  Binance rpm=600, 200 pairs, tick=2s
  req/worker/min = 200 × (60/2) = 6000  → but batch=1 call!
  actual: 1 call × 30/min = 30 req/min → well under budget
  max_workers = floor(600/30) = 20 workers safely
```

### StreamSubscriber (`brain/stream/subscriber.py`)

Reads all incoming Redis Streams and dispatches messages to the appropriate handlers in the brain. Maintains consumer group membership for each stream.

**Streams consumed:**

| Stream | Publisher | Handler |
|---|---|---|
| `stream:prices` | Workers | `MarketState.update_price()` |
| `stream:heartbeats` | Workers | `FleetMonitor.update_worker()` |
| `stream:registrations` | Workers | `FleetMonitor.register_worker()` |
| `stream:order_results` | Workers | `OrderLog.record_result()` |
| `stream:candles` | Workers | `MarketState.update_candle()` |
| `stream:balances` | Workers | `MarketState.update_balance()` |

### FleetMonitor (`brain/fleet/monitor.py`)

Tracks all registered workers, their health status, and produces fleet events. Automatically marks workers as DEAD when their heartbeat TTL (45s) expires.

**Worker states:**

```
STARTING → HEALTHY → DEGRADED → BLOCKED → DEAD
                ↓                    ↓
              PAUSED            (auto-respawn)
                ↓
             HEALTHY
```

### MarketState (`storage/market_state.py`)

In-memory store for all market data. Thread-safe via copy-on-iterate pattern. Uses a statistical outlier filter to reject bad prices (e.g. LBank quoting ADA at 100 instead of 0.28).

**Outlier filter:**
```python
# For each new price:
existing = get_prices_for_pair(pair)  # all exchanges' current prices
if existing:
    median = statistics.median(existing.values())
    ratio  = new_price / median
    if ratio > 10.0 or ratio < 0.1:   # _OUTLIER_THRESHOLD
        reject()   # likely a unit mismatch (BTC-denominated vs USDT)
```

---

## Arbitrage Modules

### Spatial Arbitrage

Detects the same asset trading at different prices on different exchanges.

```
Example:
  BTC/USDT on Binance:  $65,000
  BTC/USDT on Kraken:   $65,350

  Gross spread:  (65350 - 65000) / 65000 × 100 = 0.538%
  Buy fees:      0.075% (Binance taker)
  Sell fees:     0.160% (Kraken taker)
  Net profit:    0.538% - 0.075% - 0.160% = 0.303% ✓

Action:
  BUY  0.15 BTC on Binance @ $65,000  (cost: $9,750)
  SELL 0.15 BTC on Kraken  @ $65,350  (recv: $9,802.50)
  Net profit after fees: ~$29.50
```

**UI panel:** Spatial Arb → shows all pairs with cross-exchange spreads, fee-adjusted net profit, capital needed for $100 profit, full exchange price breakdown. Supports "Full Range" mode to analyse all pairs in memory regardless of quote filter.

### Graph Arbitrage

Detects profitable cycles across multiple currency pairs within a single exchange. Uses two algorithms:

#### Bellman-Ford (Primary, every 5s)

Finds negative-weight cycles in the currency graph. A negative cycle = profitable arbitrage loop.

```
Graph construction:
  For each pair A/B at price P:
    add edge A → B with weight -log(P × (1 - fee))
    add edge B → A with weight -log(1/P × (1 - fee))

  (Negative weights because we maximise product of rates
   by minimising sum of -log rates — Bellman-Ford finds
   minimum-weight paths, which correspond to maximum
   rate-of-return cycles)

Example 3-hop cycle:
  USDT → BTC → ETH → USDT

  USDT→BTC: price 65000  fee 0.075%  → weight = -log(1/65000 × 0.99925)
  BTC→ETH:  price 20.2   fee 0.075%  → weight = -log(20.2 × 0.99925)
  ETH→USDT: price 3215   fee 0.075%  → weight = -log(3215 × 0.99925)

  Total cycle weight = sum of edges
  If negative: profitable arbitrage exists

  Minimum capital: $10,000
  Profit on 0.25% net cycle: $25
```

#### Floyd-Warshall (Cross-check, every 45s)

Computes all-pairs shortest paths. More computationally expensive but catches cycles that Bellman-Ford might miss in sparse graphs. Used as a scheduled validation pass.

**Path validator:** After a cycle is found, the path validator checks:
- All edges are fresh (< 15s old)
- Sufficient liquidity exists on each leg
- Cycle doesn't repeat any asset
- Net profit exceeds minimum threshold (configurable, default 0.25%)

### Triangular Arbitrage

A special case of graph arbitrage: 3-hop cycles within one exchange.

```
Example on Binance:
  USDT → BTC → ETH → USDT

  1. Buy BTC with USDT (BTC/USDT @ 65000)
  2. Buy ETH with BTC  (ETH/BTC  @ 0.0492)
  3. Sell ETH for USDT (ETH/USDT @ 3215)

  Start:  $10,000 USDT
  After 1: 0.15385 BTC
  After 2: 3.128 ETH
  After 3: $10,057 USDT

  Gross profit: $57  (0.57%)
  Fees (3 legs × 0.075%): $22.50
  Net profit: $34.50  (0.345%)
```

### DEX Arbitrage

Collects prices from decentralised exchanges (Uniswap v2/v3, SushiSwap, PancakeSwap, Curve) via Web3/CCXT.

```
DEX specifics:
  - Gas costs estimated and deducted from net profit
  - DEX_MAX_GAS_USD=8.0 (skip legs costing more in gas)
  - Slippage modelled at 0.1% per leg
  - MEV protection: uses private RPC or Flashbots (configurable)
  - Pool reserves checked before path validation

Supported DEXes:
  Uniswap v2/v3   (Ethereum)
  SushiSwap       (Ethereum, Arbitrum, Polygon)
  PancakeSwap     (BSC)
  Curve Finance   (Ethereum, stablecoin swaps)
```

### FX / Cross-Country Arbitrage

Monitors fiat currency pairs (EUR/USD, GBP/USD, etc.) and cross-country crypto price premiums (e.g. Korean Won premium on Bitcoin — "Kimchi premium").

---

## Analysis Modules

ARBX includes a plugin-based analysis engine that runs in parallel with arbitrage detection.

### Context Engine (`analysis/context_engine.py`)

Aggregates signals from all analysis plugins into a unified market context score per pair. Each plugin produces a score between -1 (strong bearish) and +1 (strong bullish).

```
Final score = Σ (plugin_score × plugin_weight)

Example:
  RSI score:          +0.4  (RSI=62, slightly bullish)    weight: 0.15
  MACD score:         +0.6  (positive crossover)          weight: 0.15
  Bollinger score:    -0.2  (near upper band)             weight: 0.10
  Sentiment score:     0.0  (neutral)                     weight: 0.10
  CR 9AM score:       +0.8  (valid CR setup detected)     weight: 0.30

  Total: 0.4×0.15 + 0.6×0.15 + (-0.2)×0.10 + 0×0.10 + 0.8×0.30
       = 0.06 + 0.09 - 0.02 + 0 + 0.24 = 0.37
  → Moderate bullish signal
```

### CR 9AM Model (`analysis/plugins/cr_9am/cr_plugin.py`)

Implements the **CRT (CR Theory) 9AM methodology** — a technical analysis approach based on identifying key price ranges established at specific market session openings (1AM, 5AM, 9AM New York time).

**Concepts:**
- **CR Range**: The high-low range formed at 1AM or 5AM NYT opening
- **BOS (Break of Structure)**: Price breaking above/below the CR range
- **FVG (Fair Value Gap)**: An imbalance in the market's price delivery
- **ICT-style targeting**: Entry at mitigation of range, target at 50% or full extension

```
9AM CR Setup Detection:

  1AM range:  [64,800 - 65,200]  (established at 1:00 AM NYT)
  5AM range:  [64,900 - 65,400]  (established at 5:00 AM NYT)
  9AM candle: opens at 65,450    (above both ranges → bullish BOS)

  BOS detected: ✓ (price broke above the CR high)
  FVG detected: ✓ (gap between 9AM candle bodies)

  Entry: ~65,000 (pullback into range)
  SL:     64,700 (below 1AM low)
  TP1:    65,800 (1:1 risk/reward)
  TP2:    66,300 (2:1 risk/reward)

  RR: 2.0 (meets cr_min_rr=1.5 threshold → signal emitted)
  Score: 0.82 (meets cr_min_score=0.65 threshold → approved)
```

**Timeframes monitored:** 1M, 5M, 15M, 1H  
**Active window:** 9:00–10:00 AM New York (configurable)  
**Pairs:** BTC/USDT, ETH/USDT, EUR/USD (configurable)

### Technical Indicators (`analysis/plugins/indicators/indicators.py`)

| Indicator | Signal logic | Weight |
|---|---|---|
| **RSI (14)** | > 70 → bearish, < 30 → bullish, 50-cross → momentum | 0.15 |
| **MACD (12/26/9)** | Histogram sign change, signal line cross | 0.15 |
| **Bollinger Bands (20, 2σ)** | Near lower band → bullish, upper → bearish | 0.10 |
| **Sentiment** | Placeholder for news/social feed integration | 0.10 |

All indicators operate on OHLCV candle data fetched by workers every 60s (initial 200-candle history on startup, incremental after).

---

## Risk & Decision System

### Risk Manager (`brain/decision/risk_manager.py`)

Circuit breaker system that halts trading when limits are exceeded.

```
Circuit Breakers:

  ┌─────────────────────────────────────────────────────────┐
  │  1. Daily Loss Limit (max_daily_loss_usd = $500)        │
  │     Sum of closed P&L today < -$500 → HALT all trading  │
  │     Resets at midnight UTC                               │
  ├─────────────────────────────────────────────────────────┤
  │  2. Drawdown (max_drawdown_pct = 10%)                   │
  │     Peak balance was $10,000                             │
  │     Current balance < $9,000 → HALT                     │
  │     Requires manual reset via dashboard                  │
  ├─────────────────────────────────────────────────────────┤
  │  3. Consecutive Losses (max_consecutive_losses = 5)     │
  │     5 losing trades in a row → HALT                     │
  ├─────────────────────────────────────────────────────────┤
  │  4. Exchange Exposure (max_exchange_exposure = 60%)     │
  │     Single exchange holds > 60% of portfolio → block    │
  │     new positions on that exchange                       │
  ├─────────────────────────────────────────────────────────┤
  │  5. Pair Exposure (max_pair_exposure_usd = $2,000)      │
  │     Open position on one pair > $2,000 → block new      │
  └─────────────────────────────────────────────────────────┘

All limits configurable in config.yaml or via .env.local.
All triggers send alerts via configured channels.
```

### Decision Engine (`brain/decision/engine.py`)

Five-stage pipeline from signal to order:

```
Stage 1: TradingMode gate
  DISABLED  → drop all signals (no orders, no logs)
  SIMULATE  → process signals, log to DB, no real trades
  LIVE      → process signals, execute real trades

Stage 2: Per-exchange enable check
  trading.exchange_enabled.binance = false → drop binance signals

Stage 3: Risk Manager check
  Any circuit breaker triggered → drop with halt alert

Stage 4: Strategy-specific rules
  CR 9AM:
    score ≥ 0.65 (cr_min_score)
    risk/reward ≥ 1.5 (cr_min_rr)
    BOS required: true (cr_require_bos)
    Cooldown: 60s per pair (cooldown_seconds)

  Spatial Arb:
    net_pct > 0 (after fees)
    net_pct ≥ graph_min_profit_pct (0.15%)
    Not in cooldown

  Graph Arb:
    net_profit ≥ graph_min_profit_pct (0.15%)
    Cycle age < graph_max_age_ms (5000ms)
    Not in cooldown

Stage 5: Emit OrderCommand
  id, exchange, pair, side, order_type, price, volume,
  stop_loss, take_profit_1, take_profit_2, capital_usd, source
```

### Position Manager (`brain/decision/positions.py`)

Tracks open positions and auto-closes them when SL/TP levels are hit.

```
For each open position, every 2s:
  current_price = MarketState.get_price(exchange, pair)

  if side == BUY:
    if current_price ≤ stop_loss:    → send SELL market order (SL hit)
    if current_price ≥ take_profit:  → send SELL market order (TP hit)

  if side == SELL:
    if current_price ≥ stop_loss:    → send BUY  market order (SL hit)
    if current_price ≤ take_profit:  → send BUY  market order (TP hit)

  On close: record P&L to order_log, emit alert
```

---

## Vault & Security

### Vault (`api/routes/vault.py`, `storage/db/config_store.py`)

Encrypted credential storage backed by PostgreSQL. API keys, wallet addresses, and fee tables never appear in environment variables at rest — they are encrypted with `ARBX_MASTER_KEY` (AES-256) and stored in the DB.

**Components:**

| Component | Purpose | Table |
|---|---|---|
| API Keys | Exchange credentials (key, secret, passphrase) | `api_keys` |
| Wallet Addresses | Deposit addresses per exchange per asset/network | `wallet_addresses` |
| Taker Fees | Per-exchange fee rates for net profit calc | `fee_table` |
| Withdrawal Fees | Per-coin per-network withdrawal costs | `withdrawal_fees` |
| Transfer Planner | Routes cheapest cross-exchange transfer | (computed) |
| Config Store | Persistent runtime config (pairs, targets, etc.) | `arbx_config` |

**Transfer Planner example:**
```
Transfer 500 USDT from Binance to KuCoin

Cheapest route analysis:
  USDT via TRC20:  fee = 1 USDT   (~$1.00)  min = 10 USDT  ✓ cheapest
  USDT via ERC20:  fee = 25 USDT  (~$25.00) min = 50 USDT
  USDT via BEP20:  fee = 0.8 USDT (~$0.80)  min = 10 USDT  ✓ alternative

Selected: BEP20
  Withdraw from Binance to KuCoin BEP20 address
  Destination: 0x742d35Cc6634C0532925a3b844Bc454e4438f44e
  Net received: 499.20 USDT
  Confirm? → sends actual withdrawal via Binance API
```

### mTLS Security (`brain/security/auth_manager.py`)

Workers authenticate to the brain using mutual TLS certificates. Each worker presents its certificate, which the brain validates against the CA.

```
Certificate chain:
  CA cert (ca.crt)
    ├── Brain cert (brain.crt) — brain server identity
    └── Worker cert (worker-N.crt) — per-worker identity (future)

Nonce system:
  Worker includes a nonce in each heartbeat
  Brain validates nonce is < 30s old (NONCE_TTL)
  Prevents replay attacks
```

---

## Rate Limit Management

### Token Bucket per Worker (`worker/rate_limit.py`)

Each worker instance maintains a token bucket seeded from the exchange's published request-per-minute limit (conservative ~50% of official limit).

```
Token Bucket:

  Exchange: Binance
  RPM limit: 600 (conservative; Binance allows 1200 weight/min)
  
  Bucket refills at: 600 tokens / 60 seconds = 10 tokens/second
  
  Each fetch_tickers() call costs: 1 token
  (vs the old per-pair approach: 200 tokens per tick!)
  
  At 2s tick, 30 ticks/min: 30 tokens consumed
  Budget remaining: 570 tokens/min — plenty of headroom

Per-exchange RPM table (conservative safe values):
  binance:   600   (official: 1200 weight/min)
  kucoin:    900   (official: 1800/min)
  okx:       200   (official: 300/min)
  kraken:     40   (official: 60/min)
  mexc:      120   (official: ~500/min)
  bitget:    120   (official: ~300/min)
  whitebit:  120   (official: ~300/min)

Override any limit: BINANCE_RATE_LIMIT_RPM=400
```

### Back-off on 429

```
429 received:
  consecutive_429s = 1
  backoff = 5s   (initial)

429 again:
  consecutive_429s = 2
  backoff = 10s  (×2 each time)

429 again:
  backoff = 20s → 40s → 80s → 120s (capped)

Success received:
  backoff = backoff / 2 = 60s
  
Next success:
  backoff = 30s → 15s → 7.5s → 0s (cleared)
  consecutive_429s = 0
```

### Pre-spawn Cap (AutoSpawner)

Before spawning workers, the AutoSpawner calculates the maximum safe count:

```python
max_workers = floor(rpm_budget / req_per_worker_per_min)

# Example: Binance, 2s tick, 200 pairs per worker
# With fetch_tickers (batch): 1 req per tick
# Ticks per minute: 60/2 = 30
# req_per_worker_per_min = 1 × 30 = 30
# max_workers = floor(600 / 30) = 20 workers

# If cap is exceeded, pairs are merged into fewer workers
```

### Brain-side Throttle

The dashboard can slow down any exchange's workers at runtime without restart:

```
POST /api/workers/throttle
{ "exchange": "binance", "interval_ms": 5000 }

→ Broadcasts set_tick_interval to all binance workers
→ Tick slows from 2s to 5s
→ Other exchanges unaffected
→ Automatically updates rate guard token budget
```

---

## Alert System

### Channels

| Channel | Config variable | Use case |
|---|---|---|
| **ntfy** | `NTFY_TOPIC`, `NTFY_URL` | Mobile push (free, self-hostable) |
| **Slack** | `SLACK_WEBHOOK_URL` | Team workspace |
| **Discord** | `DISCORD_WEBHOOK_URL` | Community/personal |
| **Telegram** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Mobile push |
| **Email** | `EMAIL_SMTP_HOST`, `EMAIL_FROM`, etc. | Formal notifications |
| **Webhook** | `WEBHOOK_URL` | Custom integration (HTTP POST JSON) |

### Alert Categories

Each category can be independently enabled/disabled and routed to specific channels:

```
📢 Alert Rules (Config → Alert Rules panel):

  🚨 System Errors        critical  → ntfy + slack + telegram
     Worker down, Redis/DB unreachable, brain crash

  ⚠️  Market Alerts        high      → ntfy
     Stale pairs, rate limits hit, exchange blocked

  💰 Opportunities         default   → ntfy + slack
     Spatial arb found, graph cycle detected, CR setup

  🛑 Risk Events           high      → all channels
     SL/TP hit, daily loss limit, drawdown circuit breaker

  📋 Order Events          default   → ntfy
     Order placed, filled, failed (disabled by default)

  ⚙️  Operational           low       → none
     Config reload, worker spawn (disabled by default)
```

### Alert payload example (ntfy):

```
Title: 💰 ARBX — Opportunity Found
Body:  BTC/USDT spatial arb: BUY binance @ 65000,
       SELL kraken @ 65350 | net 0.303% | $29.50 on $9,750
Tags:  opportunity, spatial, btc
Priority: 3 (default)
```

---

## Dashboard & UI

ARBX ships with a full React dashboard served by nginx. Built with Vite, React 18, Tailwind CSS.

### Pages & Panels

```
Navigation bar:
  Fleet Health     → Worker status, API health, latency, fleet events
  Market Feed      → Live price stream, cross-exchange spreads
  Graph Arb        → Detected arbitrage cycles, profitability
  Spatial Arb      → Cross-exchange spread table, full-range mode
  9AM CR Model     → CR signal state, setup quality scores
  Analysis         → Context engine signals, indicator readings
  Coverage         → Exchange × pair coverage map
  Balances         → All configured exchanges, sync button, P&L
  Trading Mode     → Enable/disable simulate or live trading
  Orders           → Open orders, history, manual placement
  Config & Reload  → Exchange manager, risk settings, alert rules
  Financials       → P&L charts, daily statistics
  Risk & Rules     → Circuit breaker status, manual reset
  Logs             → Live log viewer (WebSocket streaming)
  Fin. Events      → Financial event timeline
  Vault            → API keys, wallet addresses, fees, transfer planner
  Security         → mTLS certificate status
  Fleet Events     → Worker registration and death events
```

### Real-time Features

| Feature | Transport | Update rate |
|---|---|---|
| Price feed | WebSocket `/ws/market` | 2s |
| Fleet status | WebSocket `/ws/fleet` | 3s |
| Signals | WebSocket `/ws/signals` | 5s |
| Log viewer | WebSocket `/api/ws/logs` | real-time |
| Spreads | Polling `/api/market/spreads` | 5s |
| Balances | Polling `/api/balances` | 10s |
| Rate limits | Polling `/api/workers/rate-limits` | 10s |

### Sortable Tables

All major tables support click-to-sort on column headers (▲/▼/⇅):
- **Fleet Health**: Worker ID, Exchange, Pairs, Status, Latency
- **Market Feed**: Pair, Spread, Last seen
- **Spatial Arb**: Pair, Spread %, Net %, exchanges
- **Config → Exchanges**: Exchange, Workers, Status
- **Vault → API Keys**: Exchange, Label, Mode, Created
- **Vault → Fees**: Exchange, Taker %, Maker %
- **Orders → Open**: Pair, Exchange, Side, Volume, Price, Status
- **Orders → History**: Pair, Exchange, Side, Status, P&L

---

## Technology Stack

### Backend

| Component | Technology | Purpose |
|---|---|---|
| Brain API | **FastAPI** 0.109 + **uvicorn** | REST + WebSocket server |
| Async runtime | **asyncio** (Python 3.12) | Concurrent loops |
| Message bus | **Redis 7** Streams | Worker ↔ Brain communication |
| Database | **PostgreSQL 16** + **asyncpg** | Persistent storage |
| Exchange API | **CCXT** 4.2 | Unified exchange connector (130+ exchanges) |
| Graph algorithms | Custom Python | Bellman-Ford, Floyd-Warshall on -log(rate) weights |
| DEX | **Web3.py** 6 | Ethereum/EVM chain interaction |
| HTTP client | **aiohttp** 3.9 | Async HTTP (alerts, webhooks) |
| Monitoring | **prometheus-client** | Metrics export |
| Config | **Pydantic** v2 + **PyYAML** | Typed config models |
| Docker SDK | **docker** 7 | Worker container spawning |

### Frontend

| Component | Technology | Purpose |
|---|---|---|
| Framework | **React 18** | UI components |
| Build tool | **Vite** | Fast development + production builds |
| Styling | **Tailwind CSS** 3 | Utility-first CSS |
| HTTP client | **axios** | REST API calls |
| Transport | Native **WebSocket** | Real-time streaming |
| Icons | Unicode/emoji | No external icon dependency |

### Infrastructure

| Component | Technology | Purpose |
|---|---|---|
| Reverse proxy | **nginx:alpine** | Static files + API proxy + WS upgrade |
| Containerisation | **Docker Compose** | Service orchestration |
| Monitoring | **Prometheus** (external) | Metrics scraping |
| Dashboards | **Grafana** (external) | Metrics visualisation |

---

## Configuration Reference

### `config/config.yaml` — Main configuration

```yaml
brain:
  dry_run: true                  # Global dry-run flag
  log_level: "INFO"              # DEBUG | INFO | WARNING | ERROR

trading:
  mode: "disabled"               # disabled | simulate | live
  min_profit_percent: 0.5        # Minimum gross spread to consider
  max_position_usd: 10000        # Maximum per-trade capital
  max_concurrent_orders: 3       # Max open orders at once

risk:
  max_daily_loss_usd: 500        # Daily loss circuit breaker
  max_drawdown_pct: 10.0         # Peak-to-trough drawdown limit
  max_consecutive_losses: 5      # Consecutive loss circuit breaker
  max_exchange_exposure: 0.6     # Max fraction on one exchange

graph_arbitrage:
  algorithm: "bellman_ford"      # bellman_ford | floyd_warshall
  max_hops: 5                    # Maximum cycle length
  min_profit_pct: 0.1            # Minimum net profit after fees
  capital_usd: 10000             # Capital for profit estimation
  scan_interval_seconds: 5       # Bellman-Ford run interval

analysis:
  plugins:
    rsi:
      enabled: true
      weight: 0.15
      params: { period: 14, overbought: 70, oversold: 30 }
    macd:
      enabled: true
      weight: 0.15
      params: { fast: 12, slow: 26, signal: 9 }
    bollinger_bands:
      enabled: true
      weight: 0.10
      params: { period: 20 }

alerts:
  ntfy_enabled: false
  ntfy_url: "https://ntfy.sh"
  ntfy_topic: ""
  slack_enabled: false
  slack_webhook: ""
```

### `config/.env.local` — Personal overrides (never committed)

```bash
# Exchange list (AutoSpawner will spawn workers for each)
EXCHANGES=binance,kraken,bybit,mexc,kucoin,gateio,okx

# Pairs per exchange (ALL = resolve from CCXT load_markets)
BINANCE_PAIRS=ALL
KRAKEN_PAIRS=BTC/USDT,ETH/USDT,SOL/USDT
BYBIT_PAIRS=ALL

# Quote filter when using ALL (comma-separated)
PAIRS_ALL_QUOTE_FILTER=USDT,USDC,BTC,ETH

# Max pairs per worker (excess splits into multiple workers)
PAIRS_WORKER_SIZE=200

# Tick interval in milliseconds
TICK_INTERVAL_MS=2000

# Trading mode
TRADING_MODE=simulate

# Vault encryption key (generate: python3 -c "import secrets; print(secrets.token_hex(32))")
ARBX_MASTER_KEY=your-32-byte-hex-key

# Alert channels
NTFY_TOPIC=my-arbx-alerts
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Rate limit overrides (optional)
BINANCE_RATE_LIMIT_RPM=500
KRAKEN_RATE_LIMIT_RPM=35

# Database
POSTGRES_PASSWORD=your-password
```

---

## Quick Start

### Prerequisites

- Docker + Docker Compose v2
- 2GB RAM minimum (4GB recommended for 7+ exchanges)
- Linux/macOS (Windows with WSL2)

### 1. Clone & configure

```bash
git clone https://github.com/your-username/arbx
cd arbx

# Copy personal config template
cp config/.env.local.example config/.env.local

# Edit your settings
nano config/.env.local
```

### 2. Set minimum config

```bash
# config/.env.local
EXCHANGES=binance,kraken          # Start with 2 exchanges
BINANCE_PAIRS=BTC/USDT,ETH/USDT  # Explicit pairs for safety
KRAKEN_PAIRS=BTC/USDT,ETH/USDT
TRADING_MODE=simulate             # Safe: no real orders
POSTGRES_PASSWORD=changeme123
ARBX_MASTER_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

### 3. Build & start

```bash
make docker-rebuild    # First time: builds all images
# or
make docker-up         # Subsequent starts (no rebuild)
```

### 4. Open dashboard

Navigate to `http://localhost:3005`

Default view: Fleet Health → should show workers connecting within 30s.

### 5. Verify data flow

```
Fleet Health    → workers show "healthy" with green dots
Market Feed     → prices updating every 2s
Spatial Arb     → spreads appearing (need 2+ exchanges with same pair)
Logs            → green "● live" indicator, log lines streaming
```

### 6. Enable trading (optional)

```bash
# Add to config/.env.local:
TRADING_MODE=simulate   # See decisions in Orders panel, no real trades
# then:
make docker-reload      # Hot-reload (no rebuild needed)
```

To go live:
```bash
TRADING_MODE=live
# Also add API keys via Dashboard → Vault → API Keys
```

### Makefile targets

```bash
make docker-rebuild     # Full rebuild of all images
make docker-up          # Start without rebuild
make docker-down        # Stop all containers
make docker-reload      # Restart brain only (hot config reload)
make docker-logs        # Follow all container logs
make docker-logs-brain  # Brain logs only
make test-quick         # Quick health check (bash)
make test-full          # Full test suite (94 checks)
make test-report        # Test report with details
```

---

## Environment Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `EXCHANGES` | (none) | Comma-separated exchange list for AutoSpawner |
| `{EX}_PAIRS` | `BTC/USDT,ETH/USDT` | Pairs for exchange EX (`ALL` = full market) |
| `PAIRS_WORKER_SIZE` | `200` | Max pairs per worker before splitting |
| `PAIRS_ALL_QUOTE_FILTER` | `USDT,USDC,BTC,ETH` | Quote currencies when `PAIRS=ALL` |
| `TICK_INTERVAL_MS` | `2000` | Price fetch interval (ms) |
| `TRADING_MODE` | `disabled` | `disabled` / `simulate` / `live` |
| `ARBX_MASTER_KEY` | (required) | 32-byte hex key for Vault encryption |

### Ports

| Variable | Default | Service |
|---|---|---|
| `BRAIN_API_PORT` | `8000` | FastAPI REST + WebSocket |
| `BRAIN_METRICS_PORT` | `9090` | Prometheus scrape |
| `FRONTEND_PORT` | `3005` | nginx dashboard |
| `REDIS_PORT` | `6379` | Redis |
| `POSTGRES_PORT` | `5432` | PostgreSQL |

### Performance

| Variable | Default | Description |
|---|---|---|
| `HEARTBEAT_INTERVAL_S` | `10` | Worker heartbeat frequency |
| `HEARTBEAT_TTL` | `45` | Seconds before worker marked dead |
| `BALANCE_INTERVAL_S` | `60` | Balance fetch interval |
| `ORDER_SYNC_INTERVAL_S` | `30` | Order sync interval |
| `CANDLE_INTERVAL_S` | `60` | Candle fetch interval |
| `PRICE_OUTLIER_THRESHOLD` | `10.0` | Ratio for outlier rejection |
| `EXCHANGES_WATCH_INTERVAL` | `60` | AutoSpawner fleet check interval |
| `{EX}_RATE_LIMIT_RPM` | (table) | Override RPM budget for exchange EX |

### Alerts

| Variable | Description |
|---|---|
| `NTFY_TOPIC` | ntfy topic name (enables ntfy automatically) |
| `NTFY_URL` | Custom ntfy server (default: https://ntfy.sh) |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat/group/channel ID |
| `EMAIL_SMTP_HOST` | SMTP server hostname |
| `EMAIL_FROM` / `EMAIL_TO` | Email sender/recipient |

---

## API Reference

All endpoints are under `/api/`. WebSocket endpoints are under `/ws/` and `/api/ws/`.

### Market

```
GET  /api/market/prices           → all current prices
GET  /api/market/prices/{ex}/{pair} → single price
GET  /api/market/spreads          → cross-exchange spreads with fees
GET  /api/market/all-pairs        → spreads for ALL pairs (no filter)
GET  /api/market/rejected         → outlier rejection stats
```

### Workers

```
GET  /api/fleet/workers           → all workers + status
POST /api/workers/{id}/kill       → kill worker
POST /api/workers/{id}/pause      → pause ticks
POST /api/workers/{id}/resume     → resume ticks
POST /api/workers/{id}/reload     → reload config
POST /api/workers/spawn           → spawn new worker
POST /api/workers/throttle        → set tick interval per exchange
GET  /api/workers/rate-limits     → per-exchange rate limit status
```

### Orders

```
GET  /api/orders                  → order log (history)
GET  /api/orders/open             → open orders
POST /api/orders/place            → manual order placement
POST /api/orders/{id}/cancel      → cancel order
POST /api/orders/sync             → force sync from all exchanges
```

### Balances

```
GET  /api/balances                → balances by exchange
GET  /api/balances/summary        → totals + P&L snapshot
POST /api/balances/sync           → force fetch from all workers
```

### Vault

```
GET  /api/vault/apikeys           → list stored API keys (masked)
POST /api/vault/apikeys           → store new API key
POST /api/vault/apikeys/{ex}/test → test connectivity
DELETE /api/vault/apikeys/{ex}    → delete API key
GET  /api/vault/wallets           → list wallet addresses
POST /api/vault/wallets           → add wallet address
GET  /api/vault/fees              → taker fee table
PUT  /api/vault/fees/{ex}         → update exchange fee
GET  /api/vault/withdrawal-fees   → withdrawal fee table
POST /api/vault/transfer/plan     → plan a cross-exchange transfer
POST /api/vault/transfer/execute  → execute transfer
```

### Config & Alerts

```
GET  /api/config/current          → full current config snapshot
POST /api/config/reload           → hot-reload brain config
GET  /api/config/exchanges/active → configured exchanges + worker status
GET  /api/alerts/categories       → alert category config
PATCH /api/alerts/categories/{id} → update alert category
POST /api/alerts/test/{channel}   → test a specific alert channel
```

### WebSockets

```
WS  /ws/market                    → live price + spread stream (2s)
WS  /ws/fleet                     → live fleet status (3s)
WS  /ws/signals                   → live analysis signals (5s)
WS  /api/ws/logs                  → live log stream (real-time)
```

---

## Monitoring

ARBX exposes a Prometheus metrics endpoint at `:9090/metrics`.

### Key metrics

```
# Worker fleet
arbx_workers_total{status="healthy"}   5
arbx_workers_total{status="dead"}      0

# Price data
arbx_price_updates_total{exchange="binance"}   145820
arbx_stale_pairs_count                         0

# Arbitrage
arbx_opportunities_detected_total{strategy="spatial"}  234
arbx_opportunities_acted_total{strategy="spatial"}      12
arbx_graph_cycles_found_total                           89

# Performance
arbx_tick_latency_ms{exchange="binance",quantile="0.99"}  487
arbx_redis_stream_lag_seconds{stream="prices"}             0.003

# Trading
arbx_orders_total{mode="simulate",status="filled"}   12
arbx_daily_pnl_usd                                   127.50
```

### External Prometheus + Grafana

```yaml
# prometheus.yml
scrape_configs:
  - job_name: arbx
    static_configs:
      - targets: ['YOUR_SERVER_IP:9090']
    scrape_interval: 15s
```

Pre-built Grafana dashboard at `monitoring/grafana/arbx-dashboard.json`.

---

## FAQ

**Q: Does ARBX execute trades automatically?**  
A: Yes, when `TRADING_MODE=live`. Spatial arb, graph arb, and CR 9AM signals are all wired to the decision engine. Set `TRADING_MODE=simulate` first to see decisions logged without real trades.

**Q: Why is TRADING_MODE disabled by default?**  
A: Safety first. Arbitrage requires precise timing and sufficient capital on both legs simultaneously. Verify signals, test spreads, and understand slippage/fees before going live.

**Q: I hit Binance rate limits. What do I do?**  
A: ARBX v6.7 uses `fetch_tickers()` (batch), which uses ~1 API weight per tick instead of 200. If still hitting limits: lower `TICK_INTERVAL_MS=4000` or `BINANCE_RATE_LIMIT_RPM=300`. The throttle button in Config → Rate Limit Monitor slows workers without restart.

**Q: What does "stale pairs" mean?**  
A: Pairs that haven't received a price update in >30s. With the v6.7 batch fetch, stales should be near zero. If high stales persist, check worker health in Fleet Health → look for rate-limited or blocked status.

**Q: Why are some exchanges showing "Starting" when workers are running?**  
A: Fixed in v6.6. The status now reads the actual worker `status` field instead of a 45s dead-timer.

**Q: Can I add a new exchange not in the list?**  
A: Any exchange supported by CCXT works. Add it to `EXCHANGES=` in `.env.local`, ensure `{EX}_PAIRS` is set, and restart. Rate limit RPM can be set with `{EX}_RATE_LIMIT_RPM=60`.

**Q: The Vault shows a spinner forever.**  
A: PostgreSQL may not be ready. Check `docker logs arb-postgres`. The spinner clears automatically once the DB is accessible (fixed in v6.7 — `usePolling` clears loading on error).

**Q: Does ARBX support futures/perpetuals?**  
A: Currently spot markets only. CCXT supports futures; adding a `type=swap` market filter to the worker is the extension point.

**Q: How many workers can I run?**  
A: Limited by `MAX_WORKERS=50` (configurable) in the WorkerManager and your server's RAM (~256MB per worker container). On a 4GB machine: ~12 workers comfortably. Rate limits are the practical ceiling for most exchanges.

**Q: Is my API key safe?**  
A: API keys are encrypted at rest with AES-256 using `ARBX_MASTER_KEY`. They are injected into worker containers at spawn time via environment variables (not stored on disk in workers). The dashboard never receives key or secret values — only masked previews.

---

<div align="center">

**ARBX** is a personal research and trading tool.  
Always backtest strategies, start with simulate mode, and never risk more than you can afford to lose.

*Built with ❤️ for the serious systematic trader.*

</div>

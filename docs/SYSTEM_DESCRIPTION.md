# ARBX v4.4 — System Description

> **Version:** 2.0.0  
> **Document type:** Technical reference  
> **Audience:** Developers, quantitative analysts, traders

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Module Reference](#3-module-reference)
4. [Arbitrage Strategies](#4-arbitrage-strategies)
5. [Analysis System](#5-analysis-system)
6. [9AM CR Model (ICT Candle Range Theory)](#6-9am-cr-model-ict-candle-range-theory)
7. [Market Data Collectors](#7-market-data-collectors)
8. [Security Model](#8-security-model)
9. [Fleet Health Management](#9-fleet-health-management)
10. [Data Flow](#10-data-flow)
11. [API Reference](#11-api-reference)
12. [Dashboard Panels](#12-dashboard-panels)
13. [Configuration Reference](#13-configuration-reference)
14. [Extending the System](#14-extending-the-system)

---

## 1. System Overview

ARBX v4.4 is a professional, distributed, modular crypto arbitrage research and simulation platform. It is designed around one central principle: **the brain should never connect to exchanges directly.**

Instead, a fleet of lightweight worker processes — each dedicated to a single exchange — stream market data to a central brain via a message bus. The brain focuses exclusively on analysis, strategy evaluation, and decision-making.

### Design goals

- **Horizontal scalability:** Add workers on any machine without modifying the brain
- **Fault isolation:** A crashed or blocked worker does not affect the brain or other workers
- **Modularity:** Every analysis plugin, strategy, and alert channel can be independently toggled
- **Security:** Workers operating over the internet authenticate with the brain using multiple layers
- **Research-first:** Dry-run mode is the default; live trading requires explicit opt-in

### What the system does

The engine continuously:

1. Collects price data from centralized exchanges (CEX), decentralized exchanges (DEX), and forex sources via specialized workers
2. Analyzes per-(exchange × pair) market signals using a modular plugin system
3. Scans for arbitrage opportunities across 7 distinct strategy types
4. Applies the 9AM CR (Candle Range Theory) model for intraday setups
5. Scores and ranks every opportunity using a multi-factor algorithm
6. Simulates trades in dry-run mode, calculating P&L after fees, slippage, and gas
7. Manages fund balances and suggests rebalancing across exchanges
8. Alerts operators via multiple channels when significant opportunities arise
9. Monitors worker fleet health and automatically recovers from failures

---

## 2. Architecture

### High-level architecture

```
┌──────────────────────────────────────────────────┐
│                React Dashboard                    │
│   Fleet · CR Model · Analysis · Security · Map   │
└─────────────────────┬────────────────────────────┘
                      │  HTTP / WebSocket
┌─────────────────────▼────────────────────────────┐
│                FastAPI Brain API                  │
│         10 REST routes + 3 WebSocket streams      │
└─────────────────────┬────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────┐
│                  Brain Core                       │
│                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────┐  │
│  │ Auth Manager│  │ Fleet Monitor│  │ Market  │  │
│  │ mTLS · HMAC │  │ Heartbeats · │  │ State   │  │
│  │ Permissions │  │ Failover     │  │ Store   │  │
│  └─────────────┘  └──────────────┘  └─────────┘  │
│                                                   │
│  ┌─────────────────────────────────────────────┐  │
│  │           Context Analysis Engine           │  │
│  │  Per-(exchange × pair) analysis contexts    │  │
│  │  ┌────────┐ ┌──────┐ ┌────────┐ ┌────────┐ │  │
│  │  │RSI/MACD│ │ARIMA │ │Patterns│ │CR 9AM  │ │  │
│  │  │Bollinger│ │Pred.│ │Detector│ │Plugin  │ │  │
│  │  └────────┘ └──────┘ └────────┘ └────────┘ │  │
│  └─────────────────────────────────────────────┘  │
└─────────────────────┬────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────┐
│              Redis Streams Bus                    │
│                                                   │
│  stream:prices      stream:candles                │
│  stream:orderbooks  stream:heartbeats             │
│  stream:orders      stream:balances               │
│  stream:events      stream:spawn_requests         │
└──────┬───────────────────────────────┬────────────┘
       │                               │
┌──────▼──────┐                 ┌──────▼──────┐
│  Worker     │  ...            │  Worker     │
│  Binance    │                 │  Uniswap    │
│  Machine A  │                 │  Machine C  │
└─────────────┘                 └─────────────┘
```

### Key architectural decisions

**Push vs pull:** Workers push data to the brain via Redis Streams. The brain never polls. This eliminates rate-limit pressure on the brain and allows workers to be on any network.

**Per-context analysis:** Each (exchange, pair) combination has its own independent analysis context with its own price history, plugin configuration, and signal output. BTC/USDT on Binance and BTC/USDT on Kraken are analyzed independently.

**Plugin registry:** Analysis plugins self-register at import time. Adding a new plugin requires creating one file and one config entry — no other code changes.

**Stateless workers:** Workers carry no persistent state. If a worker crashes, a replacement starts fresh with the same configuration and quickly rebuilds its price history from live feeds.

---

## 3. Module Reference

### `messaging/` — Communication Layer

**`messaging/bus.py`** — Redis Streams message bus abstraction

The MessageBus class wraps Redis Streams with typed publisher methods and a consumer group subscriber. All brain↔worker communication flows through named streams. The bus interface is designed to be swap-replaceable with NATS for higher throughput requirements.

Stream names and their purpose:

| Stream | Published by | Consumed by | Contents |
|---|---|---|---|
| `stream:prices` | Workers | Brain | Price ticks per exchange/pair |
| `stream:candles` | Workers | Brain | OHLCV candle data (1M, 15M, 1H) |
| `stream:orderbooks` | Workers | Brain | Bid/ask orderbook snapshots |
| `stream:heartbeats` | Workers | Fleet Monitor | Worker health status |
| `stream:registration` | Workers | Stream Subscriber | Initial worker announcement |
| `stream:orders` | Brain | Workers | Order execution commands |
| `stream:order_results` | Workers | Brain | Trade execution feedback |
| `stream:balances` | Workers | Brain | Exchange balance updates |
| `stream:spawn_requests` | Brain | Worker Managers | Request to spawn new workers |
| `stream:worker_commands` | Brain | Workers | Kill, reassign, restart commands |
| `stream:signals` | Brain | API/WebSocket | Analysis signal outputs |
| `stream:events` | Brain | API/WebSocket | System event log |

**`messaging/models.py`** — Shared dataclasses

All data structures shared between brain, workers, and API are defined here. Key classes:

- `WorkerHeartbeat` — health report from worker
- `FleetAction` — decision from fleet monitor (RESPAWN, SPAWN_REPLACEMENT, etc.)
- `CRRange` — candle high/low range with equilibrium calculation
- `CRSignal` — complete 9AM CR setup with entry, TP1, TP2, SL, R:R
- `Sweep` — detected range sweep (high_sweep or low_sweep)
- `OrderBlock` — last opposing candle before impulse
- `FVG` — fair value gap (3-candle imbalance)
- `Opportunity` — arbitrage opportunity with score and confidence
- `MarketSignal` — aggregated analysis signal per context
- `PluginResult` — output from a single analysis plugin

---

### `brain/` — Central Brain

**`brain/brain.py`** — Main entry point

Initializes all components, connects to the message bus, starts async tasks, and handles graceful shutdown on SIGINT/SIGTERM. The brain starts four concurrent tasks: stream subscriber, fleet monitor, API server, and strategy scanner.

**`brain/security/auth_manager.py`** — Authentication and authorization

Manages the registry of known workers, verifies HMAC signatures on all incoming messages, tracks nonces to prevent replay attacks, and enforces per-worker permission scopes. See [Security Model](#8-security-model) for full details.

**`brain/fleet/monitor.py`** — Fleet health manager

Consumes heartbeats from all workers and maintains a live `WorkerState` for each. Applies the `HealthDecisionEngine` to classify problems and produce `FleetAction` objects. Actions are published to the event stream and acted upon by the failover system.

**`brain/stream/subscriber.py`** — Stream data router

Subscribes to all worker-published streams and routes each message to the appropriate handler: price ticks → context engine, candles → market state + context engine, heartbeats → fleet monitor, order results → market state.

---

### `analysis/` — Analysis Engine

**`analysis/context_engine.py`** — Per-context analysis manager

Creates and manages an `AnalysisContext` for every unique (exchange, pair) combination seen. Each context has:
- An independent price history ring buffer (500 ticks)
- Per-candle-timeframe history (1M, 15M, 1H, up to 200 candles each)
- A resolved plugin configuration (merged from global → exchange → pair → context overrides)
- The most recent `MarketSignal` output

Contexts are created automatically when workers stream new data — no manual configuration needed.

**`analysis/plugins/registry.py`** — Plugin registry

Provides `@register` decorator and `get_enabled()` function. Plugins register themselves at import time. The aggregator calls `get_enabled(config)` to get only the plugins enabled in the current context's config.

---

### `worker/` — Exchange Worker

**`worker/worker.py`** — Self-contained exchange connector

A worker is a single-purpose process dedicated to one exchange. It runs three concurrent loops:

1. **Tick loop:** Fetches prices from the exchange (via CCXT or simulation) and publishes to `stream:prices`
2. **Heartbeat loop:** Every 5 seconds, publishes health metrics to `stream:heartbeats`
3. **Command listener:** Subscribes to `stream:worker_commands` and `stream:orders`, responding to kill, reassign, and execute commands

Error self-classification: the worker parses its own error messages and sets its condition to `ip_block`, `rate_limit`, `exchange_down`, or `auth_error`. The brain's fleet monitor reads this classification in the next heartbeat.

---

### `worker_manager/` — Spawn Daemon

**`worker_manager/manager.py`** — Docker container manager

A lightweight daemon that runs on each machine. It subscribes to `stream:spawn_requests` and spawns Docker containers when requested by the brain. It respects the `avoid_machine` field to prevent spawning on the same IP that got blocked.

---

### `storage/` — Data Layer

**`storage/market_state.py`** — Unified market data store

An in-memory store updated by the stream subscriber. Holds the latest price tick, candle history, orderbook, and balance for every exchange/pair/asset seen. Provides query methods used by the API and strategy modules. Thread-safe under asyncio's cooperative multitasking model.

---

### `api/` — REST + WebSocket API

**`api/main.py`** — FastAPI application factory

Creates the FastAPI app with the brain reference injected into `app.state`. All routes access the brain's components (market state, fleet monitor, auth manager, context engine) through this reference.

**Route modules:**

| Module | Routes | Description |
|---|---|---|
| `routes/system.py` | `GET /api/system/status`, `GET /api/health` | Brain health and uptime |
| `routes/fleet.py` | `GET /api/fleet/workers`, `POST /api/fleet/workers/{id}/kill` | Worker management |
| `routes/workers.py` | `POST /api/workers/spawn` | Dynamic worker creation |
| `routes/analysis.py` | `GET /api/analysis/contexts`, `GET /api/analysis/signals` | Analysis context inspection |
| `routes/market.py` | `GET /api/market/prices`, `GET /api/market/spreads` | Live market data |
| `routes/balances.py` | `GET /api/balances` | Fund distribution |
| `routes/security.py` | `POST /api/security/workers/register` | Worker credential management |
| `routes/cr_signals.py` | `GET /api/cr/signals` | Today's 9AM CR setups |
| `routes/websocket.py` | `WS /ws/market`, `/ws/fleet`, `/ws/signals` | Live streaming endpoints |

---

## 4. Arbitrage Strategies

Seven independent strategy modules scan for different types of price inefficiency. Each strategy inherits from `BaseStrategy`, which handles deduplication, validation, simulation, and persistence automatically.

Every strategy implements the same interface:

```python
async def _find_opportunities() -> List[Opportunity]
async def validate(opp: Opportunity) -> bool
async def simulate_trade(opp: Opportunity) -> SimulationResult
```

### 4.1 Spatial Arbitrage

**File:** `arbitrage/spatial_arbitrage.py`  
**Type:** Cross-exchange, same pair  
**Typical spread:** 0.1–2.0%

Detects price differences for the same trading pair across different centralized exchanges. Example: BTC/USDT trading at $65,000 on Binance and $65,500 on Kraken creates a 0.77% spread.

All exchange combinations are checked in both directions. The scanner runs across 8 pairs simultaneously on all configured exchanges.

**Execution requirements:**
- Accounts on both exchanges
- Same asset available on both sides
- Transfer speed: immediate (no blockchain bridge needed)

### 4.2 Triangular Arbitrage

**File:** `arbitrage/triangular_arbitrage.py`  
**Type:** Within single exchange, 3-leg cycle  
**Typical spread:** 0.05–0.5%

Detects pricing inconsistencies in 3-way currency cycles within a single exchange. Example on Binance: USDT → BTC → ETH → USDT, where the circular conversion yields more USDT than started with.

The scanner checks 7 cycle combinations (USDT/BTC/ETH, USDT/BTC/BNB, USDT/ETH/SOL, etc.) on 3 exchanges.

**Execution requirements:**
- Account on a single exchange
- All three assets available
- No transfer delays — all legs execute on the same platform

### 4.3 DEX Arbitrage

**File:** `arbitrage/dex_arbitrage.py`  
**Type:** CEX vs DEX pool price  
**Typical spread:** 0.3–3.0%

Compares prices between centralized exchange order books and decentralized exchange liquidity pools. Example: ETH priced at $3,200 on Binance vs $3,165 in a Uniswap pool creates a 1.1% opportunity.

Checks all CEX/DEX combinations for 6 tracked pairs. Gas costs are explicitly factored into the P&L calculation.

**Execution requirements:**
- CEX account + funded wallet for DEX
- Web3 provider URL configured
- Gas costs reduce net profit significantly on small trades

### 4.4 Cross-Chain Arbitrage

**File:** `arbitrage/cross_chain_arbitrage.py`  
**Type:** Same asset, different blockchains  
**Typical spread:** 0.2–1.5%

Detects price differences for the same asset on different blockchain networks. Example: ETH on Ethereum (Uniswap) vs ETH on BSC (PancakeSwap), with a bridge facilitating the transfer.

Bridge costs and bridge time (10–20 minutes typically) are factored into the opportunity score. Higher bridge time = lower score.

**Execution requirements:**
- Wallets on multiple chains
- Bridge smart contract or manual bridging
- Sufficient time tolerance for bridge delays

### 4.5 Flash Loan Arbitrage (Simulation Only)

**File:** `arbitrage/flashloan_arbitrage.py`  
**Type:** Zero-capital DeFi cycle  
**Typical net profit:** 0.1–1.0%  
**⚠️ Simulation only — no real transactions executed**

Models zero-collateral flash loan cycles. Borrow $100,000 USDC from Aave, buy ETH cheap on Uniswap, sell ETH higher on SushiSwap, repay the loan + fee, keep the profit — all in one atomic transaction.

Simulates three flash loan providers (Aave V3 at 0.09%, Uniswap V3 at 0.05%, Balancer at 0.00%) and calculates net profit after loan fees, gas, and slippage.

The module produces realistic P&L simulations but generates no on-chain transactions. A Solidity contract would be required for live execution.

**What is simulated:**
- Loan amount: $100,000 USDC
- Loan fee per provider
- Swap slippage on both DEX legs
- Gas estimate (~$25 per flash transaction)

### 4.6 FX Arbitrage

**File:** `arbitrage/fx_arbitrage.py`  
**Type:** Regional fiat currency conversion spreads  
**Typical spread:** 0.3–5.0%

Detects price inefficiencies caused by fiat currency differences across geographic exchanges. Example: BTC/USD on Binance.US vs BTC/EUR on Kraken, where the USD/EUR exchange rate creates a discrepancy in effective USD-equivalent prices.

Requires the Forex collector to be running for real-time FX rates. Falls back to simulated rates if forex collector is unavailable.

**Pairs tracked:** USD/EUR, USD/JPY, USD/KRW, USD/TRY, USD/BRL

### 4.7 Multi-Country Arbitrage

**File:** `arbitrage/multi_country_arbitrage.py`  
**Type:** Regional demand premiums  
**Typical spread:** 0.5–5.0%

Models geographic price premiums caused by capital controls, local demand, and market inefficiencies. The most famous example is the "Kimchi Premium" — BTC historically trading 1–5% higher on Korean exchanges than global markets.

**Regional premiums modeled:**

| Region | Phenomenon | Typical Range |
|---|---|---|
| Korea | Kimchi Premium | 1–5% |
| Japan | Japan Premium | 0.5–2% |
| Turkey | Inflation hedge demand | 2–8% |
| Brazil | Local demand premium | 1–3% |
| EU | Cross-border EUR spread | 0.2–1% |

**Important:** Transfer costs and capital control friction are subtracted from gross premiums. Net profitability depends heavily on ability to transfer capital across borders.

---

### Opportunity Scoring

Every opportunity from all strategies is scored 0.0–1.0 using six weighted factors:

| Factor | Weight | Calculation |
|---|---|---|
| **Profit percent** | 40% | `min(profit_pct / 10.0, 1.0)` |
| **Liquidity** | 20% | `log(volume_usd) / log(max_volume)` |
| **Execution probability** | 15% | Strategy-specific constant (spatial=0.85, cross_chain=0.50) |
| **Transfer time** | 10% | `1 - (bridge_minutes / 60)` |
| **Gas cost** | 10% | `1 - (gas_usd / 100)` |
| **Risk penalty** | 5% | `1 - strategy_risk` (spatial=0.10, flashloan=0.40) |

The final score is multiplied by a market signal adjustment factor (0.9–1.1×) from the analysis engine.

**Confidence labels:**
- `HIGH`: score ≥ 0.75
- `MEDIUM`: score ≥ 0.50
- `LOW`: score < 0.50

---

## 5. Analysis System

The analysis system is built around a self-registering plugin architecture. Each plugin is independent, configurable per-(exchange × pair) context, and failure-isolated from all others.

### 5.1 Plugin system

**Self-registration:** Plugins register at import time using the `@register` decorator:

```python
@register
class MyPlugin(AnalysisPlugin):
    name = "my_plugin"
```

**Configuration hierarchy** (most specific wins):

```
global defaults
    ↓
exchange-level override (e.g., "uniswap" section)
    ↓
pair-level override (e.g., "DOGE/USDT" section)
    ↓
context override (e.g., "uniswap:ETH/USDT" section)
```

**Failure isolation:** If a plugin throws an exception, it is logged as a warning and skipped. The signal is computed from the remaining successful plugins with weights renormalized.

**Score aggregation:** Each plugin returns a `signal_score` (0.0–1.0) and a `weight`. The final signal is a weighted average across all successful plugins for that context.

### 5.2 Technical Indicators Plugin

**Plugin name:** `rsi`, `macd`, `bollinger_bands`, `moving_averages`

**RSI (Relative Strength Index)**
- Period: configurable (default 14)
- Interpretation: >70 = overbought (bearish signal), <30 = oversold (bullish signal), 40–60 = neutral
- Score contribution: neutral zone scores highest (most favorable for arbitrage entries)

**MACD (Moving Average Convergence Divergence)**
- Fast EMA: 12, Slow EMA: 26, Signal: 9
- Bullish crossover (MACD > signal line) adds score
- Bearish crossover subtracts score

**Bollinger Bands**
- Period: 20, Standard deviations: 2
- Band width percentage determines volatility classification
- Band width >4% = HIGH volatility (slight score reduction — wider spreads but higher slippage risk)

**Moving Averages**
- SMA 20, SMA 50, EMA 12
- SMA 20 > SMA 50 × 1.005 = BULLISH trend
- SMA 20 < SMA 50 × 0.995 = BEARISH trend

### 5.3 Price Prediction Plugin

**Plugin name:** `arima_predictor`, `lstm_predictor`

**AR(1) / ARIMA-style predictor (default)**
- Model: First-order autoregression using last 20 price points
- Output: Predicted price 5 ticks ahead, direction (BULLISH/BEARISH/NEUTRAL), confidence
- Weight: 0.20 (highest of all plugins — forward-looking)
- Resource requirement: Minimal (pure Python, no external dependencies)

**LSTM predictor (optional)**
- Model: Long Short-Term Memory neural network
- Requires: `tensorflow>=2.15` (disabled by default — heavy dependency)
- Enable in config: `lstm_predictor.enabled: true`
- Weight: 0.25 when enabled
- Training: Uses collected price history (cold start on first run)

### 5.4 Pattern Detector Plugin

**Plugin name:** `pattern_detector`

Identifies common chart patterns on recent price history:

- **Support level:** Average of local price minima over last 50 ticks
- **Resistance level:** Average of local price maxima
- **Double top:** Two peaks at similar price levels → bearish reversal signal
- **Double bottom:** Two troughs at similar levels → bullish reversal signal
- **Rising trend:** Second half average > first half average × 1.005
- **Falling trend:** Second half average < first half average × 0.995

**Signal output:**
- `CAUTION_RESISTANCE` → near resistance, avoid longs
- `POTENTIAL_BOUNCE` → near support, favorable for longs
- `BULLISH_CONTINUATION` → uptrend, favor long entries
- `BEARISH_CONTINUATION` → downtrend, favor short entries
- `NEUTRAL` → no strong pattern

### 5.5 Sentiment Plugin

**Plugin name:** `sentiment`

Fetches the Crypto Fear & Greed Index from alternative.me API.

- Score 0–25: Extreme Fear → high volatility expected → score reduction
- Score 25–45: Fear → cautious
- Score 45–55: Neutral → no adjustment
- Score 55–75: Greed → mild boost
- Score 75–100: Extreme Greed → high volatility expected → score reduction

Both extreme fear and extreme greed increase spread volatility, which is captured in the signal adjustment.

**Disabled by default** — requires internet access to alternative.me. Enable in config:
```yaml
analysis:
  plugins:
    sentiment:
      enabled: true
      weight: 0.10
```

### 5.6 Volume Profile Plugin (stub — add your own)

**Plugin name:** `volume_profile`

A placeholder for custom volume-based analysis. Demonstrates how easy it is to add a new plugin:

1. Create `analysis/plugins/my_plugin.py`
2. Implement `async def run()` returning `PluginResult`
3. Add `@register` decorator
4. Enable in `config.yaml`

No other code changes required.

---

## 6. 9AM CR Model (ICT Candle Range Theory)

The 9AM CR model is a time-gated analysis plugin implementing the ICT (Inner Circle Trader) Candle Range Theory methodology for intraday setups.

### 6.1 Conceptual framework

The model is built on one core insight: **specific candles form a range, price sweeps (purges) one side of that range, and then reverses to deliver to the other side.**

It uses nested timeframe analysis:
- **HTF (Higher Time Frame):** 1-hour candle at 8:00 AM — the outer boundary
- **LTF (Lower Time Frame):** 15-minute candle at 9:00 AM — the inner target range

Price is expected to sweep the inner LTF range, then deliver to the outer HTF range extremes.

### 6.2 Step-by-step execution

**Step 1 — 8:00 AM: Build HTF range**

The 1-hour candle closing at 9:00 AM (covering the 8:00–9:00 hour) defines the outer reference range. Its High and Low become the final profit targets (TP2).

```
HTF Range:
  High: 66,000  ← TP2 for longs
  Low:  64,000  ← TP2 for shorts
  Equilibrium: 65,000 (midpoint)
```

**Step 2 — 9:00 AM: Build LTF range**

The first 15-minute candle of the 9:00 hour (9:00–9:15) defines the inner range. Its High and Low become the first profit targets (TP1) and the sweep trigger levels.

```
LTF Range:
  High: 65,420  ← sweep trigger for shorts, TP1 for longs
  Low:  65,180  ← sweep trigger for longs, TP1 for shorts
  Equilibrium: 65,300
```

**Step 3 — 9:00–10:00 AM: Monitor for sweep**

On the 1-minute chart, watch for price to exceed one side of the LTF range with a wick, then close back inside. This is the sweep (purge):

```
Bullish setup:  price wicks below 65,180, closes above 65,180
                → low swept → look for long entry
                
Bearish setup:  price wicks above 65,420, closes below 65,420
                → high swept → look for short entry
```

**Step 4 — Structure confirmation**

After the sweep, confirm market structure on the 1-minute chart:

- **BOS (Break of Structure):** Price closes beyond a prior swing high (bullish) or low (bearish), confirming the directional shift
- **Order Block (OB):** The last opposing candle before the impulse move — the last red candle before a bullish impulse, or last green candle before a bearish impulse
- **FVG (Fair Value Gap):** A 3-candle imbalance where candle 1 and candle 3 leave a gap between them; requires the second candle (confirmation) to have closed

**Step 5 — Entry validation**

- Entry zone: overlap of OB and FVG (IFVG + OB alignment = strongest setup)
- Price must be in **discount** for longs (below LTF equilibrium)
- Price must be in **premium** for shorts (above LTF equilibrium)
- Wait for 2nd candle close to confirm the FVG before entering

**Step 6 — Targets and stop**

```
For a long setup:
  Entry:  FVG midpoint or OB midpoint
  TP1:    LTF range High (65,420)    ← take partials here
  TP2:    HTF range High (66,000)    ← let runners reach here
  SL:     Below sweep low with buffer
```

### 6.3 Setup quality scoring

Each setup receives a composite score based on which elements are confirmed:

| Element | Score contribution |
|---|---|
| Sweep confirmed | +0.20 (required) |
| BOS confirmed | +0.20 |
| Order Block present and valid | +0.15 |
| FVG confirmed (2nd candle closed) | +0.20 |
| IFVG + OB alignment | +0.10 |
| Price in optimal zone (discount/premium) | +0.15 |

Minimum score to surface as a signal: **0.55**

Confidence labels: HIGH ≥ 0.75, MEDIUM ≥ 0.55, LOW < 0.55

### 6.4 Risk-reward calculation

The `CRSignal.risk_reward_tp1` and `risk_reward_tp2` properties calculate:

```
R:R = |entry_price - target| / |entry_price - stop_loss|
```

A setup with entry at 65,100, TP1 at 65,420, TP2 at 66,000, and SL at 65,050 gives:
- R:R to TP1 = 320 / 50 = **6.4:1**
- R:R to TP2 = 900 / 50 = **18.0:1**

### 6.5 Configuration

```yaml
analysis:
  cr_9am:
    enabled: true
    weight: 0.30
    timezone: "America/New_York"    # New York = standard trading session
    active_from_hour: 9             # Start monitoring at 9:00 AM NY
    active_to_hour: 10              # Stop at 10:00 AM NY
    min_setup_score: 0.55
    pairs:
      - "BTC/USDT"
      - "ETH/USDT"
      - "EUR/USD"                   # Forex pairs also supported
```

### 6.6 Forex application

The same model works on forex pairs (EUR/USD, GBP/USD, etc.) with the same logic. The 9:00 AM New York time corresponds to approximately 2:00 PM London time — still within the active forex session.

---

## 7. Market Data Collectors

### 7.1 CEX collectors

All CEX collectors share a base class (`BaseCollector`) and operate with the same pattern:
- Try to initialize a CCXT client with configured API keys
- If keys not present, fall back to simulation mode
- Simulation mode generates realistic price ticks with random noise around known base prices

**Binance collector** — `worker/collectors/binance_collector.py`
- Library: CCXT `binance`
- WebSocket: Native Binance WebSocket feed for low-latency streaming
- Pairs: BTC/USDT, ETH/USDT, BNB/USDT, SOL/USDT, ADA/USDT, XRP/USDT, DOGE/USDT, AVAX/USDT
- Simulation base prices: BTC=$65,000, ETH=$3,200, etc.

**Kraken collector** — `worker/collectors/kraken_collector.py`
- Library: CCXT `kraken`
- Note: Simulation prices include a small persistent spread vs Binance to model real market conditions
- Pairs: BTC/USDT, ETH/USDT, SOL/USDT, ADA/USDT, XRP/USDT, DOT/USDT, MATIC/USDT, LINK/USDT

**Coinbase collector** — `worker/collectors/coinbase_collector.py`
- Library: CCXT `coinbase`
- Pairs: BTC/USDT, ETH/USDT, SOL/USDT, AVAX/USDT, MATIC/USDT, LINK/USDT, UNI/USDT, AAVE/USDT

**Bybit collector** — `worker/collectors/bybit_collector.py`
- Library: CCXT `bybit`
- Pairs: BTC/USDT, ETH/USDT, SOL/USDT, XRP/USDT, DOGE/USDT, BNB/USDT, TON/USDT, SUI/USDT

### 7.2 DEX collectors

All DEX collectors use web3.py when a provider URL is configured, and fall back to simulation.

**Uniswap V3** — `worker/dex/uniswap_collector.py`
- Chain: Ethereum mainnet
- Pairs: ETH/USDT, BTC/USDT, UNI/USDT, LINK/USDT, AAVE/USDT, WBTC/USDT
- In production: reads prices from Uniswap V3 pool contracts via web3.py

**SushiSwap** — `worker/dex/sushiswap_collector.py`
- Chain: Ethereum mainnet
- Pairs: ETH/USDT, BTC/USDT, SUSHI/USDT, LINK/USDT, AAVE/USDT, UNI/USDT

**PancakeSwap** — `worker/dex/pancakeswap_collector.py`
- Chain: Binance Smart Chain
- Uses `BSC_PROVIDER_URL` (separate from Ethereum provider)
- Pairs: BNB/USDT, BTC/USDT, ETH/USDT, CAKE/USDT, XRP/USDT, ADA/USDT

**Curve Finance** — `worker/dex/curve_collector.py`
- Chain: Ethereum mainnet
- Specialization: Stablecoin and liquid staking token (LST) pairs
- Pairs: USDC/USDT, DAI/USDT, ETH/USDT, WBTC/USDT, stETH/ETH, FRAX/USDT

### 7.3 Forex collector

**`worker/collectors/forex_collector.py`**

Sources (in priority order):
1. **ECB (European Central Bank)** — XML daily rate feed, free, no API key
2. **exchangerate.host** — REST API, free tier, no API key for basic pairs
3. **OpenExchangeRates** — Requires `OPENEXCHANGERATES_APP_ID` in `.env`
4. **Simulation** — Falls back to realistic rates if all sources fail

Pairs: USD/EUR, USD/JPY, USD/KRW, USD/TRY, USD/BRL  
Update frequency: Every 60 seconds (FX rates change slowly)

---

## 8. Security Model

### 8.1 Threat model

The security system is designed to protect against:

| Threat | Mitigation |
|---|---|
| Unknown worker sends fake prices | HMAC signature verification + worker registry |
| MITM attack on brain↔worker traffic | mTLS mutual certificate authentication |
| Replay attack (reuse of old messages) | UUID nonce + 30-second timestamp window |
| Compromised worker executes unauthorized orders | Per-worker permission scopes |
| IP block forces worker to different machine | Credential tied to worker ID, not IP |
| Credential theft (worker ID stolen) | Multiple-IP detection triggers auto-revocation |
| DDoS on brain heartbeat stream | Rate limiting + anomaly detection |
| Price manipulation by compromised worker | Median cross-validation against other workers |

### 8.2 Authentication layers

**Layer 1 — mTLS (production)**

Mutual TLS requires both brain and worker to present valid certificates signed by the shared CA. A worker without a valid certificate cannot establish a TCP connection to the brain, regardless of knowing the address.

**Layer 2 — Worker registry**

Every legitimate worker is registered in the brain's `AuthManager` with its exchange, allowed pairs, permissions, and expiry date. Messages from unregistered workers are rejected.

**Layer 3 — HMAC-SHA256 signatures**

Every message from a worker is signed with a per-worker secret key using HMAC-SHA256. The brain verifies each signature before processing.

**Layer 4 — Nonce + timestamp**

Each message includes:
- A UUID nonce (never reused)
- A Unix timestamp

The brain rejects:
- Messages with timestamps older than 30 seconds
- Messages with a nonce already seen in the current window

This prevents replay attacks where an attacker captures and resubmits a valid message.

**Layer 5 — Permission scopes**

Each registered worker has defined permissions:
- `allowed_pairs`: which pairs it may stream (empty = all)
- `can_execute_orders`: whether brain will send it order commands
- `max_order_size_usd`: hard cap on any single order
- `ip_whitelist`: optional list of allowed source IPs
- `expires_at`: automatic credential expiry

### 8.3 Anomaly detection

Automatic responses to suspicious patterns:

| Pattern | Response |
|---|---|
| Same worker_id from 2+ IPs simultaneously | Auto-revoke (credential theft suspected) |
| Heartbeat rate > 100/minute | Rate limit (DDoS suspected) |
| Message replay detected | Reject message + log |
| Price deviates >5% from median of all workers for same pair | Quarantine worker (manipulation suspected) |
| Unregistered certificate connection attempt | Reject + log |

---

## 9. Fleet Health Management

### 9.1 Condition detection

The fleet monitor classifies each worker's health every 5 seconds based on:

1. **Heartbeat presence:** If no heartbeat received in TTL seconds → `DEAD`
2. **Error classification:** Last error message analyzed against known patterns
3. **Data freshness:** Per-pair tick timestamps monitored independently
4. **Resource usage:** CPU and memory from heartbeat payload

**Error pattern matching:**

| Error pattern | Condition | Auto-response |
|---|---|---|
| 403, 418, "banned", "forbidden" | `IP_BLOCK` | Spawn replacement on different machine |
| 429, "rate limit", "too many requests" | `RATE_LIMIT` | Spawn companion, split pairs |
| 502, 503, "maintenance" | `EXCHANGE_DOWN` | Alert only |
| 401, "unauthorized", "invalid api key" | `AUTH_ERROR` | Alert + suggest key rotation |
| CPU >85% or RAM >800MB | `OVERLOADED` | Spawn companion, split pairs |
| No ticks for 30s (worker alive) | `STALE_DATA` | Spawn parallel probe |
| Heartbeat gap > 15s | `DEAD` | Respawn on different machine |

### 9.2 Fleet action types

| Action | Description | Kills original? |
|---|---|---|
| `RESPAWN` | Restart dead worker on different machine | Yes (it's dead) |
| `SPAWN_REPLACEMENT` | New worker takes over entirely | Yes |
| `SPAWN_COMPANION` | New worker shares the load | No |
| `SPAWN_PARALLEL` | New worker runs alongside for comparison | No |
| `SUGGEST` | Log advisory, no auto-action | No |
| `NONE` | Worker is healthy | No |

### 9.3 Pair splitting

When a companion is spawned for load sharing, the brain reassigns pairs intelligently:

```
Original worker handles: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT
Worker overloaded → spawn companion

Reassignment:
  Original keeps: BTC/USDT, ETH/USDT  (highest value pairs stay)
  Companion gets: SOL/USDT, BNB/USDT  (lower priority moved)
```

Pairs are ranked by trading volume from the price data stream. Highest-volume pairs stay on the most stable worker.

### 9.4 Typical recovery times

| Condition | Detection time | Recovery time | Total |
|---|---|---|---|
| IP block | 0–5s | 4–8s | ~9s |
| Rate limit | 0–5s | 4–8s | ~9s |
| Worker crash | 0–15s (TTL) | 4–8s | ~20s |
| Overload | 0–5s | 4–8s | ~10s |
| Stale data | 30s | 4–8s | ~35s |

---

## 10. Data Flow

### Price tick flow (worker → brain → analysis → API)

```
1. Worker fetches price from exchange (every 2 seconds)
2. Worker publishes to stream:prices
   { exchange: "binance", pair: "BTC/USDT", price: 65204.20, worker_id: "..." }

3. Brain StreamSubscriber receives tick
4. Calls MarketState.update_price() → latest price stored
5. Calls ContextEngine.on_price_tick() → price appended to context history

6. Every 10 ticks, ContextEngine._run_plugins() is called:
   - RSI computed on last 30 prices → PluginResult(score=0.65)
   - MACD computed → PluginResult(score=0.71)
   - CR 9AM checked (only active 9–10AM NY) → PluginResult or None
   - Results aggregated → MarketSignal(score=0.68, confidence=MEDIUM)

7. Signal published to stream:signals
8. WebSocket /ws/signals pushes update to connected dashboards
9. GET /api/analysis/signals returns latest signals
```

### Opportunity flow (strategy → ranking → simulation → alert)

```
1. Brain runs SpatialArbitrage.scan() every 5 seconds
2. Reads market state: binance BTC=$65,200, kraken BTC=$65,700
3. Calculates spread: 0.77%

4. Opportunity created:
   { pair: "BTC/USDT", buy: "binance", sell: "kraken", profit_pct: 0.77 }

5. RankingEngine.score() called:
   - Profit score: 0.31 (×0.40 weight)
   - Liquidity score: 0.72 (×0.20)
   - Exec probability: 0.85 (×0.15)
   - Market signal: 0.68 (adjustment factor)
   → Final score: 0.58, confidence: MEDIUM

6. Cache check: "BTC/USDT-binance-kraken-spatial" not in Redis → new opportunity

7. TradingSimulator.simulate() called:
   - Buy fee: 0.1% = $65.20
   - Sell fee: 0.26% = $170.82
   - Slippage: 0.05% = $32.60
   → Net profit: $231.38 (0.355% net)

8. Saved to Redis (TTL 10s) and PostgreSQL
9. AlertManager.send() called → ConsoleAlert prints formatted output
10. WebSocket /ws/signals updated
```

---

## 11. API Reference

Full interactive documentation: `http://localhost:8000/docs`

### REST endpoints

| Method | Endpoint | Response |
|---|---|---|
| `GET` | `/api/health` | `{"status": "ok"}` |
| `GET` | `/api/system/status` | Brain health, uptime, market summary, worker count |
| `GET` | `/api/fleet/workers` | Array of all worker states |
| `GET` | `/api/fleet/workers/{id}` | Single worker detail |
| `GET` | `/api/fleet/events` | Fleet event log (last 100) |
| `GET` | `/api/fleet/coverage` | Exchange × pair coverage map |
| `POST` | `/api/fleet/workers/{id}/kill` | Send kill command to worker |
| `POST` | `/api/fleet/workers/{id}/restart` | Trigger worker respawn |
| `POST` | `/api/workers/spawn` | Request new worker spawn |
| `GET` | `/api/analysis/contexts` | All active analysis contexts |
| `GET` | `/api/analysis/signals` | Latest signal per context |
| `GET` | `/api/analysis/signals/{exchange}/{pair}` | Single context signal |
| `GET` | `/api/market/prices` | All latest price ticks |
| `GET` | `/api/market/spreads` | Cross-exchange spread table |
| `GET` | `/api/balances` | Fund balances per exchange |
| `GET` | `/api/cr/signals` | Today's 9AM CR setups |
| `GET` | `/api/cr/signals/{exchange}/{pair}` | CR signal for specific pair |
| `GET` | `/api/security/workers` | Registered workers + rejection log |
| `POST` | `/api/security/workers/register` | Register new worker |
| `POST` | `/api/security/workers/{id}/revoke` | Revoke worker credentials |

### WebSocket streams

| Endpoint | Push interval | Contents |
|---|---|---|
| `WS /ws/market` | Every 2s | Latest prices, market summary |
| `WS /ws/fleet` | Every 3s | Worker statuses, recent events |
| `WS /ws/signals` | Every 5s | Analysis signals, CR setups |

All WebSocket messages are JSON with a `type` field indicating the message type.

---

## 12. Dashboard Panels

The React dashboard communicates with the brain exclusively via the REST API and three WebSocket streams. All panels update automatically without page refresh.

| Panel | Tab | Data source | Refresh |
|---|---|---|---|
| **Fleet Health** | Fleet Health | `WS /ws/fleet` | 3s |
| **Worker Inspector** | Fleet Health (click worker) | `GET /api/fleet/workers/{id}` | 4s |
| **Market Feed** | Market Feed | `WS /ws/market` | 2s |
| **9AM CR Model** | 9AM CR Model | `GET /api/cr/signals` | 10s |
| **Analysis Contexts** | Analysis | `GET /api/analysis/contexts` + signals | 8s |
| **Coverage Map** | Coverage | `GET /api/fleet/coverage` | 8s |
| **Balances** | Balances | `GET /api/balances` | 10s |
| **Security** | Security | `GET /api/security/workers` | 15s |
| **Event Log** | Events | `GET /api/fleet/events` | 5s |

### CR Panel features

The CR Panel provides a visual range representation alongside standard data:
- Horizontal bar showing HTF range, LTF range, and entry zone relative to each other
- Color-coded by direction (green for long, red for short)
- Expandable card showing all confirmed structure elements (BOS, OB, FVG, IFVG+OB alignment)
- New York time clock showing active/pre-window/inactive status
- R:R calculation displayed for both TP1 and TP2

---

## 13. Configuration Reference

### Top-level sections in `config/config.yaml`

```yaml
brain:          # Brain server settings
worker:         # Default worker settings
redis:          # Message bus configuration
postgres:       # Database configuration
security:       # Authentication settings
analysis:       # Plugin configuration + CR 9AM
trading:        # Min profit, position size, slippage
strategies:     # Enable/disable each of 7 strategies
alerts:         # Alert channel configuration
monitoring:     # Prometheus settings
```

### Analysis plugin configuration

Every plugin supports these base fields:

```yaml
analysis:
  plugins:
    plugin_name:
      enabled: true/false      # Toggle the plugin
      weight:  0.15            # 0.0–1.0 contribution to signal
      params:                  # Plugin-specific parameters
        period: 14             # e.g., RSI period
```

### Per-context overrides

```yaml
analysis:
  # Exchange-level: applies to all pairs on this exchange
  exchanges:
    uniswap:
      plugins:
        gas_cost_plugin: { enabled: true, weight: 0.20 }

  # Pair-level: applies to this pair on all exchanges
  pairs:
    "DOGE/USDT":
      plugins:
        rsi:             { period: 7 }    # shorter period for volatile pairs
        sentiment:       { enabled: true, weight: 0.30 }

  # Context-level: most specific, applies only to this exact combination
  contexts:
    "binance:BTC/USDT":
      plugins:
        lstm_predictor:  { enabled: true }
```

---

## 14. Extending the System

### Add a new analysis plugin

```python
# analysis/plugins/my_indicator.py
from analysis.plugins.registry import AnalysisPlugin, register
from messaging.models import PluginResult

@register
class MyIndicatorPlugin(AnalysisPlugin):
    name = "my_indicator"
    enabled_by_default = True

    async def run(self, exchange, pair, prices, candles=None, extra=None):
        if len(prices) < 10:
            return None

        # Your analysis logic here
        score = compute_my_score(prices)

        return PluginResult(
            plugin=self.name,
            signal_score=score,          # 0.0–1.0
            weight=self._weight,
            data={"my_value": score},    # arbitrary data for dashboard/API
        )
```

Enable in config:
```yaml
analysis:
  plugins:
    my_indicator:
      enabled: true
      weight: 0.12
```

### Add a new arbitrage strategy

```python
# arbitrage/my_strategy.py
from arbitrage.base_strategy import BaseStrategy
from messaging.models import Opportunity, StrategyType

class MyStrategy(BaseStrategy):
    strategy_name = "my_strategy"

    async def _find_opportunities(self):
        # Scan for opportunities
        # Return list of Opportunity objects
        return []
```

Register in `brain/brain.py`:
```python
from arbitrage.my_strategy import MyStrategy
strat = MyStrategy(self.config)
self.scheduler.register("strategy.my_strategy", strat.scan)
```

### Add a new exchange worker

1. Create `worker/collectors/my_exchange_collector.py` following the pattern of `binance_collector.py`
2. Add environment variables to `.env.example`
3. Add a service to `docker/docker-compose.yml`
4. Enable in `config/config.yaml` under `workers`

### Add a new alert channel

```python
# alerts/my_alert.py
from messaging.models import Opportunity

class MyAlert:
    def __init__(self, config):
        self.config = config

    async def send(self, opp: Opportunity, message: str) -> None:
        # Send alert via your channel
        pass
```

Register in `alerts/alert_manager.py` `_build_channels()` method.

---

*ARBX v4.4.0.0 — For research and simulation use only.*  
*Always run in dry-run mode before considering any live deployment.*

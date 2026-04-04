# ARBX v4.4

A professional, distributed, modular crypto arbitrage research platform.

> **⚠️ Dry-run by default.** All trading is simulated. No real funds move without explicitly setting `dry_run: false` and connecting live credentials.

---

## Architecture

```
                    ┌─────────────────────────┐
                    │     React Dashboard      │
                    │   Vite · Tailwind · WS   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    FastAPI Brain API     │
                    │   REST + 3 WebSockets    │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │           Brain (Central)            │
              │  Analysis · Fleet · Security · State │
              └──────────────────┬──────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │        Redis Streams Bus             │
              │  prices · candles · heartbeats ·     │
              │  orders · balances · events          │
              └──┬──────────┬──────────┬────────────┘
                 │          │          │
         ┌───────▼──┐ ┌────▼────┐ ┌──▼──────────┐
         │ Worker   │ │ Worker  │ │ Worker      │
         │ Binance  │ │ Kraken  │ │ Uniswap     │
         │ Machine A│ │Machine B│ │ Machine C   │
         └──────────┘ └─────────┘ └─────────────┘
```

**Key design principle:** The brain never connects to exchanges. All data arrives via the message bus from independent workers that can run on any machine, anywhere in the world.

---

## What's New since v2

| Feature | v1 | v2 |
|---|---|---|
| Architecture | Monolithic | Distributed workers |
| Data flow | Brain polls exchanges | Workers push via Redis Streams |
| Analysis | Global, shared | Per-(exchange × pair) context |
| Plugins | Hardcoded | Self-registering, config-toggleable |
| Security | None | mTLS + HMAC + nonce/replay protection |
| Fleet management | None | Heartbeat monitoring, auto-failover |
| IP block recovery | Manual | Automatic worker respawn |
| 9AM CR Model | None | Full ICT model with BOS/OB/FVG |
| Workers | Local only | Any machine, any network |

---

## Quick Start

### Docker (recommended — one command)

```bash
git clone <your-repo>
cd arbx
cp config/.env.example config/.env
make docker-up
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Prometheus | http://localhost:9091 |
| Grafana | http://localhost:3001 |

### Local (no Docker)

```bash
# Terminal 1 — Redis (required)
docker run -p 6379:6379 redis:7-alpine

# Terminal 2 — Brain
make install
make brain

# Terminal 3 — Worker (one per exchange)
EXCHANGE=binance PAIRS=BTC/USDT,ETH/USDT make worker

# Terminal 4 — Dashboard
make frontend
```

---

## Project Structure

```
arbx/
├── brain/
│   ├── brain.py               # Main entry point
│   ├── security/
│   │   └── auth_manager.py    # mTLS, HMAC, permissions, revocation
│   ├── fleet/
│   │   └── monitor.py         # Heartbeat tracking, error classification, failover
│   ├── stream/
│   │   └── subscriber.py      # Consumes all worker streams
│   └── analysis/
├── worker/
│   └── worker.py              # Self-contained exchange worker
├── worker_manager/
│   └── manager.py             # Docker spawn daemon (one per machine)
├── messaging/
│   ├── bus.py                 # Redis Streams message bus
│   ├── models.py              # All shared dataclasses
│   └── logging.py             # Structured logger
├── analysis/
│   ├── context_engine.py      # Per-(exchange × pair) analysis contexts
│   └── plugins/
│       ├── registry.py        # Self-registering plugin system
│       └── cr_9am/
│           └── cr_plugin.py   # 9AM CR model (full ICT implementation)
├── storage/
│   └── market_state.py        # Unified in-memory market data store
├── api/
│   ├── main.py                # FastAPI factory
│   └── routes/                # 10 route modules
├── frontend/
│   └── src/
│       └── components/        # 11 React components
├── config/
│   ├── config.yaml            # Full configuration
│   ├── loader.py              # Typed Pydantic config loader
│   └── .env.example           # Secrets template
├── docker/
│   ├── docker-compose.yml     # 8 services
│   ├── nginx.conf
│   └── prometheus.yml
├── scripts/
│   ├── run_brain.py
│   ├── run_worker.py
│   ├── run_worker_manager.py
│   └── generate_worker.py     # Worker credential generator
└── tests/
    └── test_v2.py             # 18 tests, all passing
```

---

## Distributed Workers

Each worker is a self-contained Python process (or Docker container) that:
- Connects to ONE exchange
- Streams price ticks, candles, and orderbooks via Redis Streams
- Sends heartbeats every 5 seconds
- Receives and executes order commands from the brain
- Self-classifies errors (IP block, rate limit, overload)

### Deploy a worker anywhere

```bash
# On any machine with Redis access:
docker run arbitrage-worker:v4.4 \
  -e WORKER_ID=worker-binance-nyc \
  -e EXCHANGE=binance \
  -e PAIRS=BTC/USDT,ETH/USDT \
  -e REDIS_HOST=your.redis.host \
  -e WORKER_SECRET_KEY=<from generate_worker.py>
```

### Add a new worker type

```bash
make gen-worker ID=worker-coinbase-01 EXCHANGE=coinbase PAIRS='BTC/USDT ETH/USDT'
```

---

## Fleet Health Management

The brain automatically detects and responds to worker issues:

| Condition | Detection | Response |
|---|---|---|
| IP blocked | 403/418 in error | Spawn replacement on different machine |
| Rate limited | 429 in error | Spawn companion, split pairs |
| Overloaded | CPU >85% or RAM >800MB | Spawn companion, split pairs |
| Stale data | No ticks for 30s | Spawn parallel probe worker |
| Crashed | Heartbeat TTL expired | Respawn, avoid same machine |
| High latency | Latency >2000ms | Suggest relocating worker |

Typical recovery time: **5–15 seconds**, fully automated.

---

## Security

All worker↔brain communication is secured with multiple layers:

| Layer | Mechanism |
|---|---|
| Transport | mTLS (mutual TLS certificates) |
| Message integrity | HMAC-SHA256 per message |
| Replay protection | UUID nonce + 30s timestamp window |
| Registration | Challenge-response handshake |
| Permissions | Per-worker ACL (pairs, order execution, size limits) |
| Order privacy | Asymmetric encryption per worker |
| Anomaly detection | Price manipulation, DDoS, credential theft |

### Register a new worker

```bash
# Generate credentials
python scripts/generate_worker.py \
  --id worker-binance-07 \
  --exchange binance \
  --pairs BTC/USDT ETH/USDT \
  --expires 30

# Then register in brain via API:
POST /api/security/workers/register
```

### Revoke a compromised worker

```bash
POST /api/security/workers/{worker_id}/revoke
# Kills the worker process immediately
```

---

## 9AM CR Model (ICT Candle Range Theory)

A time-gated intraday analysis plugin that runs 09:00–10:00 NY time.

### How it works

```
08:00  → Mark 1H candle High/Low as HTF range (outer boundary)
09:00  → Mark 15M candle High/Low as LTF range (inner boundary)
09:00+ → Watch 1M for wick sweep of LTF high or low
         After sweep: look for BOS + Order Block + FVG
         Enter on confirmed FVG in discount/premium zone
         TP1 = opposite end of LTF range
         TP2 = opposite end of HTF range
         SL  = beyond sweep extreme
```

### Setup scoring

| Element | Score |
|---|---|
| Sweep confirmed | +0.20 |
| BOS confirmed | +0.20 |
| Order Block present | +0.15 |
| FVG confirmed (2nd candle) | +0.20 |
| IFVG + OB alignment | +0.10 |
| Price in discount/premium | +0.15 |

Minimum score to surface as signal: **0.55**

### Configure

```yaml
analysis:
  cr_9am:
    enabled: true
    timezone: "America/New_York"
    pairs: ["BTC/USDT", "ETH/USDT", "EUR/USD"]
    min_setup_score: 0.55
```

---

## Per-Context Analysis

Each `(exchange, pair)` combination gets its own independent analysis context with:
- Separate price history buffer
- Per-context plugin configuration
- Independent signal output

Config is resolved in priority order:
```
global defaults < exchange override < pair override < context override
```

Example — disable ARIMA for DOGE, enable gas plugin for Uniswap:

```yaml
analysis:
  pairs:
    "DOGE/USDT":
      plugins:
        arima_predictor: { enabled: false }
        sentiment: { enabled: true, weight: 0.30 }
  exchanges:
    uniswap:
      plugins:
        gas_cost_plugin: { enabled: true, weight: 0.20 }
```

---

## Adding a New Analysis Plugin

```python
# analysis/plugins/my_plugin.py
from analysis.plugins.registry import AnalysisPlugin, register, PluginResult

@register
class MyPlugin(AnalysisPlugin):
    name = "my_plugin"

    async def run(self, exchange, pair, prices, candles=None, extra=None):
        score = compute_something(prices)
        return PluginResult(
            plugin=self.name,
            signal_score=score,
            weight=self._weight,
            data={"value": score},
        )
```

Then enable it in config:
```yaml
analysis:
  plugins:
    my_plugin:
      enabled: true
      weight: 0.15
```

That's it. No other files need to change.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/system/status` | Brain health + market summary |
| GET | `/api/fleet/workers` | All workers with status |
| GET | `/api/fleet/workers/{id}` | Single worker detail |
| GET | `/api/fleet/events` | Fleet event log |
| GET | `/api/fleet/coverage` | Pair coverage map |
| POST | `/api/fleet/workers/{id}/kill` | Kill a worker |
| POST | `/api/fleet/workers/{id}/restart` | Restart a worker |
| POST | `/api/workers/spawn` | Spawn a new worker |
| GET | `/api/analysis/contexts` | All analysis contexts |
| GET | `/api/analysis/signals` | All current signals |
| GET | `/api/market/prices` | Latest prices from all workers |
| GET | `/api/market/spreads` | Cross-exchange spread table |
| GET | `/api/balances` | Fund balances per exchange |
| GET | `/api/cr/signals` | Today's 9AM CR setups |
| GET | `/api/security/workers` | Registered workers + rejections |
| POST | `/api/security/workers/register` | Register new worker |
| POST | `/api/security/workers/{id}/revoke` | Revoke worker credentials |
| WS | `/ws/market` | Live price stream |
| WS | `/ws/fleet` | Live fleet health stream |
| WS | `/ws/signals` | Live analysis + CR signals |

---

## Running Tests

```bash
make test
# 18 tests — config, models, auth, fleet, CR model, context engine
```

---

## Disclaimer

This platform is for **research and simulation only**. Crypto arbitrage involves significant risk including execution delays, IP bans, exchange API failures, gas cost volatility, regulatory risk, and capital loss. Always run in dry-run mode for extended periods before considering live deployment. The authors accept no responsibility for financial losses.

# ARBX

### Distributed Arbitrage Intelligence — Scan Every Market. Miss Nothing.

<p align="center">
  <img src="https://img.shields.io/badge/version-2.0.0-22c55e?style=flat-square" alt="Version" />
  <img src="https://img.shields.io/badge/python-3.11%2B-3b82f6?style=flat-square" alt="Python" />
  <img src="https://img.shields.io/badge/react-18-61dafb?style=flat-square" alt="React" />
  <img src="https://img.shields.io/badge/redis-streams-dc382d?style=flat-square" alt="Redis" />
  <img src="https://img.shields.io/badge/dry--run-default-f59e0b?style=flat-square" alt="Dry Run" />
  <img src="https://img.shields.io/badge/tests-18%20passing-22c55e?style=flat-square" alt="Tests" />
  <img src="https://img.shields.io/badge/license-MIT-6b7280?style=flat-square" alt="License" />
</p>

---

ARBX is a professional, distributed crypto arbitrage research platform built around a single principle: **the brain should never talk to exchanges — workers should.**

A fleet of lightweight worker processes streams real-time price data from centralized exchanges, decentralized protocols, and forex sources into a central brain via Redis Streams. The brain runs market analysis, scans for opportunities across seven arbitrage strategies, monitors fleet health, and serves a live dashboard — without ever touching an exchange API directly.

Workers can run on any machine, anywhere in the world. When one gets IP-blocked, ARBX detects it in under 5 seconds and spawns a replacement on a different machine automatically.

---

## What ARBX Does

```
Workers (any machine, any network)            Brain (central node)
┌─────────────────┐                          ┌──────────────────────────────────┐
│ worker-binance  │──┐                        │  7 Arbitrage Strategies          │
│ worker-kraken   │──┤  Redis Streams  ──────▶│  Per-Context Analysis Engine     │
│ worker-uniswap  │──┤  (price ticks,         │  9AM CR Model (ICT)              │
│ worker-pancake  │──┘   candles,             │  Fleet Health Monitor            │
│ worker-forex    │──    heartbeats)          │  Balance Manager + Rebalancer    │
└─────────────────┘                          │  Dry-Run Trading Simulator       │
                                             │  Alert System (5 channels)       │
                                             │  Prometheus Metrics              │
                                             └──────────────┬───────────────────┘
                                                            │
                                             ┌──────────────▼───────────────────┐
                                             │     React Dashboard              │
                                             │  Fleet · CR Model · Analysis ·   │
                                             │  Coverage · Security · Events    │
                                             └──────────────────────────────────┘
```

---

## Key Features

**Distributed by design**
Workers are self-contained processes — one per exchange. Deploy them on any machine, in any datacenter, close to any exchange. Add or remove workers at runtime without restarting anything.

**Automatic failover**
The fleet monitor tracks every worker's heartbeat, latency, error type, and data freshness. IP block, rate limit, crash, or overload — ARBX detects the condition and spawns a replacement worker on a different machine in seconds.

**Seven arbitrage strategies**
Spatial (cross-exchange), triangular (within-exchange 3-leg cycles), DEX vs CEX, cross-chain, flash loan simulation, FX (regional fiat spreads), and multi-country (Kimchi premium and regional demand). All run independently, all scored on the same 0.0–1.0 scale.

**9AM CR Model — ICT Candle Range Theory**
A full implementation of the ICT intraday setup model. Marks the 8AM 1H range (HTF) and 9AM 15M range (LTF), monitors 1M candles for a sweep, detects Break of Structure + Order Block + Fair Value Gap, and produces a complete trade plan with entry zone, TP1, TP2, stop loss, and R:R ratios. Active 9:00–10:00 AM New York time.

**Per-context market analysis**
Each exchange × pair combination gets its own independent analysis context: separate price history, independently configured plugins, and its own signal output. BTC/USDT on Binance and BTC/USDT on Kraken are analyzed in complete isolation — no signal blending.

**Modular plugin architecture**
Analysis plugins self-register at import time. Adding a new indicator requires creating one file and one config entry — nothing else changes. Every plugin is individually toggleable per-pair, per-exchange, or globally. Ships with RSI, MACD, Bollinger Bands, pattern detection, AR(1) price prediction, and an optional LSTM model.

**Multi-layer security**
Workers communicating over the internet authenticate with the brain using mTLS certificates, per-message HMAC-SHA256 signatures, nonce + timestamp replay protection, per-worker permission scopes, and automatic credential revocation. A compromised worker can be killed and blacklisted in one API call.

**Dry-run by default**
Every trade is simulated. The simulator accounts for exchange fees, slippage, gas costs, and orderbook depth. No real funds move without explicitly setting `dry_run: false` and connecting live API keys.

---

## Architecture at a Glance

| Component | Technology | Role |
|---|---|---|
| **Workers** | Python + CCXT + web3.py | Exchange connectivity, price streaming |
| **Message Bus** | Redis Streams | All brain↔worker communication |
| **Brain** | Python + asyncio | Analysis, strategies, fleet management, API |
| **Analysis** | Modular plugin system | Per-context market signals |
| **CR Model** | ICT methodology | Intraday 9AM setup detection |
| **API** | FastAPI + WebSocket | REST (19 routes) + 3 live streams |
| **Dashboard** | React + Vite + Tailwind | 9 panels, fully live |
| **Storage** | Redis + PostgreSQL | Cache + persistence |
| **Monitoring** | Prometheus + Grafana | Metrics and dashboards |
| **Deployment** | Docker Compose | One-command startup |

---

## Quick Start

```bash
git clone https://github.com/your-org/arbx.git
cd arbx
cp config/.env.example config/.env
make docker-up
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| API + Docs | http://localhost:8000/docs |
| Prometheus | http://localhost:9091 |
| Grafana | http://localhost:3001 |

No API keys needed to start — all collectors run in simulation mode and generate realistic prices until real keys are configured.

---

## Arbitrage Strategies

| Strategy | Mechanism | Typical Spread |
|---|---|---|
| **Spatial** | Same pair, different CEX | 0.1 – 2.0% |
| **Triangular** | 3-leg cycle within one exchange | 0.05 – 0.5% |
| **DEX** | CEX order book vs DEX pool price | 0.3 – 3.0% |
| **Cross-Chain** | Same asset across different blockchains | 0.2 – 1.5% |
| **Flash Loan** | Zero-capital DeFi cycle (simulation) | 0.1 – 1.0% net |
| **FX** | Regional fiat currency conversion spreads | 0.3 – 5.0% |
| **Multi-Country** | Kimchi premium, regional demand | 0.5 – 5.0% |

---

## Exchanges Supported

**Centralized (CEX)**
Binance · Kraken · Coinbase · Bybit

**Decentralized (DEX)**
Uniswap V3 · SushiSwap · PancakeSwap · Curve Finance

**Forex**
ECB · exchangerate.host · OpenExchangeRates
Pairs: USD/EUR · USD/JPY · USD/KRW · USD/TRY · USD/BRL

---

## Documentation

| Document | Description |
|---|---|
| [`docs/INSTALL_AND_DEPLOYMENT.md`](docs/INSTALL_AND_DEPLOYMENT.md) | Prerequisites, local setup, Docker, remote workers, production checklist, troubleshooting |
| [`docs/SYSTEM_DESCRIPTION.md`](docs/SYSTEM_DESCRIPTION.md) | Architecture, all modules explained, strategies, CR model, analysis plugins, security model, API reference |
| [`docs/V1_TO_V2_RELEASE_NOTES.md`](docs/V1_TO_V2_RELEASE_NOTES.md) | What changed from v1, new features, breaking changes, migration guide |

---

## Project Structure

```
arbx/
├── brain/                  Central analysis and orchestration
│   ├── security/           mTLS + HMAC authentication
│   ├── fleet/              Worker heartbeat monitoring + failover
│   └── stream/             Redis Streams consumer
├── worker/                 Self-contained exchange worker
├── worker_manager/         Docker spawn daemon (per machine)
├── messaging/              Redis Streams bus + shared models
├── analysis/
│   ├── context_engine.py   Per-(exchange × pair) analysis
│   └── plugins/
│       └── cr_9am/         9AM CR model (ICT)
├── arbitrage/              7 strategy modules
├── trading/                Dry-run simulator + balance manager
├── alerts/                 5 alert channels
├── storage/                Market state + Redis cache + PostgreSQL
├── api/                    FastAPI + WebSocket (19 routes)
├── frontend/               React + Vite + Tailwind dashboard
├── docker/                 Compose, nginx, Prometheus config
├── config/                 config.yaml + .env.example
├── scripts/                Brain, worker, manager entry points
└── tests/                  18 tests, all passing
```

---

## Requirements

- Python 3.11+
- Docker 24+ and Docker Compose 2.20+
- Redis 7+ (included in Docker Compose)
- PostgreSQL 16+ (included in Docker Compose)
- Node.js 20+ (local frontend development only)

---

## ⚠️ Disclaimer

ARBX is a **research and simulation platform**. All trading is simulated by default. Crypto arbitrage carries significant risk including execution delays, IP bans, exchange API failures, gas cost volatility, slippage, and capital loss. Always run in dry-run mode for an extended period before considering any live deployment. The authors accept no responsibility for financial losses.

---

<p align="center">
  <sub>ARBX v2.0.0 — Distributed Arbitrage Intelligence</sub>
</p>

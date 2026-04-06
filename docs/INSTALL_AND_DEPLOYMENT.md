# ARBX v4.4 — Install & Deployment Guide

> **Version:** 2.0.0  
> **Last updated:** March 2026  
> **Audience:** Developers, DevOps engineers, system administrators

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Repository Setup](#2-repository-setup)
3. [Configuration](#3-configuration)
4. [Local Development Setup](#4-local-development-setup)
5. [Docker Deployment (Recommended)](#5-docker-deployment-recommended)
6. [Deploying Workers on Remote Machines](#6-deploying-workers-on-remote-machines)
7. [Worker Registration & Security Setup](#7-worker-registration--security-setup)
8. [Production Deployment Checklist](#8-production-deployment-checklist)
9. [Service Management](#9-service-management)
10. [Monitoring & Observability](#10-monitoring--observability)
11. [Upgrading](#11-upgrading)
12. [Troubleshooting](#13-troubleshooting)

---

## 1. Prerequisites

### Required software

| Software | Minimum Version | Purpose |
|---|---|---|
| Python | 3.11+ | Brain, workers, worker manager |
| Docker | 24.0+ | Containerized deployment |
| Docker Compose | 2.20+ | Multi-service orchestration |
| Node.js | 20.0+ | Frontend build (local dev only) |
| Redis | 7.0+ | Message bus + opportunity cache |
| PostgreSQL | 16.0+ | Persistent storage |

### System requirements

**Brain server (central node)**

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 2 cores | 4+ cores |
| RAM | 2 GB | 8 GB |
| Disk | 20 GB | 100 GB |
| Network | 100 Mbps | 1 Gbps |
| OS | Ubuntu 22.04 | Ubuntu 24.04 / Debian 12 |

**Worker nodes (per machine)**

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 1 core | 2 cores |
| RAM | 512 MB | 1 GB |
| Disk | 5 GB | 10 GB |
| Network | 50 Mbps | 500 Mbps |

**Network requirements:**
- Workers must be able to reach Redis on the brain server (default port 6379)
- Workers must be able to reach their target exchange APIs (outbound HTTPS/WSS)
- Brain server needs port 8000 (API) and 9090 (metrics) accessible

---

## 2. Repository Setup

### Clone and enter directory

```bash
git clone https://github.com/your-org/arbitrage-engine-v2.git
cd arbitrage-engine-v2
```

### Verify directory structure

```bash
ls -la
# Expected output includes:
# brain/        worker/        worker_manager/
# analysis/     messaging/     config/
# frontend/     docker/        scripts/
# Makefile      README.md      requirements.txt
```

---

## 3. Configuration

### 3.1 Environment variables

```bash
# Copy the environment template
cp config/.env.example config/.env

# Edit with your values
nano config/.env
```

**Minimum required variables for dry-run mode:**

```bash
# PostgreSQL
POSTGRES_PASSWORD=your_secure_password_here

# Redis (only if not using localhost)
REDIS_HOST=localhost
```

**For live exchange data, add API keys:**

```bash
# Binance
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret

# Kraken
KRAKEN_API_KEY=your_kraken_api_key
KRAKEN_API_SECRET=your_kraken_api_secret

# Coinbase
COINBASE_API_KEY=your_coinbase_api_key
COINBASE_API_SECRET=your_coinbase_api_secret

# Bybit
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_api_secret
```

**For DEX/blockchain support:**

```bash
# Ethereum (Infura, Alchemy, or self-hosted node)
WEB3_PROVIDER_URL=https://mainnet.infura.io/v3/YOUR_PROJECT_ID

# Binance Smart Chain
BSC_PROVIDER_URL=https://bsc-dataseed.binance.org/
```

> **Note:** Without API keys, all collectors automatically switch to simulation mode, generating realistic randomized prices. The engine is fully functional in simulation mode.

### 3.2 Main configuration file

The primary configuration lives in `config/config.yaml`. Key sections:

```yaml
brain:
  dry_run: true          # KEEP TRUE until ready for live trading
  log_level: INFO

analysis:
  cr_9am:
    enabled: true
    timezone: "America/New_York"
    pairs: ["BTC/USDT", "ETH/USDT"]

trading:
  min_profit_percent: 0.5
  max_position_usd: 10000
```

**Important:** Always keep `dry_run: true` during initial setup. Change only after thorough testing.

### 3.3 Certificate setup (production only)

For production deployments, mTLS certificates provide transport security. For local development, certificate verification can be disabled:

```yaml
# config/config.yaml
security:
  require_mtls: false    # Set true in production
```

For production mTLS:

```bash
# Create certs directory
mkdir -p config/certs

# Generate CA certificate
openssl genrsa -out config/certs/ca.key 4096
openssl req -new -x509 -days 365 -key config/certs/ca.key \
    -out config/certs/ca.crt -subj "/CN=ArbitrageEngine-CA"

# Generate brain server certificate
openssl genrsa -out config/certs/brain.key 2048
openssl req -new -key config/certs/brain.key \
    -out config/certs/brain.csr -subj "/CN=brain"
openssl x509 -req -days 365 -in config/certs/brain.csr \
    -CA config/certs/ca.crt -CAkey config/certs/ca.key \
    -CAcreateserial -out config/certs/brain.crt
```

---

## 4. Local Development Setup

### 4.1 Python environment

```bash
# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate        # Windows

# Install dependencies
make install
# or: pip install -r requirements.txt

# Install dev dependencies
pip install pytest pytest-asyncio black ruff pytz
```

### 4.2 Start Redis (required)

```bash
# Option A: Docker (simplest)
docker run -d --name arb-redis -p 6379:6379 redis:7-alpine

# Option B: System package
sudo apt install redis-server
sudo systemctl start redis
```

### 4.3 Start PostgreSQL (optional for dry-run)

```bash
# Option A: Docker
docker run -d --name arb-postgres \
    -e POSTGRES_DB=arbitrage \
    -e POSTGRES_USER=arbitrage \
    -e POSTGRES_PASSWORD=arbitrage_secret \
    -p 5432:5432 postgres:16-alpine

# Option B: Disable postgres in config
# Set postgres.enabled: false in config/config.yaml
```

### 4.4 Run the brain

```bash
make brain
# or: python -m scripts.run_brain
```

Expected output:
```
2026-03-14 09:00:00 [INFO    ] brain.main                 ============================================================
2026-03-14 09:00:00 [INFO    ] brain.main                   ArbitrageEngine Brain v2.0.0
2026-03-14 09:00:00 [INFO    ] brain.main                   Dry-run  : ON
2026-03-14 09:00:00 [INFO    ] brain.main                   API      : 0.0.0.0:8000
2026-03-14 09:00:00 [INFO    ] brain.main                   Security : HMAC only
2026-03-14 09:00:00 [INFO    ] brain.main                   CR 9AM   : enabled
2026-03-14 09:00:00 [INFO    ] brain.main                 ============================================================
2026-03-14 09:00:00 [INFO    ] messaging.bus              MessageBus connected to Redis localhost:6379
```

### 4.5 Run a worker (separate terminal)

```bash
# Binance worker with simulation prices
EXCHANGE=binance PAIRS=BTC/USDT,ETH/USDT make worker

# Or with real API keys
EXCHANGE=binance \
PAIRS=BTC/USDT,ETH/USDT \
BINANCE_API_KEY=your_key \
BINANCE_API_SECRET=your_secret \
python -m scripts.run_worker
```

### 4.6 Run the frontend (separate terminal)

```bash
make frontend
# Dashboard available at http://localhost:5173
```

### 4.7 Run tests

```bash
make test
# Expected: 18 passed
```

---

## 5. Docker Deployment (Recommended)

Docker Compose is the recommended way to run the full system with a single command.

### 5.1 Quick start

```bash
# Copy environment file
cp config/.env.example config/.env

# Edit minimum required values
nano config/.env

# Start all services
make docker-up
```

This starts 8 services:

| Container | Port | Description |
|---|---|---|
| `arb-brain` | 8000, 9090 | Brain API + metrics |
| `arb-frontend` | 3000 | React dashboard |
| `arb-worker-binance` | — | Binance price collector |
| `arb-worker-kraken` | — | Kraken price collector |
| `arb-worker-uniswap` | — | Uniswap DEX collector |
| `arb-worker-manager` | — | Worker spawn daemon |
| `arb-redis` | 6379 | Message bus |
| `arb-postgres` | 5432 | Persistent storage |
| `arb-prometheus` | 9091 | Metrics scraper |
| `arb-grafana` | 3001 | Metrics dashboard |

### 5.2 Verify services are running

```bash
docker compose -f docker/docker-compose.yml ps
```

All services should show `running (healthy)`.

### 5.3 View logs

```bash
# Brain logs
make docker-logs

# Worker logs
make docker-worker-logs

# All logs
docker compose -f docker/docker-compose.yml logs -f

# Specific service
docker compose -f docker/docker-compose.yml logs -f worker-binance
```

### 5.4 Stop all services

```bash
make docker-down
```

### 5.5 Rebuild after code changes

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

### 5.6 Add more workers to Docker

Edit `docker/docker-compose.yml` and add a new service block:

```yaml
  worker-coinbase:
    build:
      context: .
      dockerfile: Dockerfile.worker
    container_name: arb-worker-coinbase
    networks: [arb-net]
    env_file: config/.env
    environment:
      WORKER_ID:    worker-coinbase-01
      EXCHANGE:     coinbase
      PAIRS:        BTC/USDT,ETH/USDT,SOL/USDT
      REDIS_HOST:   redis
      MACHINE_ID:   docker-local
    depends_on: [redis]
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
```

Then restart:

```bash
docker compose -f docker/docker-compose.yml up -d worker-coinbase
```

---

## 6. Deploying Workers on Remote Machines

Workers can run on any machine that has network access to the Redis server. This enables geographic distribution, IP rotation, and load balancing across machines.

### 6.1 Network requirements

The remote worker machine needs:
- Outbound access to Redis on brain server port 6379
- Outbound access to the target exchange APIs (HTTPS/WSS)
- No inbound ports required

> **Security note:** In production, Redis should be protected with authentication (`requirepass` in redis.conf) and the connection should be tunneled via SSH or VPN rather than exposed publicly.

### 6.2 Install worker on remote machine

```bash
# On the remote machine:

# Option A: Git clone (simplest)
git clone https://github.com/your-org/arbitrage-engine-v2.git
cd arbitrage-engine-v2
pip install -r requirements.txt

# Option B: Docker pull (recommended for production)
docker pull your-registry/arbitrage-worker:v4.4
```

### 6.3 Generate worker credentials

Run this on the brain machine:

```bash
python scripts/generate_worker.py \
    --id worker-binance-remote-01 \
    --exchange binance \
    --pairs BTC/USDT ETH/USDT SOL/USDT \
    --expires 30
```

This outputs a `.env.secret` file. Transfer it to the remote machine **securely** (not via unencrypted channels):

```bash
# Secure transfer via SCP
scp worker-binance-remote-01.env.secret user@remote-machine:/opt/workers/

# Then delete local copy
shred -u worker-binance-remote-01.env.secret
```

### 6.4 Run worker on remote machine

```bash
# Option A: Direct Python
cd arbitrage-engine-v2
source /opt/workers/worker-binance-remote-01.env.secret
REDIS_HOST=brain.yourdomain.com \
TICK_INTERVAL_MS=1500 \
python -m scripts.run_worker

# Option B: Docker
docker run -d \
    --name worker-binance-remote-01 \
    --restart unless-stopped \
    --memory 256m \
    --cpus 0.5 \
    --env-file /opt/workers/worker-binance-remote-01.env.secret \
    -e REDIS_HOST=brain.yourdomain.com \
    -e MACHINE_ID=remote-machine-nyc \
    arbitrage-worker:v4.4
```

### 6.5 Verify worker connected

On the brain machine:

```bash
# Check API
curl http://localhost:8000/api/fleet/workers | python3 -m json.tool

# Check dashboard
# Open http://localhost:3000 → Fleet Health tab
```

The new worker should appear with status `healthy` within 10 seconds.

### 6.6 Deploy Worker Manager on remote machine

The Worker Manager daemon enables automatic failover — it listens for spawn requests from the brain and can start new worker containers.

```bash
# On the remote machine:
REDIS_HOST=brain.yourdomain.com \
MACHINE_IP=remote-machine-nyc \
MAX_WORKERS=5 \
WORKER_IMAGE=arbitrage-worker:v4.4 \
python -m scripts.run_worker_manager
```

For Docker:

```bash
docker run -d \
    --name arb-worker-manager \
    --restart unless-stopped \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -e REDIS_HOST=brain.yourdomain.com \
    -e MACHINE_IP=remote-machine-nyc \
    -e MAX_WORKERS=5 \
    arbitrage-brain:v4.4 \
    python -m scripts.run_worker_manager
```

---

## 7. Worker Registration & Security Setup

### 7.1 Register a worker with the brain

Workers must be registered before the brain will accept their messages in secure mode.

```bash
# Via API (recommended)
curl -X POST http://localhost:8000/api/security/workers/register \
    -H "Content-Type: application/json" \
    -d '{
        "worker_id": "worker-binance-01",
        "exchange": "binance",
        "allowed_pairs": ["BTC/USDT", "ETH/USDT"],
        "can_execute_orders": false,
        "max_order_size_usd": 0,
        "expires_days": 30
    }'
```

The response includes the `secret_key` — store it immediately, it is shown only once:

```json
{
    "worker_id": "worker-binance-01",
    "secret_key": "a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5...",
    "message": "Store this secret key securely — it will not be shown again."
}
```

Set the key in the worker's environment before starting it:

```bash
WORKER_SECRET_KEY=a3f8b2c1d4e5f6a7b8c9d0e1f2a3b4c5...
```

### 7.2 Revoke a compromised worker

```bash
# Via API
curl -X POST http://localhost:8000/api/security/workers/worker-binance-01/revoke

# Via dashboard
# Security tab → Registered Workers → [Revoke] button
```

Revocation immediately kills the worker process and blacklists its credentials.

### 7.3 Security configuration summary

For local/development (insecure, simplest):

```yaml
security:
  enabled: false
```

For production (full security):

```yaml
security:
  enabled: true
  require_mtls: true
  nonce_ttl_seconds: 30
  heartbeat_ttl: 15
```

---

## 8. Production Deployment Checklist

Complete this checklist before going live:

### Infrastructure

- [ ] Redis secured with `requirepass` authentication
- [ ] Redis not exposed publicly (firewall or VPN-only access)
- [ ] PostgreSQL secured with strong password
- [ ] PostgreSQL not exposed publicly
- [ ] Brain API behind reverse proxy (nginx/Caddy) with TLS
- [ ] Firewall rules: only necessary ports open
- [ ] Regular database backups configured

### Configuration

- [ ] `dry_run: true` verified in `config/config.yaml`
- [ ] `config/.env` contains no placeholder values
- [ ] API keys stored in `.env`, never in `config.yaml`
- [ ] `.env` file has restricted permissions: `chmod 600 config/.env`
- [ ] mTLS certificates generated and configured
- [ ] All workers registered with the brain

### Testing

- [ ] `make test` passes: 18/18
- [ ] Brain starts cleanly: `make brain`
- [ ] At least one worker connects and appears in Fleet Health
- [ ] API responds: `curl http://localhost:8000/api/health`
- [ ] Dashboard loads at http://localhost:3000

### Monitoring

- [ ] Prometheus scraping: http://localhost:9091
- [ ] Grafana accessible: http://localhost:3001
- [ ] Alert channels configured (ntfy / Slack / email)
- [ ] Log aggregation configured if needed

### Before enabling live trading

- [ ] Engine has run in dry-run for at minimum 2 weeks
- [ ] Simulated trade P&L reviewed and understood
- [ ] Position size limits (`max_position_usd`) set conservatively
- [ ] `dry_run: false` change reviewed by multiple people
- [ ] Exchange API keys have trading permissions (not just read)
- [ ] Worker role set to `collector_and_executor`

---

## 9. Service Management

### Systemd services (Linux production)

Create a systemd unit for the brain:

```ini
# /etc/systemd/system/arb-brain.service

[Unit]
Description=ARBX v4.4 Brain
After=network.target redis.service postgresql.service

[Service]
Type=simple
User=arbitrage
WorkingDirectory=/opt/arbitrage-engine-v2
EnvironmentFile=/opt/arbitrage-engine-v2/config/.env
ExecStart=/opt/arbitrage-engine-v2/.venv/bin/python -m scripts.run_brain
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable arb-brain
sudo systemctl start arb-brain
sudo journalctl -fu arb-brain   # follow logs
```

Create a similar unit for each worker:

```ini
# /etc/systemd/system/arb-worker-binance.service

[Unit]
Description=ArbitrageEngine Worker — Binance
After=network.target

[Service]
Type=simple
User=arbitrage
WorkingDirectory=/opt/arbitrage-engine-v2
EnvironmentFile=/opt/arbitrage-engine-v2/config/.env
Environment=WORKER_ID=worker-binance-01
Environment=EXCHANGE=binance
Environment=PAIRS=BTC/USDT,ETH/USDT,SOL/USDT
ExecStart=/opt/arbitrage-engine-v2/.venv/bin/python -m scripts.run_worker
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Useful commands

```bash
# Status of all services
docker compose -f docker/docker-compose.yml ps

# Restart specific service
docker compose -f docker/docker-compose.yml restart brain

# Scale workers (add 2 more binance workers)
docker compose -f docker/docker-compose.yml up -d --scale worker-binance=3

# Execute command in running container
docker exec -it arb-brain python -c "import sys; print(sys.version)"

# Check Redis stream lengths
docker exec arb-redis redis-cli XLEN stream:prices
docker exec arb-redis redis-cli XLEN stream:heartbeats
```

---

## 10. Monitoring & Observability

### 10.1 Prometheus metrics

Available at `http://brain-host:9090/metrics`

Key metrics to monitor:

| Metric | Alert threshold |
|---|---|
| `arbitrage_opportunities_total` | < 1 per 10 min (strategies not finding anything) |
| `exchange_api_latency_seconds` | > 2.0 seconds (slow exchange API) |
| `balance_usd_total` | < min_balance (low funds) |
| Worker heartbeat gap | > 15 seconds = dead worker |

### 10.2 Grafana dashboards

Access at `http://localhost:3001` (default credentials: admin / admin)

Import the community ArbitrageEngine dashboard or create panels for:
- Opportunity detection rate per strategy
- Worker fleet health overview
- Exchange API latency histogram
- Balance distribution pie chart
- CR 9AM signal quality over time

### 10.3 Log aggregation (optional)

For production, ship logs to a central system:

```bash
# Using Docker logging driver (Loki/Grafana)
docker compose -f docker/docker-compose.yml \
    --log-driver=loki \
    --log-opt loki-url=http://loki:3100/loki/api/v1/push \
    up -d
```

### 10.4 Alerting

Configure alert channels in `config/config.yaml`:

```yaml
alerts:
  console: true
  ntfy_enabled: true
  ntfy_topic: "your-ntfy-topic"
  slack_enabled: true
  slack_webhook: "https://hooks.slack.com/services/..."
```

Alerts fire when:
- An opportunity meets the minimum profit threshold and score
- A worker gets IP blocked (with failover status)
- A worker crashes (with respawn status)
- Balance drops below minimum threshold

---

## 11. Upgrading

### Minor update (same major version)

```bash
git pull origin main

# Rebuild Docker images
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d

# Or for local:
pip install -r requirements.txt --upgrade
```

### Configuration migration

Check `config/config.yaml` against `config/config.yaml.example` after upgrading — new settings may have been added with their defaults.

### Database migrations

If the schema changed, run:

```bash
# The engine auto-creates tables on startup via SQLAlchemy
# For manual migration, connect to postgres:
docker exec -it arb-postgres psql -U arbitrage -d arbitrage
```

---

## 12. Troubleshooting

### Brain fails to connect to Redis

```
RuntimeError: MessageBus not connected
```

**Fix:**
```bash
# Verify Redis is running
docker ps | grep redis
# or
redis-cli ping   # should return PONG

# Check REDIS_HOST in config/.env
grep REDIS_HOST config/.env
```

### Worker not appearing in fleet

**Check 1:** Worker is running and connected to Redis:
```bash
docker logs arb-worker-binance | tail -20
```

**Check 2:** Same Redis instance:
```bash
# On worker machine
redis-cli -h $REDIS_HOST ping
```

**Check 3:** Security — worker may be rejected (check brain logs):
```bash
docker logs arb-brain | grep REJECTED
```

### API returns 503 or connection refused

```bash
# Check brain is running
docker ps | grep brain
curl http://localhost:8000/api/health
```

### Dashboard shows no data

The dashboard requires:
1. Brain running (`curl http://localhost:8000/api/health` returns `{"status":"ok"}`)
2. At least one worker connected (check Fleet Health tab)
3. Browser WebSocket support (modern browsers only)

If workers are connected but no prices show, check the Market Feed tab — data may take 30–60 seconds to populate analysis contexts.

### CR 9AM signals not appearing

The CR plugin is only active between 09:00 and 10:00 AM New York time. Outside this window, the plugin returns no signals by design.

Also verify the pair is in the `cr_9am.pairs` config list.

### Worker gets IP blocked

The fleet monitor detects this automatically (within 5 seconds) and spawns a replacement on a different machine (if a Worker Manager is running there).

To manually verify:
```bash
curl http://localhost:8000/api/fleet/workers | python3 -m json.tool
# Look for worker with "condition": "ip_block"
```

To manually spawn a replacement:
```bash
curl -X POST http://localhost:8000/workers/spawn \
    -H "Content-Type: application/json" \
    -d '{"exchange": "binance", "pairs": ["BTC/USDT"], "avoid_machine": "blocked-machine-ip"}'
```

### High memory usage on brain

The brain stores price history in-memory per context. If running many pairs across many exchanges, this grows. Reduce history size or increase available RAM. Default history is 500 ticks per context.

### Test failures

```bash
# Ensure test dependencies installed
pip install pytest pytest-asyncio pytz

# Run with verbose output
pytest tests/test_v2.py -v --tb=long

# Run single test
pytest tests/test_v2.py::test_auth_manager_register_and_verify -v
```

---

## Appendix A — Port Reference

| Port | Service | Protocol | Notes |
|---|---|---|---|
| 3000 | Frontend dashboard | HTTP | Nginx serving React build |
| 5173 | Frontend dev server | HTTP | Vite local dev only |
| 8000 | Brain API | HTTP/WS | FastAPI + WebSocket |
| 9090 | Brain metrics | HTTP | Prometheus scrape target |
| 9091 | Prometheus UI | HTTP | Metrics query interface |
| 3001 | Grafana | HTTP | Dashboard visualization |
| 6379 | Redis | TCP | Message bus — protect in production |
| 5432 | PostgreSQL | TCP | Database — protect in production |

---

## Appendix B — Environment Variable Reference

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | `arbitrage_secret` | PostgreSQL password |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `BINANCE_API_KEY` | _(empty)_ | Binance API key — enables live prices |
| `BINANCE_API_SECRET` | _(empty)_ | Binance API secret |
| `KRAKEN_API_KEY` | _(empty)_ | Kraken API key |
| `KRAKEN_API_SECRET` | _(empty)_ | Kraken API secret |
| `WEB3_PROVIDER_URL` | _(empty)_ | Ethereum RPC URL (Infura/Alchemy) |
| `BSC_PROVIDER_URL` | _(empty)_ | BSC RPC URL |
| `WORKER_ID` | Auto-generated | Unique worker identifier |
| `EXCHANGE` | `binance` | Exchange name for worker |
| `PAIRS` | `BTC/USDT,ETH/USDT` | Comma-separated pairs for worker |
| `WORKER_SECRET_KEY` | _(empty)_ | HMAC secret — from generate_worker.py |
| `TICK_INTERVAL_MS` | `2000` | Milliseconds between price fetches |
| `ROLE` | `collector_only` | Worker role: `collector_only` or `collector_and_executor` |
| `MACHINE_ID` | hostname | Machine identifier for fleet tracking |
| `IS_REPLACEMENT` | `false` | Whether worker is a failover replacement |
| `NTFY_TOPIC` | _(empty)_ | ntfy push notification topic |
| `SLACK_WEBHOOK_URL` | _(empty)_ | Slack incoming webhook URL |
| `GRAFANA_PASSWORD` | `admin` | Grafana admin password |

---

*ARBX v4.4.0.0 — For research and simulation use only.*

# ⛁ dockup

> **Automated database backup manager with Docker auto-discovery**

[![CI](https://github.com/yourorg/dockup/actions/workflows/ci.yml/badge.svg)](https://github.com/yourorg/dockup/actions)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ghcr.io%2Fyourorg%2Fdockup-blue)](https://ghcr.io/yourorg/dockup)

dockup watches your Docker socket, auto-discovers database containers, and runs scheduled backups — zero config needed if you use Docker labels.

```
┌──────────────────────────────────────────────────────┐
│  Docker Socket  →  Discovery  →  Scheduler           │
│                                     ↓                │
│  PostgreSQL ─────────────────► Backup Engine         │
│  MySQL       ─────────────────►  (worker pool)       │
│  MongoDB     ─────────────────►    ↓                 │
│  Redis       ─────────────────► Local / S3 Storage   │
│  InfluxDB    ─────────────────►    ↓                 │
│  ClickHouse  ─────────────────► Prometheus Metrics   │
│  Elasticsearch ───────────────► Notifications        │
└──────────────────────────────────────────────────────┘
```

---

## Features

- **Zero-config discovery** — attach labels to containers, dockup finds them automatically
- **8 database drivers** — PostgreSQL, MySQL, MariaDB, MongoDB, Redis, InfluxDB, ClickHouse, Elasticsearch
- **Async worker pool** — concurrent backups with configurable parallelism
- **Flexible storage** — local filesystem, AWS S3, or MinIO
- **Retention policies** — max count + max age, applied automatically after each backup
- **6 notification channels** — ntfy, Slack, Email, Webhook, PagerDuty, Microsoft Teams
- **Prometheus metrics** — 8 metrics, Grafana dashboard included
- **Zabbix integration** — HTTP agent endpoint + XML template
- **REST API** — JWT-authenticated, RBAC (admin / operator / viewer)
- **Web UI** — built-in dashboard, no extra services needed
- **Helm chart** — production-ready Kubernetes deployment

---

## Quick Start

```bash
# Pull and run
docker run -d \
  --name dockup \
  -p 8080:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /backups:/backups \
  -e DOCKUP_API_JWT_SECRET="your-secret-here" \
  ghcr.io/yourorg/dockup:latest

# Open the UI
open http://localhost:8080
```

### With docker-compose

```bash
git clone https://github.com/yourorg/dockup
cd dockup
docker compose -f examples/compose/docker-compose.yml up -d
```

---

## Docker Labels

Add these labels to any database container and dockup will back it up automatically:

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16
    labels:
      dockup.enable: "true"       # required
      dockup.type: postgres       # postgres|mysql|mariadb|mongodb|redis|influxdb|clickhouse|elasticsearch
      dockup.username: myuser
      dockup.password: mypass
      dockup.database: mydb
      dockup.schedule: "0 2 * * *"      # cron or @daily/@hourly/@weekly/@monthly
      dockup.retention.days: "14"        # keep backups for 14 days
      dockup.host: "127.0.0.1"           # override host (default: 127.0.0.1)
      dockup.port: "5432"                # override port
```

**Supported schedule formats:**
| Format | Meaning |
|--------|---------|
| `@hourly` | Every hour |
| `@daily` | Every day at 02:00 |
| `@midnight` | Every day at 00:00 |
| `@weekly` | Every Sunday at 02:00 |
| `@monthly` | 1st of month at 02:00 |
| `0 2 * * *` | Standard cron expression |

---

## Installation

### Docker (recommended)

```bash
docker pull ghcr.io/yourorg/dockup:latest
```

### Python

```bash
pip install dockup
dockup serve
```

### Kubernetes (Helm)

```bash
helm repo add dockup https://yourorg.github.io/dockup
helm install dockup dockup/dockup \
  --set config.jwtSecret="your-secret" \
  --set storage.type=s3 \
  --set storage.s3.bucket=my-backups
```

---

## Configuration

All settings can be provided as environment variables (prefix `DOCKUP_`) or in a YAML file at `/etc/dockup/dockup.yaml`.

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKUP_API_PORT` | `8080` | HTTP server port |
| `DOCKUP_API_JWT_SECRET` | *(required)* | JWT signing secret |
| `DOCKUP_API_JWT_EXPIRE_MINUTES` | `480` | Token expiry in minutes |
| `DOCKUP_LOG_LEVEL` | `info` | Log level (debug/info/warning/error) |
| `DOCKUP_LOG_FORMAT` | `json` | Log format (json/console) |

### Backup Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKUP_BACKUP_OUTPUT_DIR` | `/backups` | Local backup directory |
| `DOCKUP_BACKUP_WORKER_COUNT` | `4` | Concurrent backup workers |
| `DOCKUP_BACKUP_TIMEOUT_SECONDS` | `1800` | Max backup duration |
| `DOCKUP_BACKUP_RETENTION_MAX_COUNT` | `7` | Max backups per target |
| `DOCKUP_BACKUP_RETENTION_MAX_AGE_HOURS` | `168` | Max backup age (hours) |

### Storage Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKUP_STORAGE_TYPE` | `local` | Storage backend (local/s3/minio) |
| `DOCKUP_STORAGE_S3_BUCKET` | — | S3 bucket name |
| `DOCKUP_STORAGE_S3_REGION` | `us-east-1` | S3 region |
| `DOCKUP_STORAGE_S3_ENDPOINT_URL` | — | Custom endpoint (MinIO) |
| `DOCKUP_STORAGE_S3_ACCESS_KEY` | — | AWS/MinIO access key |
| `DOCKUP_STORAGE_S3_SECRET_KEY` | — | AWS/MinIO secret key |

### Discovery Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKUP_DISCOVERY_DOCKER_SOCKET` | `unix:///var/run/docker.sock` | Docker socket |
| `DOCKUP_DISCOVERY_SCAN_INTERVAL_SECONDS` | `60` | Re-scan interval |
| `DOCKUP_DISCOVERY_LABEL_PREFIX` | `dockup` | Container label prefix |

### Notification Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKUP_NOTIFY_SLACK_ENABLED` | `false` | Enable Slack |
| `DOCKUP_NOTIFY_SLACK_WEBHOOK_URL` | — | Slack webhook URL |
| `DOCKUP_NOTIFY_NTFY_ENABLED` | `false` | Enable ntfy |
| `DOCKUP_NOTIFY_NTFY_URL` | `https://ntfy.sh` | ntfy server URL |
| `DOCKUP_NOTIFY_NTFY_TOPIC` | `dockup-alerts` | ntfy topic |
| `DOCKUP_NOTIFY_EMAIL_ENABLED` | `false` | Enable email |
| `DOCKUP_NOTIFY_EMAIL_SMTP_HOST` | — | SMTP server host |
| `DOCKUP_NOTIFY_PAGERDUTY_ENABLED` | `false` | Enable PagerDuty |
| `DOCKUP_NOTIFY_PAGERDUTY_INTEGRATION_KEY` | — | PagerDuty key |

---

## API Reference

All endpoints (except `/health`, `/ready`, `/metrics`) require a JWT bearer token.

```bash
# Login
TOKEN=$(curl -sX POST http://localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"dockup"}' | jq -r .access_token)

# List databases
curl -H "Authorization: $TOKEN" http://localhost:8080/api/v1/databases

# Trigger backup
curl -sX POST -H "Authorization: $TOKEN" \
  http://localhost:8080/api/v1/backup/<target-id>

# View history
curl -H "Authorization: $TOKEN" http://localhost:8080/api/v1/history

# System status
curl -H "Authorization: $TOKEN" http://localhost:8080/api/v1/status
```

Full OpenAPI spec at `http://localhost:8080/docs`.

### RBAC Roles

| Role | List DBs | View History | Trigger Backup | Update Retention |
|------|----------|--------------|----------------|-----------------|
| `viewer` | ✓ | ✓ | ✗ | ✗ |
| `operator` | ✓ | ✓ | ✓ | ✗ |
| `admin` | ✓ | ✓ | ✓ | ✓ |

---

## CLI

```bash
# Start server
dockup serve --host 0.0.0.0 --port 8080

# Login (saves token to .dockup_token)
dockup login

# List discovered databases
dockup list

# Trigger backup by name or ID
dockup backup my-postgres-container

# View history
dockup history --limit 50

# System status
dockup status
```

---

## Metrics

Prometheus metrics are exposed at `/metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `dockup_jobs_total` | Counter | Total backup jobs (by db_type, target, status) |
| `dockup_jobs_failed_total` | Counter | Failed backup jobs |
| `dockup_job_duration_seconds` | Histogram | Backup duration |
| `dockup_backup_size_bytes` | Gauge | Last successful backup size |
| `dockup_last_success_timestamp` | Gauge | Last success Unix timestamp |
| `dockup_discovered_databases` | Gauge | Discovered target count |
| `dockup_active_workers` | Gauge | Worker pool size |
| `dockup_queue_depth` | Gauge | Pending jobs in queue |

---

## Zabbix

Import `docs/zabbix/dockup-template.xml` into Zabbix 6.4+.  
Configure a Zabbix host pointing to `http://<dockup-host>:8080/zabbix`.

The template includes:
- Items for all 8 core metrics
- Triggers for backup failures and queue buildup
- Discovery rules for database targets

---

## Supported Databases

| Database | Driver Tool | Notes |
|----------|------------|-------|
| PostgreSQL | `pg_dump` | Custom format (compressed) |
| MySQL | `mysqldump` | With routines, triggers, events |
| MariaDB | `mysqldump` | Same as MySQL |
| MongoDB | `mongodump` | Archive format with gzip |
| Redis | `redis-cli BGSAVE` | RDB snapshot + gzip |
| InfluxDB | `influx backup` | Tarball of backup directory |
| ClickHouse | `clickhouse-client` | SQL dump |
| Elasticsearch | `elasticdump` | JSON export |

---

## Development

```bash
# Clone and install dev dependencies
git clone https://github.com/yourorg/dockup
cd dockup
pip install -e ".[dev]"
pre-commit install

# Run tests
pytest

# Lint
ruff check dockup/
mypy dockup/

# Format
black dockup/

# Run locally (console logging)
DOCKUP_LOG_FORMAT=console DOCKUP_API_JWT_SECRET=dev dockup serve
```

### Project Structure

```
dockup/
├── dockup/
│   ├── api/app.py            FastAPI application + JWT auth + RBAC
│   ├── backup/engine.py      Async worker pool + job lifecycle
│   ├── cli.py                Typer CLI (serve, login, list, backup, history, status)
│   ├── config.py             Pydantic-settings + env var configuration
│   ├── discovery/manager.py  Docker socket + env target discovery
│   ├── drivers/drivers.py    DB backup drivers (8 supported types)
│   ├── logging_config.py     structlog JSON/console logging
│   ├── main.py               Async entrypoint
│   ├── metrics/collector.py  Prometheus metrics (8 metrics)
│   ├── models.py             Pydantic data models
│   ├── notifications/manager.py  6 notification channels
│   ├── scheduler/scheduler.py    APScheduler cron scheduling
│   ├── storage/backend.py    Local + S3/MinIO storage
│   └── web/ui.py             Embedded single-file Web UI
├── docs/                     OpenAPI spec, Grafana dashboard, Zabbix template
├── deploy/helm/              Kubernetes Helm chart
├── examples/compose/         docker-compose full-stack example
├── tests/                    pytest test suite
├── Dockerfile                Multi-stage Alpine build
├── pyproject.toml            Modern Python packaging
└── .github/workflows/ci.yml  CI/CD pipeline
```

---

## License

MIT — see [LICENSE](LICENSE).

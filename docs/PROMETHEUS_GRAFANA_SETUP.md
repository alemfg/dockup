# ARBX Monitoring Setup Guide

ARBX v3.4 ships a built-in Prometheus metrics exporter.
Prometheus and Grafana are **not** included in Docker Compose — you connect
your own existing servers instead.

---

## 1. What ARBX exposes

The brain process starts an HTTP metrics server alongside the API.
Default port: **9090** (set `BRAIN_METRICS_PORT` in `config/.env` to change it).

```
http://<your-arbx-host>:9090/metrics   ← Prometheus scrape target
http://<your-arbx-host>:9090/health    ← Returns {"status":"ok"}
```

The `/metrics` endpoint returns all ARBX metrics in standard Prometheus
text exposition format on every scrape. No authentication is required
(add a reverse proxy with basic auth if you need to restrict access).

---

## 2. Metric reference

### Brain
| Metric | Type | Description |
|--------|------|-------------|
| `arbx_brain_up` | Gauge | 1 when brain is running |
| `arbx_brain_uptime_seconds` | Gauge | Seconds since brain started |
| `arbx_brain_trading_info` | Info | Labels: `mode`, `version`, `dry_run` |

### Workers
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `arbx_worker_status` | Gauge | `worker_id`, `exchange`, `machine` | 1=healthy, 0.5=degraded, 0=dead |
| `arbx_worker_latency_ms` | Gauge | `worker_id`, `exchange` | Avg price fetch latency |
| `arbx_worker_ticks_per_minute` | Gauge | `worker_id`, `exchange` | Ticks published last 60s |
| `arbx_worker_errors_total` | Counter | `worker_id`, `exchange`, `condition` | Total errors |
| `arbx_worker_memory_mb` | Gauge | `worker_id`, `exchange` | Process memory |
| `arbx_workers_total` | Gauge | — | Total registered workers |
| `arbx_workers_healthy` | Gauge | — | Workers with status=healthy |
| `arbx_workers_dead` | Gauge | — | Workers with status=dead |
| `arbx_workers_blocked` | Gauge | — | Workers blocked/rate-limited |

### Market
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `arbx_market_price_contexts` | Gauge | — | Active exchange×pair contexts |
| `arbx_market_stale_pairs` | Gauge | — | Pairs not updated in >30s |
| `arbx_market_pair_price` | Gauge | `exchange`, `pair` | Latest price |
| `arbx_market_spread_pct` | Gauge | `pair` | Cross-exchange spread % |
| `arbx_market_total_balance_usd` | Gauge | — | Total balance across exchanges |

### Signals & Analysis
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `arbx_signal_score` | Gauge | `exchange`, `pair` | Latest composite signal score (0–1) |
| `arbx_signals_total` | Counter | `exchange`, `pair`, `confidence` | Total signals produced |
| `arbx_cr_setups_active` | Gauge | — | Active CR 9AM setups today |
| `arbx_graph_paths_found` | Gauge | — | Profitable graph arb paths in last scan |
| `arbx_graph_best_profit_pct` | Gauge | — | Best graph path net profit % |

### Orders & Positions
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `arbx_orders_total` | Counter | `trading_mode`, `source`, `exchange` | Orders emitted |
| `arbx_orders_blocked_total` | Counter | `reason_type` | Orders blocked by risk manager |
| `arbx_orders_open` | Gauge | — | Currently open/pending orders |
| `arbx_order_execution_ms` | Histogram | `exchange` | Order execution time |
| `arbx_order_slippage_pct` | Histogram | `exchange` | Order slippage |
| `arbx_positions_open` | Gauge | — | Open positions count |
| `arbx_position_unrealised_pnl_usd` | Gauge | `position_id`, `pair`, `exchange` | Unrealised P&L |

### P&L
| Metric | Type | Description |
|--------|------|-------------|
| `arbx_pnl_realised_total_usd` | Gauge | Total realised P&L |
| `arbx_pnl_daily_usd` | Gauge | Today's realised P&L |
| `arbx_trades_win_rate_pct` | Gauge | Win rate % across all closed trades |
| `arbx_trades_total` | Gauge | Total closed trades |

### Risk
| Metric | Type | Description |
|--------|------|-------------|
| `arbx_risk_daily_loss_usd` | Gauge | Loss accumulated today |
| `arbx_risk_daily_loss_limit_usd` | Gauge | Configured daily loss limit |
| `arbx_risk_drawdown_pct` | Gauge | Current drawdown from peak balance |
| `arbx_risk_consecutive_losses` | Gauge | Current consecutive loss streak |
| `arbx_risk_halted` | Gauge | 1 if system is halted, 0 otherwise |

---

## 3. Configure your Prometheus server

Open your Prometheus server's `prometheus.yml` and add the job under `scrape_configs`.
A ready-made example is in `docker/prometheus.yml`.

```yaml
scrape_configs:

  - job_name: "arbx_brain"
    scrape_interval: 15s
    scrape_timeout:  10s
    static_configs:
      - targets: ["<ARBX_HOST>:9090"]
        labels:
          environment: "production"
          service:     "arbx-brain"
    metrics_path: "/metrics"
```

Replace `<ARBX_HOST>` with:
- The Docker host IP if brain runs in Docker (e.g. `192.168.1.10`)
- `localhost` if Prometheus is on the same machine as brain
- A hostname if you have DNS set up

After editing, reload Prometheus:
```bash
curl -X POST http://localhost:9090/-/reload
# or
kill -HUP $(pidof prometheus)
```

Verify the target is UP in Prometheus UI:
`http://<your-prometheus>:9090/targets` → look for `arbx_brain` with state=UP.

### Firewall
If Prometheus is on a different machine, open port 9090 on the ARBX host:
```bash
# UFW
ufw allow from <PROMETHEUS_IP> to any port 9090

# iptables
iptables -A INPUT -s <PROMETHEUS_IP> -p tcp --dport 9090 -j ACCEPT
```

### Changing the metrics port
Set `BRAIN_METRICS_PORT` in `config/.env`:
```env
BRAIN_METRICS_PORT=9191
```
Update your Prometheus target to match.

---

## 4. Import the Grafana dashboard

A pre-built Grafana dashboard is included at:
```
monitoring/grafana/arbx-dashboard.json
```

**To import:**

1. Open Grafana → **Dashboards** → **Import**
2. Click **Upload JSON file** and select `arbx-dashboard.json`
3. Select your Prometheus datasource from the dropdown
4. Click **Import**

The dashboard includes:

| Row | Panels |
|-----|--------|
| 🧠 Brain Health | Status, Uptime, Trading Mode, Balance, Risk Halt, Open Positions, P&L, Win Rate |
| 🖥 Workers | Total/Healthy/Dead stats, Latency time series, Ticks/min time series, Worker status table |
| 📊 Market | Price contexts, Stale pairs, Top spreads, BTC/USDT and ETH/USDT price charts |
| 💹 P&L & Risk | Cumulative P&L, Daily loss gauge, Drawdown gauge, Unrealised P&L, Graph arb paths |
| ⚡ Orders & Signals | Signal scores, Active CR setups, Open orders, Consecutive losses |

Dashboard auto-refreshes every **15 seconds**.

### Recommended Grafana alerts

Set these up in Grafana → Alerting → Alert rules:

```
arbx_risk_halted == 1
  → "ARBX system halted — check risk manager"

arbx_workers_dead > 0
  → "{{$labels.worker_id}} is dead on {{$labels.exchange}}"

arbx_market_stale_pairs > 3
  → "More than 3 pairs are stale — workers may be degraded"

arbx_risk_drawdown_pct > 7
  → "Drawdown at {{$value}}% — approaching limit"

arbx_brain_up == 0
  → "ARBX brain is down"
```

---

## 5. Multiple environments

If you run both staging and production ARBX instances:

```yaml
scrape_configs:

  - job_name: "arbx_production"
    static_configs:
      - targets: ["prod-host:9090"]
        labels:
          environment: "production"

  - job_name: "arbx_staging"
    static_configs:
      - targets: ["staging-host:9090"]
        labels:
          environment: "staging"
```

Use the `environment` label in Grafana queries to split dashboards:
```promql
arbx_pnl_realised_total_usd{environment="production"}
```

---

## 6. Quick health check

Without Prometheus, you can check the metrics endpoint directly:

```bash
# Human-readable text
curl http://<ARBX_HOST>:9090/metrics

# Just the P&L
curl -s http://<ARBX_HOST>:9090/metrics | grep arbx_pnl

# Just worker status
curl -s http://<ARBX_HOST>:9090/metrics | grep arbx_worker_status

# Health check (returns {"status":"ok"})
curl http://<ARBX_HOST>:9090/health
```

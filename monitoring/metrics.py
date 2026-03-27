"""
ARBX Prometheus Metrics Exporter (v3.4)

Starts an HTTP server on BRAIN_METRICS_PORT (default 9090) that exposes
all ARBX metrics in Prometheus text format at /metrics.

Metric families:
  arbx_brain_*      — brain health, uptime, trading mode
  arbx_worker_*     — per-worker latency, ticks, status, error count
  arbx_market_*     — price contexts, stale pairs, spreads
  arbx_signal_*     — signal scores, confidence, CR setups
  arbx_order_*      — order counts by status/mode/source
  arbx_position_*   — open positions, unrealised P&L
  arbx_pnl_*        — realised P&L, win rate, daily loss
  arbx_risk_*       — circuit breaker gauges
  arbx_fleet_*      — fleet summary, dead workers, replacements
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from messaging.logging import get_logger

if TYPE_CHECKING:
    from brain.brain import Brain

logger = get_logger("monitoring.metrics")

# ─── Registry ────────────────────────────────────────────────────────────────
# Use a custom registry so we don't pollute the default one with process metrics
REGISTRY = CollectorRegistry(auto_describe=True)

# ─── Brain ───────────────────────────────────────────────────────────────────
brain_up = Gauge(
    "arbx_brain_up", "1 if brain is running, 0 otherwise",
    registry=REGISTRY,
)
brain_uptime = Gauge(
    "arbx_brain_uptime_seconds", "Brain process uptime in seconds",
    registry=REGISTRY,
)
brain_trading_mode = Info(
    "arbx_brain_trading", "Current trading mode and version",
    registry=REGISTRY,
)

# ─── Workers ─────────────────────────────────────────────────────────────────
worker_status = Gauge(
    "arbx_worker_status",
    "Worker status (1=healthy, 0.5=degraded, 0=dead/blocked)",
    ["worker_id", "exchange", "machine"],
    registry=REGISTRY,
)
worker_latency = Gauge(
    "arbx_worker_latency_ms",
    "Average price fetch latency in milliseconds",
    ["worker_id", "exchange"],
    registry=REGISTRY,
)
worker_ticks_per_min = Gauge(
    "arbx_worker_ticks_per_minute",
    "Price ticks published in the last 60 seconds",
    ["worker_id", "exchange"],
    registry=REGISTRY,
)
worker_error_count = Counter(
    "arbx_worker_errors_total",
    "Total error count since worker start",
    ["worker_id", "exchange", "condition"],
    registry=REGISTRY,
)
worker_memory_mb = Gauge(
    "arbx_worker_memory_mb",
    "Worker process memory in MB",
    ["worker_id", "exchange"],
    registry=REGISTRY,
)
workers_total = Gauge(
    "arbx_workers_total", "Total registered workers",
    registry=REGISTRY,
)
workers_healthy = Gauge(
    "arbx_workers_healthy", "Workers with status=healthy",
    registry=REGISTRY,
)
workers_dead = Gauge(
    "arbx_workers_dead", "Workers with status=dead",
    registry=REGISTRY,
)
workers_blocked = Gauge(
    "arbx_workers_blocked", "Workers with status=blocked/rate-limited",
    registry=REGISTRY,
)

# ─── Market ──────────────────────────────────────────────────────────────────
market_price_contexts = Gauge(
    "arbx_market_price_contexts",
    "Total active exchange×pair price contexts",
    registry=REGISTRY,
)
market_stale_pairs = Gauge(
    "arbx_market_stale_pairs",
    "Number of pairs with no price update in >30s",
    registry=REGISTRY,
)
market_pair_price = Gauge(
    "arbx_market_pair_price",
    "Latest price for a pair on an exchange",
    ["exchange", "pair"],
    registry=REGISTRY,
)
market_spread_pct = Gauge(
    "arbx_market_spread_pct",
    "Cross-exchange spread percentage for a pair",
    ["pair"],
    registry=REGISTRY,
)
market_total_usd = Gauge(
    "arbx_market_total_balance_usd",
    "Total balance in USD across all connected exchanges",
    registry=REGISTRY,
)

# ─── Signals ─────────────────────────────────────────────────────────────────
signals_produced = Counter(
    "arbx_signals_total",
    "Total analysis signals produced",
    ["exchange", "pair", "confidence"],
    registry=REGISTRY,
)
signal_score = Gauge(
    "arbx_signal_score",
    "Latest composite signal score (0.0–1.0)",
    ["exchange", "pair"],
    registry=REGISTRY,
)
cr_setups_active = Gauge(
    "arbx_cr_setups_active",
    "Number of active CR 9AM setups today",
    registry=REGISTRY,
)
graph_paths_found = Gauge(
    "arbx_graph_paths_found",
    "Number of profitable graph arbitrage paths in last scan",
    registry=REGISTRY,
)
graph_best_profit_pct = Gauge(
    "arbx_graph_best_profit_pct",
    "Net profit % of best current graph arbitrage path",
    registry=REGISTRY,
)

# ─── Orders ──────────────────────────────────────────────────────────────────
orders_total = Counter(
    "arbx_orders_total",
    "Total orders emitted by decision engine",
    ["trading_mode", "source", "exchange"],
    registry=REGISTRY,
)
orders_blocked = Counter(
    "arbx_orders_blocked_total",
    "Orders blocked by risk manager",
    ["reason_type"],
    registry=REGISTRY,
)
orders_open = Gauge(
    "arbx_orders_open",
    "Currently open/pending orders",
    registry=REGISTRY,
)
order_execution_time = Histogram(
    "arbx_order_execution_ms",
    "Order execution time in milliseconds",
    ["exchange"],
    buckets=[50, 100, 200, 500, 1000, 2000, 5000],
    registry=REGISTRY,
)
order_slippage_pct = Histogram(
    "arbx_order_slippage_pct",
    "Order slippage percentage (filled_price vs requested_price)",
    ["exchange"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
    registry=REGISTRY,
)

# ─── Positions & P&L ─────────────────────────────────────────────────────────
positions_open = Gauge(
    "arbx_positions_open",
    "Number of currently open positions",
    registry=REGISTRY,
)
position_unrealised_pnl = Gauge(
    "arbx_position_unrealised_pnl_usd",
    "Unrealised P&L in USD for an open position",
    ["position_id", "pair", "exchange"],
    registry=REGISTRY,
)
pnl_realised_total = Gauge(
    "arbx_pnl_realised_total_usd",
    "Total realised P&L across all closed trades",
    registry=REGISTRY,
)
pnl_daily = Gauge(
    "arbx_pnl_daily_usd",
    "Realised P&L for the current UTC day",
    registry=REGISTRY,
)
trades_win_rate = Gauge(
    "arbx_trades_win_rate_pct",
    "Win rate percentage across all closed trades",
    registry=REGISTRY,
)
trades_total = Gauge(
    "arbx_trades_total",
    "Total closed trades",
    registry=REGISTRY,
)

# ─── Risk ─────────────────────────────────────────────────────────────────────
risk_daily_loss = Gauge(
    "arbx_risk_daily_loss_usd",
    "Realised loss for the current UTC day",
    registry=REGISTRY,
)
risk_daily_loss_limit = Gauge(
    "arbx_risk_daily_loss_limit_usd",
    "Configured daily loss limit",
    registry=REGISTRY,
)
risk_drawdown_pct = Gauge(
    "arbx_risk_drawdown_pct",
    "Current drawdown from peak balance (%)",
    registry=REGISTRY,
)
risk_consecutive_losses = Gauge(
    "arbx_risk_consecutive_losses",
    "Current streak of consecutive losing trades",
    registry=REGISTRY,
)
risk_halted = Gauge(
    "arbx_risk_halted",
    "1 if risk manager has halted the system, 0 otherwise",
    registry=REGISTRY,
)

# ─── Collector ────────────────────────────────────────────────────────────────

class ARBXCollector:
    """
    Pulls live data from all brain subsystems and updates all Prometheus
    gauges. Called once per scrape by the HTTP handler.
    """

    def __init__(self, brain: "Brain", start_time: float):
        self._brain      = brain
        self._start_time = start_time

    def collect(self) -> None:
        brain = self._brain
        now   = time.time()

        # ── Brain ──────────────────────────────────────────────────────────
        brain_up.set(1)
        brain_uptime.set(now - self._start_time)
        brain_trading_mode.info({
            "mode":    brain.config.trading.mode.value,
            "version": brain.config.brain.version,
            "dry_run": str(brain.config.brain.dry_run),
        })

        # ── Workers ────────────────────────────────────────────────────────
        all_workers = brain.fleet_monitor.get_all_workers()
        status_map  = {"healthy": 1.0, "degraded": 0.5, "starting": 0.5,
                       "blocked": 0.0, "dead": 0.0, "overloaded": 0.3}
        n_healthy = n_dead = n_blocked = 0

        for w in all_workers:
            wid      = w.get("worker_id", "")
            exchange = w.get("exchange", "")
            machine  = w.get("machine", "")
            st       = w.get("status", "dead")
            cond     = w.get("condition", "none")

            worker_status.labels(wid, exchange, machine).set(status_map.get(st, 0))
            worker_latency.labels(wid, exchange).set(w.get("latency_ms", 0))
            worker_ticks_per_min.labels(wid, exchange).set(w.get("ticks_per_min", 0))
            worker_memory_mb.labels(wid, exchange).set(w.get("memory_mb", 0))

            if st == "healthy":   n_healthy += 1
            elif st == "dead":    n_dead    += 1
            elif st == "blocked": n_blocked += 1

        workers_total.set(len(all_workers))
        workers_healthy.set(n_healthy)
        workers_dead.set(n_dead)
        workers_blocked.set(n_blocked)

        # ── Market ─────────────────────────────────────────────────────────
        ms      = brain.market_state
        summary = ms.summary()
        market_price_contexts.set(summary.get("price_contexts", 0))
        market_stale_pairs.set(summary.get("stale_pairs", 0))
        market_total_usd.set(ms.get_total_usd())

        for entry in ms.get_all_prices():
            ex   = entry.get("exchange", "")
            pair = entry.get("pair", "")
            pr   = entry.get("price", 0.0)
            if ex and pair and pr:
                market_pair_price.labels(ex, pair).set(pr)

        # Cross-exchange spreads
        for pair in ms.get_all_pairs():
            prices = ms.get_prices_for_pair(pair)
            if len(prices) >= 2:
                vals   = list(prices.values())
                spread = ((max(vals) - min(vals)) / min(vals)) * 100
                market_spread_pct.labels(pair).set(round(spread, 4))

        # ── Signals ────────────────────────────────────────────────────────
        for sig in brain.context_engine.get_all_signals():
            ex   = sig.exchange
            pair = sig.pair
            conf = sig.confidence.value if hasattr(sig.confidence, "value") else str(sig.confidence)
            signal_score.labels(ex, pair).set(sig.signal_score)

        # CR setups
        from analysis.plugins.registry import get_plugin
        cr = get_plugin("cr_9am")
        if cr:
            cr_setups_active.set(len(cr.get_active_signals()))

        # Graph paths
        paths = brain._graph_paths
        graph_paths_found.set(len(paths))
        if paths:
            best = max((p.get("net_profit_pct", 0) for p in paths), default=0)
            graph_best_profit_pct.set(best)

        # ── Orders ─────────────────────────────────────────────────────────
        fin = brain.order_log.financial_summary()
        orders_open.set(fin.get("open", 0))
        pnl_realised_total.set(fin.get("total_pnl_usd", 0))
        trades_win_rate.set(fin.get("win_rate", 0))
        trades_total.set(fin.get("closed", 0))

        # Daily P&L
        daily = brain.order_log.daily_pnl()
        if daily:
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_entry = next((d for d in daily if d["date"] == today), None)
            pnl_daily.set(today_entry["pnl_usd"] if today_entry else 0.0)

        # ── Positions ──────────────────────────────────────────────────────
        open_pos = brain.position_tracker.get_open_positions()
        positions_open.set(len(open_pos))
        for pos in open_pos:
            position_unrealised_pnl.labels(
                pos.get("id", "")[:8], pos.get("pair", ""), pos.get("exchange", "")
            ).set(pos.get("pnl_usd", 0))

        # ── Risk ───────────────────────────────────────────────────────────
        rst = brain.risk_manager.status()
        risk_daily_loss.set(rst.get("daily_loss_usd", 0))
        risk_daily_loss_limit.set(rst.get("max_daily_loss_usd", 0))
        risk_drawdown_pct.set(rst.get("drawdown_pct", 0))
        risk_consecutive_losses.set(rst.get("consecutive_losses", 0))
        risk_halted.set(1 if rst.get("halted") else 0)


# ─── HTTP Server ─────────────────────────────────────────────────────────────

async def start_metrics_server(brain: "Brain", port: int) -> None:
    """
    Start a lightweight asyncio HTTP server exposing /metrics.
    Does not use Flask or any extra framework — pure asyncio.
    """
    from aiohttp import web

    start_time = time.time()
    collector  = ARBXCollector(brain, start_time)

    async def metrics_handler(request):
        collector.collect()
        body = generate_latest(REGISTRY)
        return web.Response(body=body, content_type=CONTENT_TYPE_LATEST)

    async def health_handler(request):
        return web.Response(text='{"status":"ok"}', content_type="application/json")

    app = web.Application()
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/health",  health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Prometheus metrics server started on :{port}/metrics")

    # Keep running until cancelled
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await runner.cleanup()

"""
Config Hot-Reload API (v4)
Reloads config.yaml from disk without restarting brain or workers.

Brain reload: re-reads config.yaml, applies new values to all live subsystems.
Worker reload: publishes a reload command to Redis so all workers re-read their env/config.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from messaging.logging import get_logger

router = APIRouter(tags=["Config"])
logger = get_logger("api.config")


@router.post("/config/reload/brain")
async def reload_brain_config(request: Request):
    """
    Reload brain config from config.yaml + env vars without restart.
    Updates: decision rules, risk limits, alert settings, CR plugin config,
    analysis plugin weights, trading mode. Does NOT change ports or Redis host
    (those require restart — they're baked into live connections).
    """
    brain = request.app.state.brain
    from config.loader import reload_config

    old_mode = brain.config.trading.mode
    new_cfg  = reload_config()

    # Re-apply to all live subsystems
    brain.config = new_cfg

    # Update decision engine rules
    brain.decision_engine._dcfg = new_cfg.decision
    brain.decision_engine._cfg  = new_cfg

    # Update risk manager limits
    brain.risk_manager._rcfg = new_cfg.risk
    brain.risk_manager._cfg  = new_cfg

    # Update context engine plugin config
    brain.context_engine._config = new_cfg.analysis.model_dump()

    # Re-apply CR plugin config if present
    from analysis.plugins.registry import get_plugin
    cr = get_plugin("cr_9am")
    if cr:
        cr_cfg = new_cfg.analysis.model_dump().get("cr_9am", {})
        cr.apply_config(cr_cfg)

    # Re-apply graph config to the live currency graph (fees, stale threshold)
    brain.currency_graph.update_config(new_cfg.graph)

    logger.warning(
        f"Brain config reloaded. "
        f"trading_mode: {old_mode} → {new_cfg.trading.mode}"
    )

    try:
        from events.event_bus import emit, Category, Level
        await emit(
            category = Category.SYSTEM,
            title    = "Brain config reloaded",
            detail   = (
                f"Mode: {old_mode} → {new_cfg.trading.mode} · "
                f"Algo: {new_cfg.graph.algorithm} · "
                f"Min profit: {new_cfg.graph.min_profit_pct}%"
            ),
            level    = Level.WARNING if old_mode != new_cfg.trading.mode else Level.INFO,
        )
    except Exception:
        pass

    return {
        "ok":           True,
        "message":      "Brain config reloaded from disk.",
        "trading_mode": new_cfg.trading.mode,
        "dry_run":      new_cfg.brain.dry_run,
        "graph": {
            "algorithm":      new_cfg.graph.algorithm,
            "max_hops":       new_cfg.graph.max_hops,
            "min_profit_pct": new_cfg.graph.min_profit_pct,
            "stale_edge_s":   new_cfg.graph.stale_edge_s,
            "fees_pct": {
                "binance":  new_cfg.graph.fee_binance_pct,
                "kraken":   new_cfg.graph.fee_kraken_pct,
                "bybit":    new_cfg.graph.fee_bybit_pct,
                "uniswap":  new_cfg.graph.fee_uniswap_pct,
            },
        },
        "note": "Ports and Redis connection settings require restart to change.",
    }


@router.post("/config/reload/workers")
async def reload_workers_config(request: Request):
    """
    Broadcast a reload command to all connected workers via Redis.
    Workers will re-read their environment variables and re-apply config.
    This does NOT restart workers — it sends them a soft reload signal.
    """
    brain = request.app.state.brain
    workers = brain.fleet_monitor.get_all_workers()

    await brain.bus.publish_worker_command({
        "command":   "reload_config",
        "worker_id": "",   # empty = broadcast to all
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    })

    logger.warning(f"Config reload broadcast to {len(workers)} workers")

    return {
        "ok":      True,
        "message": f"Reload command sent to {len(workers)} workers.",
        "workers": [w.get("worker_id") for w in workers],
    }


@router.get("/config/current")
async def get_current_config(request: Request):
    """Return the full active config (sanitised — no secrets)."""
    import os
    cfg = request.app.state.brain.config
    return {
        # ── Identity ──────────────────────────────────────────────────────────
        "version":            cfg.brain.version,
        "trading_mode":       cfg.trading.mode,
        "dry_run":            cfg.brain.dry_run,
        "log_level":          cfg.brain.log_level,

        # ── Ports (read-only — require restart) ───────────────────────────────
        "ports": {
            "brain_api":     cfg.ports.brain_api,
            "brain_metrics": cfg.ports.brain_metrics,
            "frontend":      cfg.ports.frontend,
            "redis":         cfg.ports.redis,
            "postgres":      cfg.ports.postgres,
        },

        # ── Workers ───────────────────────────────────────────────────────────
        "workers": {
            "exchanges":       cfg.workers.exchanges,
            "pairs_worker_size": cfg.workers.pairs_worker_size,
            "max_workers":     int(os.getenv("MAX_WORKERS", "50")),
            "tick_interval_ms": int(os.getenv("TICK_INTERVAL_MS", "2000")),
            "heartbeat_interval_s": int(os.getenv("HEARTBEAT_INTERVAL_S", "10")),
            "balance_interval_s": int(os.getenv("BALANCE_INTERVAL_S", "60")),
            "worker_image":    os.getenv("WORKER_IMAGE", "arbx-worker:latest"),
            "pairs_all_quote_filter": os.getenv("PAIRS_ALL_QUOTE_FILTER", "USDT,USDC,BTC,ETH"),
        },

        # ── Auto-spawner ──────────────────────────────────────────────────────
        "spawner": {
            "watch_interval_s":  int(os.getenv("EXCHANGES_WATCH_INTERVAL", "20")),
            "spawn_delay_s":     int(os.getenv("EXCHANGES_SPAWN_DELAY", "3")),
            "startup_wait_s":    int(os.getenv("EXCHANGES_STARTUP_WAIT", "3")),
        },

        # ── Analysis ──────────────────────────────────────────────────────────
        "analysis": {
            "analysis_pairs":        os.getenv("ANALYSIS_PAIRS", ""),
            "price_outlier_threshold": float(os.getenv("PRICE_OUTLIER_THRESHOLD", "10.0")),
        },

        # ── Graph arbitrage ───────────────────────────────────────────────────
        "graph": {
            **cfg.graph.model_dump(),
            "start_asset":   cfg.graph.start_asset,
            "hub_assets":    cfg.graph.hub_assets,
            "capital_usd":   cfg.graph.capital_usd,
            "dex_max_gas_usd": cfg.graph.dex_max_gas_usd,
        },

        # ── Decision engine ───────────────────────────────────────────────────
        "decision":   cfg.decision.model_dump(),

        # ── Risk manager ──────────────────────────────────────────────────────
        "risk":       cfg.risk.model_dump(),

        # ── Fleet / security ──────────────────────────────────────────────────
        "heartbeat_ttl":     cfg.security.heartbeat_ttl,
        "stale_threshold_s": cfg.brain.stale_data_threshold_s,

        # ── Alerts (URLs redacted) ────────────────────────────────────────────
        "alerts": {
            "ntfy_enabled":    cfg.alerts.ntfy_enabled,
            "ntfy_topic":      cfg.alerts.ntfy_topic,
            "slack_enabled":   cfg.alerts.slack_enabled,
            "webhook_enabled": cfg.alerts.webhook_enabled,
        },

        # ── 9AM CR ────────────────────────────────────────────────────────────
        "cr_9am": {
            "enabled":         cfg.analysis.cr_9am.enabled,
            "timezone":        cfg.analysis.cr_9am.timezone,
            "active_from":     cfg.analysis.cr_9am.active_from_hour,
            "active_to":       cfg.analysis.cr_9am.active_to_hour,
            "min_setup_score": cfg.analysis.cr_9am.min_setup_score,
            "tp1_pct_of_range": cfg.analysis.cr_9am.tp1_pct_of_range,
            "pairs":           cfg.analysis.cr_9am.pairs,
            "reversal_range":  os.getenv("CR_REVERSAL_RANGE", "5am"),
            "continuation_range": os.getenv("CR_CONTINUATION_RANGE", "1am"),
            "require_bos":     os.getenv("CR_REQUIRE_BOS", "true").lower() == "true",
            "require_fvg":     os.getenv("CR_REQUIRE_FVG", "false").lower() == "true",
        },
    }


@router.post("/config/patch")
async def patch_config(body: ConfigPatchRequest, request: Request):
    """
    Live-patch a single config value. Applies immediately without restart.
    Writes to the in-memory config; persists to config.yaml on reload.
    """
    brain = request.app.state.brain
    cfg   = brain.config

    try:
        if body.section == "risk":
            setattr(cfg.risk, body.key, body.value)
            brain.risk_manager._rcfg = cfg.risk
        elif body.section == "decision":
            setattr(cfg.decision, body.key, body.value)
            brain.decision_engine._dcfg = cfg.decision
        elif body.section == "graph":
            setattr(cfg.graph, body.key, body.value)
            brain.currency_graph.update_config(cfg.graph)
        elif body.section == "brain":
            setattr(cfg.brain, body.key, body.value)
        elif body.section == "cr_9am":
            setattr(cfg.analysis.cr_9am, body.key, body.value)
        else:
            from fastapi import HTTPException
            raise HTTPException(400, f"Unknown config section: {body.section}")
    except AttributeError:
        from fastapi import HTTPException
        raise HTTPException(400, f"Unknown key '{body.key}' in section '{body.section}'")

    return {"ok": True, "section": body.section, "key": body.key, "value": body.value}


@router.get("/config/exchanges/supported")
async def get_supported_exchanges():
    """List of all CCXT exchanges ARBX can connect to."""
    return {"exchanges": SUPPORTED_EXCHANGES}


@router.get("/config/exchanges/active")
async def get_active_exchanges(request: Request):
    """Currently configured exchanges with worker status."""
    brain   = request.app.state.brain
    cfg     = brain.config
    workers = brain.fleet_monitor.get_all_workers()

    worker_by_exchange: dict = {}
    for w in workers:
        ex = w.get("exchange", "")
        worker_by_exchange.setdefault(ex, []).append(w)

    result = []
    for ex in (cfg.workers.exchanges or []):
        ex_lower = ex.lower()
        ex_workers = worker_by_exchange.get(ex_lower, [])
        pairs_raw  = __import__("os").getenv(f"{ex.upper()}_PAIRS", "")
        result.append({
            "exchange":    ex_lower,
            "enabled":     True,
            "pairs_raw":   pairs_raw,
            "pair_count":  sum(w.get("pair_count", 0) for w in ex_workers),
            "worker_count": len(ex_workers),
            "healthy":     sum(1 for w in ex_workers if not w.get("is_dead")),
            "authenticated": bool(__import__("os").getenv(f"{ex.upper()}_API_KEY")),
        })
    return {"exchanges": result}


class ExchangePatchRequest(BaseModel):
    exchange: str
    pairs:    str = ""     # comma-separated or "ALL"
    enabled:  bool = True

@router.post("/config/exchanges/update")
async def update_exchange(body: ExchangePatchRequest, request: Request):
    """Add or update an exchange in the active config."""
    brain = request.app.state.brain
    cfg   = brain.config
    ex    = body.exchange.lower()

    if body.enabled and ex not in cfg.workers.exchanges:
        cfg.workers.exchanges.append(ex)
    elif not body.enabled and ex in cfg.workers.exchanges:
        cfg.workers.exchanges.remove(ex)

    if body.pairs:
        import os
        os.environ[f"{ex.upper()}_PAIRS"] = body.pairs

    return {"ok": True, "exchange": ex, "enabled": body.enabled, "pairs": body.pairs}


# ── Alert test (v5.2) ─────────────────────────────────────────────────────────

@router.post("/alerts/test")
async def test_alerts(request: Request):
    """Send a test alert through all configured channels."""
    brain = request.app.state.brain
    results = {}
    try:
        await brain.alert_sender.send({
            "title":   "ARBX Test Alert",
            "message": "This is a test notification from ARBX. All systems nominal.",
            "level":   "info",
            "source":  "portal",
        })
        results["status"] = "sent"
        results["channels"] = []
        cfg = brain.config
        if cfg.alerts.ntfy_enabled and cfg.alerts.ntfy_topic:
            results["channels"].append("ntfy")
        if cfg.alerts.slack_enabled and cfg.alerts.slack_webhook:
            results["channels"].append("slack")
        if cfg.alerts.webhook_enabled and cfg.alerts.webhook_url:
            results["channels"].append("webhook")
        if not results["channels"]:
            results["status"] = "no_channels"
            results["message"] = "No alert channels configured. Add NTFY_TOPIC, SLACK_WEBHOOK_URL, or WEBHOOK_URL to .env.local"
        else:
            results["message"] = f"Test alert sent to: {', '.join(results['channels'])}"
    except Exception as exc:
        results["status"] = "error"
        results["message"] = str(exc)
    return results


# ── Exchange connectivity test (v5.2) ─────────────────────────────────────────

class ExchangeTestRequest(BaseModel):
    exchange: str

@router.post("/config/exchanges/test")
async def test_exchange(body: ExchangeTestRequest, request: Request):
    """Test connectivity to an exchange using CCXT (public endpoint only)."""
    import asyncio
    try:
        import ccxt.async_support as ccxt_async
        ex_class = getattr(ccxt_async, body.exchange.lower(), None)
        if ex_class is None:
            return {"ok": False, "message": f"Exchange '{body.exchange}' not found in CCXT"}

        exchange = ex_class()
        try:
            # Fetch a single ticker — lightweight public endpoint
            markets = await asyncio.wait_for(exchange.load_markets(), timeout=10)
            pair_count = len(markets)
            await exchange.close()
            return {
                "ok": True,
                "message": f"Connected to {body.exchange} — {pair_count} markets available",
                "pair_count": pair_count,
            }
        except asyncio.TimeoutError:
            await exchange.close()
            return {"ok": False, "message": f"Connection timed out after 10s"}
        except Exception as exc:
            await exchange.close()
            return {"ok": False, "message": str(exc)}
    except Exception as exc:
        return {"ok": False, "message": f"CCXT error: {exc}"}


# ── Test endpoints (v5.2) ─────────────────────────────────────────────────────


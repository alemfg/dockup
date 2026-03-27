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
    """Return the current active config (sanitised — no secrets)."""
    cfg = request.app.state.brain.config
    return {
        "version":       cfg.brain.version,
        "trading_mode":  cfg.trading.mode,
        "dry_run":       cfg.brain.dry_run,
        "log_level":     cfg.brain.log_level,
        "decision":      cfg.decision.model_dump(),
        "risk":          cfg.risk.model_dump(),
        "cr_9am": {
            "enabled":        cfg.analysis.cr_9am.enabled,
            "timezone":       cfg.analysis.cr_9am.timezone,
            "active_from":    cfg.analysis.cr_9am.active_from_hour,
            "active_to":      cfg.analysis.cr_9am.active_to_hour,
            "min_setup_score": cfg.analysis.cr_9am.min_setup_score,
            "pairs":          cfg.analysis.cr_9am.pairs,
        },
        "heartbeat_ttl": cfg.security.heartbeat_ttl,
        "stale_threshold_s": cfg.brain.stale_data_threshold_s,
    }

"""System status and health routes."""
from datetime import datetime, timezone
from fastapi import APIRouter, Request
router = APIRouter(tags=["System"])
_started = datetime.now(timezone.utc)

@router.get("/system/status")
async def system_status(request: Request):
    brain = request.app.state.brain
    ms    = brain.market_state
    return {
        "status":       "running",
        "version":      brain.config.brain.version,
        "dry_run":      brain.config.brain.dry_run,
        "trading_mode": brain.config.trading.mode,
        "uptime_s":     round((datetime.now(timezone.utc) - _started).total_seconds(), 1),
        "market":       ms.summary(),
        "workers":      len(brain.fleet_monitor.get_all_workers()),
        "open_orders":  len(brain.order_log.get_open_orders()),
        "started_at":   _started.isoformat(),
    }

@router.get("/health")
async def health():
    return {"status": "ok"}

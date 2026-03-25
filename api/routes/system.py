"""System status and health routes."""
from datetime import datetime
from fastapi import APIRouter, Request
router = APIRouter(tags=["System"])
_started = datetime.utcnow()

@router.get("/system/status")
async def system_status(request: Request):
    brain = request.app.state.brain
    ms    = brain.market_state
    return {
        "status":     "running",
        "version":    brain.config.brain.version,
        "dry_run":    brain.config.brain.dry_run,
        "uptime_s":   round((datetime.utcnow() - _started).total_seconds(), 1),
        "market":     ms.summary(),
        "workers":    len(brain.fleet_monitor.get_all_workers()),
        "started_at": _started.isoformat(),
    }

@router.get("/health")
async def health():
    return {"status": "ok"}

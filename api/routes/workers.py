"""Worker registration and management routes."""
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(tags=["Workers"])


class SpawnRequest(BaseModel):
    exchange:     str
    pairs:        List[str]
    avoid_machine: Optional[str] = None


async def _cmd(brain, worker_id: str, command: str, **extra):
    await brain.bus.publish_worker_command({
        "command":   command,
        "worker_id": worker_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extra,
    })


@router.post("/workers/spawn")
async def spawn_worker(req: SpawnRequest, request: Request):
    await request.app.state.brain.bus.publish_spawn_request({
        "action":        "SPAWN",
        "exchange":      req.exchange,
        "pairs":         req.pairs,
        "avoid_machine": req.avoid_machine or "",
    })
    return {"message": f"Spawn request sent for {req.exchange} {req.pairs}"}


@router.post("/workers/{worker_id}/kill")
async def kill_worker(worker_id: str, request: Request):
    await _cmd(request.app.state.brain, worker_id, "kill")
    return {"ok": True, "message": f"Kill command sent to {worker_id}"}


@router.post("/workers/{worker_id}/restart")
async def restart_worker(worker_id: str, request: Request):
    await _cmd(request.app.state.brain, worker_id, "restart")
    return {"ok": True, "message": f"Restart command sent to {worker_id}"}


@router.post("/workers/{worker_id}/pause")
async def pause_worker(worker_id: str, request: Request):
    """Pause a worker — it stays connected but stops publishing price ticks."""
    await _cmd(request.app.state.brain, worker_id, "pause")
    return {"ok": True, "message": f"Pause command sent to {worker_id}"}


@router.post("/workers/{worker_id}/resume")
async def resume_worker(worker_id: str, request: Request):
    """Resume a paused worker."""
    await _cmd(request.app.state.brain, worker_id, "resume")
    return {"ok": True, "message": f"Resume command sent to {worker_id}"}


@router.post("/workers/{worker_id}/reload")
async def reload_worker(worker_id: str, request: Request):
    """Reload config for a specific worker."""
    await _cmd(request.app.state.brain, worker_id, "reload_config")
    return {"ok": True, "message": f"Reload command sent to {worker_id}"}


@router.post("/workers/all/reload")
async def reload_all_workers(request: Request):
    """Reload config for all workers (broadcast)."""
    brain   = request.app.state.brain
    workers = brain.fleet_monitor.get_all_workers()
    await brain.bus.publish_worker_command({
        "command":   "reload_config",
        "worker_id": "",  # empty = broadcast
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "message": f"Reload broadcast to {len(workers)} workers"}


@router.post("/workers/all/kill")
async def kill_all_workers(request: Request):
    """Kill all workers."""
    brain   = request.app.state.brain
    workers = brain.fleet_monitor.get_all_workers()
    await brain.bus.publish_worker_command({
        "command":   "kill",
        "worker_id": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "message": f"Kill broadcast to {len(workers)} workers"}


@router.post("/workers/{worker_id}/reassign")
async def reassign_pairs(worker_id: str, request: Request, pairs: List[str] = []):
    await _cmd(request.app.state.brain, worker_id, "reassign_pairs", pairs=pairs)
    return {"message": f"Pair reassignment sent to {worker_id}"}

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


# ── v6.4: Rate-limit management ───────────────────────────────────────────────

class ThrottleRequest(BaseModel):
    exchange:    str
    interval_ms: int   # new tick interval in ms (min 500)


@router.post("/workers/throttle")
async def throttle_exchange(req: ThrottleRequest, request: Request):
    """
    Broadcast a set_tick_interval command to all workers on a given exchange.
    This is the brain-side Option 1 control: slow down one exchange without
    touching workers on other exchanges.
    """
    brain   = request.app.state.brain
    workers = brain.fleet_monitor.get_all_workers()
    targets = [w for w in workers if w.get("exchange", "").lower() == req.exchange.lower()
               and not w.get("is_dead", True)]

    interval_ms = max(500, req.interval_ms)
    for w in targets:
        await brain.bus.publish_worker_command({
            "command":     "set_tick_interval",
            "worker_id":   w["worker_id"],
            "interval_ms": interval_ms,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        })

    return {
        "ok":         True,
        "exchange":   req.exchange,
        "interval_ms": interval_ms,
        "workers_notified": len(targets),
        "message": f"Throttle sent to {len(targets)} {req.exchange} worker(s) → {interval_ms}ms tick",
    }


@router.get("/workers/rate-limits")
async def get_rate_limits(request: Request):
    """
    Return per-exchange rate-limit status aggregated from the latest heartbeats.
    Each worker embeds its RateLimitGuard.status() in the heartbeat payload.
    """
    brain   = request.app.state.brain
    workers = brain.fleet_monitor.get_all_workers()

    # Aggregate by exchange — sum counters, pick worst back-off
    by_exchange: dict = {}
    for w in workers:
        if w.get("is_dead", True):
            continue
        ex = w.get("exchange", "unknown").lower()
        rl = w.get("rate_limit") or {}
        if not rl:
            continue
        if ex not in by_exchange:
            by_exchange[ex] = {
                "exchange":         ex,
                "rpm_limit":        rl.get("rpm_limit", 0),
                "workers":          0,
                "total_requests":   0,
                "total_throttled":  0,
                "total_429s":       0,
                "max_backoff_s":    0.0,
                "max_consecutive_429s": 0,
                "status":           "ok",
            }
        agg = by_exchange[ex]
        agg["workers"]              += 1
        agg["total_requests"]       += rl.get("total_requests",   0)
        agg["total_throttled"]      += rl.get("total_throttled",  0)
        agg["total_429s"]           += rl.get("total_429s",       0)
        agg["max_backoff_s"]         = max(agg["max_backoff_s"],   rl.get("backoff_s", 0.0))
        agg["max_consecutive_429s"]  = max(agg["max_consecutive_429s"], rl.get("consecutive_429s", 0))

    # Derive human-readable status
    for agg in by_exchange.values():
        if agg["max_backoff_s"] >= 30:
            agg["status"] = "throttled"
        elif agg["max_consecutive_429s"] > 0:
            agg["status"] = "recovering"
        elif agg["total_429s"] > 0:
            agg["status"] = "warning"
        else:
            agg["status"] = "ok"

    return {
        "exchanges": sorted(by_exchange.values(), key=lambda x: x["exchange"]),
        "total_429s": sum(a["total_429s"] for a in by_exchange.values()),
    }

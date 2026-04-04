"""Fleet management routes."""
from fastapi import APIRouter, Request
router = APIRouter(tags=["Fleet"])

@router.get("/fleet/workers")
async def get_workers(request: Request):
    fleet = request.app.state.brain.fleet_monitor
    workers = fleet.get_all_workers()
    return {"count": len(workers), "workers": workers}

@router.get("/fleet/workers/{worker_id}")
async def get_worker(worker_id: str, request: Request):
    fleet  = request.app.state.brain.fleet_monitor
    worker = fleet.get_worker(worker_id)
    if not worker:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")
    return worker.to_dict()

@router.get("/fleet/events")
async def get_events(request: Request, limit: int = 100):
    fleet = request.app.state.brain.fleet_monitor
    return {"events": fleet.get_event_log(limit=limit)}

@router.get("/fleet/coverage")
async def get_coverage(request: Request):
    fleet = request.app.state.brain.fleet_monitor
    ms    = request.app.state.brain.market_state
    workers = fleet.get_all_workers()
    coverage = {}
    for w in workers:
        for pair in w.get("pairs", []):
            key = f"{w['exchange']}:{pair}"
            coverage[key] = {
                "exchange":  w["exchange"],
                "pair":      pair,
                "worker_id": w["worker_id"],
                "status":    w["status"],
            }
    return {
        "covered":    len(coverage),
        "gaps":       fleet.get_coverage_gaps(),
        "coverage":   coverage,
    }

@router.post("/fleet/workers/{worker_id}/kill")
async def kill_worker(worker_id: str, request: Request):
    bus = request.app.state.brain.bus
    await bus.publish_worker_command({"command": "kill", "worker_id": worker_id})
    return {"message": f"Kill command sent to {worker_id}"}

@router.post("/fleet/workers/{worker_id}/restart")
async def restart_worker(worker_id: str, request: Request):
    brain  = request.app.state.brain
    worker = brain.fleet_monitor.get_worker(worker_id)
    if not worker:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Worker not found")
    await brain.bus.publish_spawn_request({
        "action":          "SPAWN",
        "exchange":        worker.exchange,
        "pairs":           worker.pairs,
        "worker_id":       worker_id,
        "kill_original":   True,
        "avoid_machine":   worker.machine,
    })
    return {"message": f"Restart requested for {worker_id}"}

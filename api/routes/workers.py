"""Worker registration and management routes."""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import List, Optional
router = APIRouter(tags=["Workers"])

class SpawnRequest(BaseModel):
    exchange:    str
    pairs:       List[str]
    avoid_machine: Optional[str] = None

@router.post("/workers/spawn")
async def spawn_worker(req: SpawnRequest, request: Request):
    await request.app.state.brain.bus.publish_spawn_request({
        "action":         "SPAWN",
        "exchange":       req.exchange,
        "pairs":          req.pairs,
        "avoid_machine":  req.avoid_machine or "",
    })
    return {"message": f"Spawn request sent for {req.exchange} {req.pairs}"}

@router.post("/workers/{worker_id}/reassign")
async def reassign_pairs(worker_id: str, request: Request, pairs: List[str] = []):
    await request.app.state.brain.bus.publish_worker_command({
        "command":   "reassign_pairs",
        "worker_id": worker_id,
        "pairs":     pairs,
    })
    return {"message": f"Pair reassignment sent to {worker_id}"}

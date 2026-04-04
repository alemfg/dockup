"""Security management routes."""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import List, Optional
router = APIRouter(tags=["Security"])

class RegisterWorkerRequest(BaseModel):
    worker_id:           str
    exchange:            str
    allowed_pairs:       List[str] = []
    can_execute_orders:  bool = False
    max_order_size_usd:  float = 0.0
    ip_whitelist:        List[str] = []
    expires_days:        int = 30

@router.get("/security/workers")
async def list_registered_workers(request: Request):
    auth = request.app.state.brain.auth_manager
    return {
        "workers":          auth.list_workers(),
        "rejections_24h":   auth.rejection_count_24h(),
        "recent_rejections": auth.get_rejection_log(limit=20),
    }

@router.post("/security/workers/register")
async def register_worker(req: RegisterWorkerRequest, request: Request):
    auth = request.app.state.brain.auth_manager
    secret = auth.register_worker(
        worker_id=req.worker_id,
        exchange=req.exchange,
        allowed_pairs=req.allowed_pairs,
        can_execute_orders=req.can_execute_orders,
        max_order_size_usd=req.max_order_size_usd,
        ip_whitelist=req.ip_whitelist,
        expires_days=req.expires_days,
    )
    return {
        "worker_id":  req.worker_id,
        "secret_key": secret,
        "message":    "Store this secret key securely — it will not be shown again.",
    }

@router.post("/security/workers/{worker_id}/revoke")
async def revoke_worker(worker_id: str, request: Request):
    auth = request.app.state.brain.auth_manager
    ok   = auth.revoke_worker(worker_id)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")
    # Send kill command to the worker
    await request.app.state.brain.bus.publish_worker_command({
        "command": "kill", "worker_id": worker_id
    })
    return {"message": f"Worker {worker_id} revoked and kill command sent."}

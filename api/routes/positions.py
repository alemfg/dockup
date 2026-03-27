"""Positions API — open positions, P&L, and manual close."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["Positions"])


class ManualCloseRequest(BaseModel):
    reason: str = "manual"


@router.get("/positions")
async def get_positions(request: Request):
    pt = request.app.state.brain.position_tracker
    return {
        "open":    pt.get_open_positions(),
        "summary": pt.get_pnl_summary(),
    }


@router.get("/positions/closed")
async def get_closed_positions(request: Request, limit: int = 100):
    return {"positions": request.app.state.brain.position_tracker.get_closed_positions(limit=limit)}


@router.get("/positions/daily-pnl")
async def get_daily_pnl(request: Request):
    return {"daily_pnl": request.app.state.brain.position_tracker.get_daily_pnl()}


@router.post("/positions/{position_id}/close")
async def close_position(position_id: str, body: ManualCloseRequest, request: Request):
    brain = request.app.state.brain
    ms    = brain.market_state

    pt  = brain.position_tracker
    pos = next((p for p in pt.get_open_positions() if p["id"] == position_id), None)
    if not pos:
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")

    current_price = ms.get_price(pos["exchange"], pos["pair"]) or pos["current_price"]
    result = pt.close_position(position_id, current_price, body.reason)

    if result and brain.order_log:
        brain.order_log.record_close(
            pos["order_id"], body.reason,
            result["position"].get("pnl_usd", 0.0), current_price,
        )
    if result and brain.risk_manager:
        brain.risk_manager.record_result(result["position"].get("pnl_usd", 0.0))

    return {"ok": True, "result": result}

"""Orders API — full lifecycle query and manual control."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["Orders"])


@router.get("/orders")
async def get_orders(
    request:  Request,
    limit:    int = 100,
    exchange: Optional[str] = None,
    pair:     Optional[str] = None,
    status:   Optional[str] = None,
    source:   Optional[str] = None,
):
    log = request.app.state.brain.order_log
    return {
        "orders":  log.get_all(limit=limit, exchange=exchange,
                               pair=pair, status=status, source=source),
        "summary": log.financial_summary(),
    }


@router.get("/orders/open")
async def get_open_orders(request: Request):
    return {"orders": request.app.state.brain.order_log.get_open_orders()}


@router.get("/orders/log")
async def get_decision_log(request: Request, limit: int = 100):
    """Full decision engine log including blocked and simulated orders."""
    return {
        "orders": request.app.state.brain.decision_engine.get_order_log(limit=limit),
        "stats":  request.app.state.brain.decision_engine.get_stats(),
    }


@router.get("/orders/daily-pnl")
async def get_daily_pnl(request: Request):
    return {"daily_pnl": request.app.state.brain.order_log.daily_pnl()}


@router.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    order = request.app.state.brain.order_log.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return order

"""Financials API — P&L summary, charts, trade statistics."""
from fastapi import APIRouter, Request

router = APIRouter(tags=["Financials"])


@router.get("/financials/summary")
async def get_financial_summary(request: Request):
    brain = request.app.state.brain
    order_summary = brain.order_log.financial_summary()
    pos_summary   = brain.position_tracker.get_pnl_summary()
    risk_status   = brain.risk_manager.status()

    return {
        "orders":          order_summary,
        "positions":       pos_summary,
        "risk":            risk_status,
        "total_balance_usd": round(brain.market_state.get_total_usd(), 2),
    }


@router.get("/financials/daily-pnl")
async def get_daily_pnl(request: Request):
    return {
        "orders":    request.app.state.brain.order_log.daily_pnl(),
        "positions": request.app.state.brain.position_tracker.get_daily_pnl(),
    }


@router.get("/financials/trades")
async def get_trades(request: Request, limit: int = 50):
    """Closed positions with full detail — for the trade history table."""
    return {
        "trades":  request.app.state.brain.position_tracker.get_closed_positions(limit=limit),
        "summary": request.app.state.brain.position_tracker.get_pnl_summary(),
    }

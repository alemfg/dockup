"""Financials API — P&L summary, charts, trade statistics, balance breakdown."""
from fastapi import APIRouter, Request
from collections import defaultdict

router = APIRouter(tags=["Financials"])


@router.get("/financials/summary")
async def get_financial_summary(request: Request):
    brain         = request.app.state.brain
    order_summary = brain.order_log.financial_summary()
    pos_summary   = brain.position_tracker.get_pnl_summary()
    risk_status   = brain.risk_manager.status()
    ms            = brain.market_state

    # ── Balance breakdown ─────────────────────────────────────────────────────
    all_balances  = ms.get_all_balances()
    by_exchange   = ms.get_balances_by_exchange()

    # Total USD per exchange
    exchange_totals = {
        ex: round(sum(b.get("usd_value", 0) for b in bals), 2)
        for ex, bals in by_exchange.items()
        if sum(b.get("usd_value", 0) for b in bals) > 0.01
    }

    # Total per asset across all exchanges
    asset_totals: dict = defaultdict(lambda: {"total": 0.0, "usd_value": 0.0, "exchanges": []})
    for b in all_balances:
        asset = b.get("asset", "?")
        asset_totals[asset]["total"]     += b.get("total", 0)
        asset_totals[asset]["usd_value"] += b.get("usd_value", 0)
        asset_totals[asset]["exchanges"].append(b.get("exchange", "?"))
    asset_totals_clean = {
        k: {**v, "usd_value": round(v["usd_value"], 2), "total": round(v["total"], 8)}
        for k, v in asset_totals.items()
        if v["usd_value"] > 0.01
    }

    # Orders breakdown
    open_orders = brain.order_log.get_open_orders()

    return {
        "orders":             order_summary,
        "positions":          pos_summary,
        "risk":               risk_status,
        "total_balance_usd":  round(ms.get_total_usd(), 2),
        "exchange_totals":    exchange_totals,
        "asset_totals":       asset_totals_clean,
        "open_orders_count":  len(open_orders),
        "open_orders":        open_orders[:20],   # cap at 20 for display
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

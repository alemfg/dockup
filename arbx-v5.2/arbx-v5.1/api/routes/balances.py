"""Balance routes."""
from typing import Dict, Optional
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["Balances"])


@router.get("/balances")
async def get_balances(request: Request):
    ms = request.app.state.brain.market_state
    return {
        "total_usd": round(ms.get_total_usd(), 2),
        "exchanges": ms.get_balances_by_exchange(),
        "all":       ms.get_all_balances(),
    }


class RebalanceRequest(BaseModel):
    target_pct:    Optional[Dict[str, float]] = None  # {exchange: target_%}
    threshold_pct: float = 5.0


@router.post("/balances/rebalance/suggest")
async def suggest_rebalance(body: RebalanceRequest, request: Request):
    """
    v3.2 — Return rebalance suggestions for manual approval.
    No transfers are made — user must approve each one on the dashboard.
    """
    ms = request.app.state.brain.market_state
    suggestions = ms.get_rebalance_suggestions(
        target_pct=body.target_pct,
        threshold_pct=body.threshold_pct,
    )
    return {
        "total_usd":   round(ms.get_total_usd(), 2),
        "suggestions": suggestions,
        "count":       len(suggestions),
        "note": "No transfers have been made. Review and approve each suggestion.",
    }

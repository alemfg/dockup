"""Balance routes."""
from fastapi import APIRouter, Request
router = APIRouter(tags=["Balances"])

@router.get("/balances")
async def get_balances(request: Request):
    ms = request.app.state.brain.market_state
    return {
        "total_usd":  round(ms.get_total_usd(), 2),
        "exchanges":  ms.get_balances_by_exchange(),
        "all":        ms.get_all_balances(),
    }

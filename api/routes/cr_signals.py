"""9AM CR Model signal routes."""
from fastapi import APIRouter, Request
router = APIRouter(tags=["CR 9AM"])

@router.get("/cr/signals")
async def get_cr_signals(request: Request):
    """Return all active 9AM CR setups for today."""
    from analysis.plugins.registry import get_plugin
    plugin = get_plugin("cr_9am")
    if not plugin:
        return {"signals": [], "message": "CR 9AM plugin not loaded"}

    signals = plugin.get_active_signals()
    return {
        "count":      len(signals),
        "signals":    signals,
        "plugin_active": True,
    }

@router.get("/cr/signals/{exchange}/{pair}")
async def get_cr_signal(exchange: str, pair: str, request: Request):
    """Return CR signal for a specific exchange/pair."""
    from analysis.plugins.registry import get_plugin
    from fastapi import HTTPException
    plugin = get_plugin("cr_9am")
    if not plugin:
        raise HTTPException(status_code=404, detail="CR 9AM plugin not loaded")

    signals = plugin.get_active_signals()
    match = next(
        (s for s in signals if s["exchange"] == exchange and s["pair"] == pair.replace("-", "/")),
        None
    )
    if not match:
        raise HTTPException(status_code=404, detail=f"No CR signal for {exchange}:{pair}")
    return match

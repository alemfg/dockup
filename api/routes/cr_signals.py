"""9AM CR Model signal routes."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["CR 9AM"])


class ForceActiveRequest(BaseModel):
    active: bool


@router.get("/cr/signals")
async def get_cr_signals(request: Request):
    """Return all active 9AM CR setups for today."""
    from analysis.plugins.registry import get_plugin
    plugin = get_plugin("cr_9am")
    if not plugin:
        return {"signals": [], "message": "CR 9AM plugin not loaded"}

    signals = plugin.get_active_signals()
    return {
        "count":        len(signals),
        "signals":      signals,
        "plugin_active": True,
        "force_active": getattr(plugin, "_force_active", False),
    }


@router.get("/cr/signals/{exchange}/{pair}")
async def get_cr_signal(exchange: str, pair: str, request: Request):
    """Return CR signal for a specific exchange/pair."""
    from analysis.plugins.registry import get_plugin
    plugin = get_plugin("cr_9am")
    if not plugin:
        raise HTTPException(status_code=404, detail="CR 9AM plugin not loaded")

    signals = plugin.get_active_signals()
    match = next(
        (s for s in signals if s["exchange"] == exchange and s["pair"] == pair.replace("-", "/")),
        None,
    )
    if not match:
        raise HTTPException(status_code=404, detail=f"No CR signal for {exchange}:{pair}")
    return match


@router.post("/cr/force-active")
async def set_cr_force_active(body: ForceActiveRequest, request: Request):
    """
    Bypass the 09:00-10:00 NY time gate and force the CR plugin to analyse
    regardless of current time. Resets on brain restart.
    """
    from analysis.plugins.registry import get_plugin
    plugin = get_plugin("cr_9am")
    if not plugin:
        raise HTTPException(status_code=404, detail="CR 9AM plugin not loaded")

    plugin.set_force_active(body.active)

    from messaging.logging import get_logger
    get_logger("api.cr").warning(
        f"CR 9AM force-active set to {body.active} via dashboard"
    )

    return {
        "ok":          True,
        "force_active": body.active,
        "message": (
            "⚠️ CR model running outside market hours — no real candle data available."
            if body.active else
            "CR model restored to normal time-gated operation."
        ),
    }


@router.get("/cr/history")
async def get_cr_history(request: Request, limit: int = 100):
    """Return history of past CR signals, newest first."""
    from analysis.plugins.registry import get_plugin
    plugin = get_plugin("cr_9am")
    if not plugin:
        return {"history": [], "message": "CR 9AM plugin not loaded"}
    return {
        "count":   min(limit, len(plugin._signal_history)),
        "history": plugin.get_signal_history(limit=limit),
    }


@router.get("/cr/state")
async def get_cr_daily_state(request: Request):
    """Return CRT daily state per pair — 1AM/5AM ranges, model type, sweep status."""
    from analysis.plugins.registry import get_plugin
    plugin = get_plugin("cr_9am")
    if not plugin:
        return {"state": [], "message": "CR 9AM plugin not loaded"}
    return {
        "state":        plugin.get_daily_state(),
        "force_active": getattr(plugin, "_force_active", False),
    }

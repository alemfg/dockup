"""Risk Manager API — status, circuit breaker control, config."""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["Risk"])


class RiskConfigUpdate(BaseModel):
    max_daily_loss_usd:     Optional[float] = None
    max_drawdown_pct:       Optional[float] = None
    max_consecutive_losses: Optional[int]   = None
    max_pair_exposure_usd:  Optional[float] = None


@router.get("/risk/status")
async def get_risk_status(request: Request):
    return request.app.state.brain.risk_manager.status()


@router.post("/risk/resume")
async def resume_after_halt(request: Request):
    """Manually clear a risk halt. Use with caution."""
    brain = request.app.state.brain
    brain.risk_manager.resume()
    return {"ok": True, "message": "Risk halt cleared. System resuming."}


@router.get("/risk/config")
async def get_risk_config(request: Request):
    cfg = request.app.state.brain.config.risk
    return cfg.model_dump()


@router.patch("/risk/config")
async def update_risk_config(update: RiskConfigUpdate, request: Request):
    """Update risk limits at runtime without restarting."""
    cfg = request.app.state.brain.config.risk
    if update.max_daily_loss_usd is not None:
        cfg.max_daily_loss_usd = update.max_daily_loss_usd
    if update.max_drawdown_pct is not None:
        cfg.max_drawdown_pct = update.max_drawdown_pct
    if update.max_consecutive_losses is not None:
        cfg.max_consecutive_losses = update.max_consecutive_losses
    if update.max_pair_exposure_usd is not None:
        cfg.max_pair_exposure_usd = update.max_pair_exposure_usd

    from messaging.logging import get_logger
    get_logger("api.risk").warning(f"Risk config updated at runtime: {update}")
    return {"ok": True, "config": cfg.model_dump()}


@router.get("/risk/decision-config")
async def get_decision_config(request: Request):
    return request.app.state.brain.config.decision.model_dump()


@router.patch("/risk/decision-config")
async def update_decision_config(update: dict, request: Request):
    """Update decision engine rules at runtime."""
    cfg = request.app.state.brain.config.decision
    for k, v in update.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    from messaging.logging import get_logger
    get_logger("api.risk").warning(f"Decision config updated: {update}")
    return {"ok": True, "config": cfg.model_dump()}

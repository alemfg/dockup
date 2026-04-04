"""
Trading mode routes — read and update the global trading mode and
per-exchange enable flags at runtime without restarting the brain.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Optional

from config.loader import TradingMode

router = APIRouter(tags=["Trading"])


class TradingModeUpdate(BaseModel):
    mode: TradingMode
    confirm: bool = False           # must be True when switching to "live"


class ExchangeToggle(BaseModel):
    enabled: bool


@router.get("/trading/mode")
async def get_trading_mode(request: Request):
    """Return current trading mode and per-exchange flags."""
    cfg = request.app.state.brain.config.trading
    return {
        "mode":             cfg.mode,
        "exchange_enabled": cfg.exchange_enabled,
        "description": {
            "disabled": "No orders sent or logged.",
            "simulate": "Orders computed and logged — never sent to exchange.",
            "live":     "Real orders sent via CCXT.",
        }[cfg.mode],
    }


@router.post("/trading/mode")
async def set_trading_mode(update: TradingModeUpdate, request: Request):
    """
    Change the global trading mode.
    Switching to 'live' requires confirm=true in the request body.
    """
    cfg = request.app.state.brain.config.trading

    if update.mode == TradingMode.LIVE and not update.confirm:
        raise HTTPException(
            status_code=400,
            detail="Switching to LIVE mode requires confirm=true. "
                   "This will place real orders on exchanges.",
        )

    old_mode = cfg.mode
    cfg.mode = update.mode

    from messaging.logging import get_logger
    logger = get_logger("api.trading")
    logger.warning(
        f"Trading mode changed: {old_mode} → {update.mode} "
        f"(confirmed={update.confirm})"
    )

    return {
        "ok":       True,
        "old_mode": old_mode,
        "new_mode": cfg.mode,
    }


@router.post("/trading/exchanges/{exchange}")
async def set_exchange_trading(
    exchange: str,
    toggle: ExchangeToggle,
    request: Request,
):
    """Enable or disable order execution for a specific exchange."""
    cfg = request.app.state.brain.config.trading
    cfg.exchange_enabled[exchange] = toggle.enabled
    return {
        "ok":      True,
        "exchange": exchange,
        "enabled":  toggle.enabled,
        "mode":     cfg.mode,
    }


@router.get("/trading/status")
async def trading_status(request: Request):
    """Full trading status — mode, per-exchange flags, and a safety summary."""
    cfg = request.app.state.brain.config.trading
    exchanges_live = [
        ex for ex, en in cfg.exchange_enabled.items() if en
    ]
    return {
        "mode":              cfg.mode,
        "exchange_enabled":  cfg.exchange_enabled,
        "exchanges_live":    exchanges_live,
        "orders_will_fire":  cfg.mode == TradingMode.LIVE and len(exchanges_live) > 0,
        "orders_simulated":  cfg.mode == TradingMode.SIMULATE,
        "orders_blocked":    cfg.mode == TradingMode.DISABLED,
    }

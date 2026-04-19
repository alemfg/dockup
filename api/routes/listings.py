"""
Listings API (v6.8)
Routes for the new listing monitor: watchlist management,
opportunity history, CoinGecko feed, status.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["Listings"])


def _lm(request: Request):
    lm = getattr(request.app.state.brain, "listing_monitor", None)
    if not lm:
        raise HTTPException(503, "Listing monitor not initialised")
    return lm


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/listings/status")
async def get_listing_status(request: Request):
    return _lm(request).status()


# ── Watchlist ─────────────────────────────────────────────────────────────────

@router.get("/listings/watchlist")
async def get_watchlist(request: Request):
    return {"watchlist": _lm(request).get_watchlist()}


class WatchlistAddRequest(BaseModel):
    symbol:             str
    name:               str = ""
    reference_exchange: str = "binance"
    notes:              str = ""
    listing_date:       Optional[str] = None


@router.post("/listings/watchlist")
async def add_to_watchlist(body: WatchlistAddRequest, request: Request):
    lm = _lm(request)
    lm.add_to_watchlist(
        symbol=body.symbol,
        name=body.name,
        source="manual",
        reference_exchange=body.reference_exchange,
        notes=body.notes,
        listing_date=body.listing_date,
    )
    return {"ok": True, "symbol": body.symbol.upper()}


@router.delete("/listings/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str, request: Request):
    removed = _lm(request).remove_from_watchlist(symbol)
    if not removed:
        raise HTTPException(404, f"{symbol} not in watchlist")
    return {"ok": True, "symbol": symbol.upper()}


# ── Opportunities ─────────────────────────────────────────────────────────────

@router.get("/listings/opportunities")
async def get_opportunities(request: Request, limit: int = 50):
    return {"opportunities": _lm(request).get_opportunities(limit=limit)}


# ── CoinGecko feed ────────────────────────────────────────────────────────────

@router.get("/listings/new")
async def get_new_listings(request: Request, limit: int = 30):
    """Recently added coins from CoinGecko. Refreshed every 30 minutes."""
    lm = _lm(request)
    return {
        "listings":     lm.get_cg_listings(limit=limit),
        "fetched_at":   lm._cg_fetched_at or None,
        "count":        len(lm.get_cg_listings(limit=limit)),
    }


@router.post("/listings/refresh")
async def force_refresh(request: Request):
    """Force-refresh CoinGecko listing data immediately."""
    import asyncio
    lm = _lm(request)
    asyncio.create_task(lm._fetch_cg_listings())
    return {"ok": True, "message": "CoinGecko refresh triggered"}

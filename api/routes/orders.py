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


# ── Manual order placement (v6.1) ──────────────────────────────────────────

from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional

class ManualOrderRequest(_BaseModel):
    exchange:    str
    pair:        str
    side:        str              # "buy" | "sell"
    order_type:  str = "market"  # "market" | "limit"
    volume:      float
    price:       float = 0.0
    stop_loss:   float = 0.0
    take_profit: float = 0.0
    capital_usd: float = 0.0
    notes:       str   = "manual"
    confirm:     bool  = False    # must be True for LIVE


@router.post("/orders/place")
async def place_order(body: ManualOrderRequest, request: Request):
    """
    Place a manual order.
    SIMULATE mode: always allowed.
    LIVE mode: requires confirm=true and a stored API key for the exchange.
    """
    from config.loader import TradingMode
    from uuid import uuid4
    from datetime import datetime, timezone, timedelta

    brain = request.app.state.brain
    mode  = brain.config.trading.mode

    if mode == TradingMode.DISABLED:
        raise HTTPException(400, "Trading is DISABLED. Switch to SIMULATE or LIVE first.")

    if mode == TradingMode.LIVE and not body.confirm:
        raise HTTPException(400, "LIVE order requires confirm=true. This places a real order.")

    if body.volume <= 0:
        raise HTTPException(400, "volume must be > 0")

    order_id = str(uuid4())
    cmd = {
        "id":           order_id,
        "exchange":     body.exchange,
        "pair":         body.pair,
        "side":         body.side,
        "order_type":   body.order_type,
        "price":        body.price,
        "volume":       body.volume,
        "capital_usd":  body.capital_usd or (body.price * body.volume),
        "stop_loss":    body.stop_loss,
        "take_profit_1": body.take_profit,
        "take_profit_2": 0.0,
        "source":       "manual",
        "trading_mode": mode.value,
        "dry_run":      mode != TradingMode.LIVE,
        "notes":        body.notes,
        "created_at":   datetime.now(timezone.utc).isoformat(),
        "expires_at":   (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
    }

    # Record in order log
    brain.order_log.record_command(cmd)

    # Publish to execution queue.
    # The brain's bus lives on its own event loop (separate thread from the API).
    # Submit the coroutine to the brain's loop rather than awaiting it here.
    main_loop = getattr(brain, "_main_loop", None)
    if main_loop and main_loop.is_running():
        import concurrent.futures
        fut = asyncio.run_coroutine_threadsafe(
            brain.bus.publish_order_command(cmd), main_loop
        )
        try:
            fut.result(timeout=5)
        except concurrent.futures.TimeoutError:
            raise HTTPException(503, "Order bus timeout — brain loop may be busy")
        except Exception as exc:
            raise HTTPException(503, f"Order publish failed: {exc}")
    else:
        # Fallback: same-loop execution (dev mode / tests)
        await brain.bus.publish_order_command(cmd)

    return {
        "ok":      True,
        "order_id": order_id,
        "mode":    mode.value,
        "message": f"Order queued for {'LIVE execution' if mode == TradingMode.LIVE else 'simulation'}",
    }


@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, request: Request):
    """Cancel an open order (LIVE: calls exchange API; SIMULATE: marks cancelled)."""
    from config.loader import TradingMode
    brain = request.app.state.brain
    order = brain.order_log.get(order_id)
    if not order:
        raise HTTPException(404, f"Order {order_id} not found")

    if order.get("status") not in ("pending", "sent", "partial"):
        raise HTTPException(400, f"Order status is '{order.get('status')}' — cannot cancel")

    mode = brain.config.trading.mode
    if mode == TradingMode.LIVE and order.get("exchange_order_id"):
        try:
            import ccxt.async_support as ccxt_async
            cs   = brain.persistence.config_store
            creds = await cs.get_api_key(order["exchange"]) if cs else None
            if creds:
                cls = getattr(ccxt_async, order["exchange"], None)
                if cls:
                    ex = cls({"apiKey": creds["api_key"], "secret": creds["api_secret"]})
                    try:
                        await ex.cancel_order(order["exchange_order_id"], order["pair"])
                    finally:
                        await ex.close()
        except Exception as exc:
            return {"ok": False, "message": f"Exchange cancel failed: {exc}"}

    brain.order_log.record_close(order_id, "cancelled", 0.0, order.get("price", 0), persistence=brain.persistence)
    return {"ok": True, "order_id": order_id, "status": "cancelled"}

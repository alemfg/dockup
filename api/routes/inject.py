"""
Price Injection API — accepts synthetic ticks via HTTP.

All endpoints publish directly to the Redis stream exactly as a worker would.
Use for:
  - curl-based testing and scripting
  - CI/CD integration test pipelines
  - Automated scenario replay

Endpoints:
  POST /api/inject/tick       single price tick
  POST /api/inject/ticks      batch of ticks
  POST /api/inject/spread     two-exchange spread
  POST /api/inject/candle     OHLCV candle (for CR model)
  POST /api/inject/scenario   full named scenario (JSON body)
  POST /api/inject/cycle      graph arbitrage cycle
  GET  /api/inject/status     show injected tick count + last tick
  DELETE /api/inject/reset    clear injected state (flush graph etc.)
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from injector.engine import PriceInjector, SyntheticTick, SyntheticCandle

router = APIRouter(tags=["Price Injection (Testing)"])

# Module-level counter so /inject/status can report
_inject_count = 0
_last_tick: Optional[dict] = None


def _get_injector(request: Request) -> PriceInjector:
    """Get or create a PriceInjector attached to the brain's message bus."""
    brain = request.app.state.brain
    if not hasattr(brain, "_injector") or brain._injector is None:
        brain._injector = PriceInjector(
            redis_host=brain.config.redis.host,
            redis_port=brain.config.redis.port,
            verbose=True,
        )
        brain._injector._bus = brain.bus   # reuse brain's already-connected bus
    return brain._injector


# ─── Request models ───────────────────────────────────────────────────────────

class TickRequest(BaseModel):
    exchange:   str
    pair:       str
    price:      float
    volume_24h: float = 50_000.0
    delay_ms:   int   = 0
    note:       str   = ""


class CandleRequest(BaseModel):
    exchange:  str
    pair:      str
    timeframe: str   = "1H"
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float = 100.0
    time:      Optional[str] = None


class SpreadRequest(BaseModel):
    pair:        str
    buy_exchange:  str
    buy_price:     float
    sell_exchange: str
    sell_price:    float
    note:        str = ""


class CycleLeg(BaseModel):
    exchange: str
    pair:     str
    price:    float


class ScenarioRequest(BaseModel):
    name:        str = "ad-hoc"
    description: str = ""
    ticks:   List[TickRequest]   = []
    candles: List[CandleRequest] = []


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/inject/tick")
async def inject_tick(req: TickRequest, request: Request):
    """
    Inject a single synthetic price tick.

    curl example:
      curl -X POST http://localhost:8000/api/inject/tick \\
        -H "Content-Type: application/json" \\
        -d '{"exchange":"binance","pair":"BTC/USDT","price":70000}'
    """
    global _inject_count, _last_tick
    inj = _get_injector(request)
    tick = SyntheticTick(**req.model_dump())
    msg_id = await inj.inject_tick(tick)
    _inject_count += 1
    _last_tick = req.model_dump()
    return {
        "injected": True,
        "msg_id":   msg_id,
        "tick":     req.model_dump(),
        "total":    _inject_count,
    }


@router.post("/inject/ticks")
async def inject_ticks(reqs: List[TickRequest], request: Request):
    """
    Inject a batch of price ticks.

    curl example:
      curl -X POST http://localhost:8000/api/inject/ticks \\
        -H "Content-Type: application/json" \\
        -d '[{"exchange":"binance","pair":"BTC/USDT","price":65000},
             {"exchange":"kraken","pair":"BTC/USDT","price":66000}]'
    """
    global _inject_count, _last_tick
    inj = _get_injector(request)
    ids = []
    for req in reqs:
        tick = SyntheticTick(**req.model_dump())
        ids.append(await inj.inject_tick(tick))
        _inject_count += 1
        _last_tick = req.model_dump()
    return {"injected": len(ids), "msg_ids": ids, "total": _inject_count}


@router.post("/inject/spread")
async def inject_spread(req: SpreadRequest, request: Request):
    """
    Inject prices on two exchanges to simulate a spatial arbitrage spread.

    curl example:
      curl -X POST http://localhost:8000/api/inject/spread \\
        -H "Content-Type: application/json" \\
        -d '{"pair":"BTC/USDT","buy_exchange":"binance","buy_price":65000,
             "sell_exchange":"kraken","sell_price":66000}'
    """
    global _inject_count
    inj  = _get_injector(request)
    spread_pct = ((req.sell_price - req.buy_price) / req.buy_price) * 100
    await inj.inject_spread(
        pair=req.pair,
        buy_exchange=req.buy_exchange,   buy_price=req.buy_price,
        sell_exchange=req.sell_exchange, sell_price=req.sell_price,
        note=req.note or f"{spread_pct:.3f}% spread",
    )
    _inject_count += 2
    return {
        "injected":   True,
        "pair":       req.pair,
        "spread_pct": round(spread_pct, 4),
        "buy":  {"exchange": req.buy_exchange,  "price": req.buy_price},
        "sell": {"exchange": req.sell_exchange, "price": req.sell_price},
    }


@router.post("/inject/candle")
async def inject_candle(req: CandleRequest, request: Request):
    """
    Inject an OHLCV candle. Used to test the 9AM CR model.

    curl example (inject the 8AM 1H candle for CR model):
      curl -X POST http://localhost:8000/api/inject/candle \\
        -H "Content-Type: application/json" \\
        -d '{"exchange":"binance","pair":"BTC/USDT","timeframe":"1H",
             "open":64000,"high":65500,"low":63800,"close":65000,
             "time":"2026-03-23T08:00:00"}'
    """
    inj = _get_injector(request)
    candle = SyntheticCandle(**req.model_dump())
    msg_id = await inj.inject_candle(candle)
    return {"injected": True, "msg_id": msg_id, "candle": req.model_dump()}


@router.post("/inject/cycle")
async def inject_cycle(legs: List[CycleLeg], request: Request):
    """
    Inject a set of prices that form a graph arbitrage cycle.

    curl example (3-hop profitable cycle):
      curl -X POST http://localhost:8000/api/inject/cycle \\
        -H "Content-Type: application/json" \\
        -d '[{"exchange":"binance","pair":"BTC/USDT","price":65000},
             {"exchange":"binance","pair":"ETH/BTC","price":0.0490},
             {"exchange":"binance","pair":"ETH/USDT","price":3250}]'
    """
    global _inject_count
    inj = _get_injector(request)
    ticks = [(leg.exchange, leg.pair, leg.price) for leg in legs]
    await inj.inject_graph_cycle(ticks)
    _inject_count += len(ticks)
    return {"injected": len(ticks), "legs": [l.model_dump() for l in legs]}


@router.post("/inject/scenario")
async def inject_scenario(req: ScenarioRequest, request: Request):
    """
    Run a full named scenario (batch of ticks + candles).

    curl example:
      curl -X POST http://localhost:8000/api/inject/scenario \\
        -H "Content-Type: application/json" \\
        -d @config/scenarios/btc_pump.json

    Or inline:
      curl -X POST http://localhost:8000/api/inject/scenario \\
        -H "Content-Type: application/json" \\
        -d '{
          "name": "test spread",
          "ticks": [
            {"exchange":"binance","pair":"BTC/USDT","price":65000},
            {"exchange":"kraken","pair":"BTC/USDT","price":66000}
          ]
        }'
    """
    global _inject_count
    inj = _get_injector(request)
    scenario = req.model_dump()
    result = await inj.inject_scenario(scenario)
    _inject_count += result["ticks"] + result["candles"]
    return result


@router.get("/inject/status")
async def inject_status(request: Request):
    """Current injector status — total injected, last tick, graph state."""
    brain = request.app.state.brain
    return {
        "total_injected": _inject_count,
        "last_tick":      _last_tick,
        "graph_nodes":    brain.currency_graph.node_count,
        "graph_edges":    brain.currency_graph.edge_count,
        "graph_paths":    len(brain._graph_paths),
        "timestamp":      datetime.utcnow().isoformat(),
    }


@router.delete("/inject/reset")
async def inject_reset(request: Request):
    """
    Reset injector state — clears the currency graph so you start fresh.
    Workers will repopulate it naturally within seconds.

    curl example:
      curl -X DELETE http://localhost:8000/api/inject/reset
    """
    global _inject_count, _last_tick
    brain = request.app.state.brain
    brain.currency_graph._edges.clear()
    brain.currency_graph._nodes.clear()
    brain._graph_paths = []
    _inject_count = 0
    _last_tick    = None
    return {"reset": True, "message": "Graph and injector state cleared."}

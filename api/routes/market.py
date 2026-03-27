"""Market data routes."""
from fastapi import APIRouter, Request
router = APIRouter(tags=["Market"])

@router.get("/market/prices")
async def get_prices(request: Request):
    ms = request.app.state.brain.market_state
    return {"prices": ms.get_all_prices(), "pairs": ms.get_all_pairs()}

@router.get("/market/prices/{exchange}/{pair}")
async def get_price(exchange: str, pair: str, request: Request):
    ms    = request.app.state.brain.market_state
    price = ms.get_price(exchange, pair.replace("-", "/"))
    return {"exchange": exchange, "pair": pair, "price": price}

@router.get("/market/spreads")
async def get_spreads(request: Request):
    ms    = request.app.state.brain.market_state
    pairs = ms.get_all_pairs()
    result = []
    for pair in sorted(pairs):
        prices = ms.get_prices_for_pair(pair)
        if len(prices) >= 2:
            vals = list(prices.values())
            spread = ((max(vals) - min(vals)) / min(vals)) * 100
            result.append({"pair": pair, "spread_pct": round(spread, 4), "prices": prices})
    return {"spreads": sorted(result, key=lambda x: x["spread_pct"], reverse=True)}

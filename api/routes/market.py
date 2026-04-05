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

    # Load fee table from DB (falls back to graph config if DB unavailable)
    cs = getattr(request.app.state.brain.persistence, "config_store", None)
    fee_table: dict = {}
    if cs and cs._pool:
        try:
            rows = await cs.get_all_fees()
            fee_table = {r["exchange"]: r["taker_pct"] for r in rows}
        except Exception:
            pass

    # Fallback to graph config fees
    gcfg = request.app.state.brain.config.graph
    def _taker(exchange: str) -> float:
        if exchange in fee_table:
            return fee_table[exchange]
        return gcfg.fee_for(exchange) * 100  # fee_for returns fraction, we want %

    result = []
    for pair in sorted(pairs):
        prices = ms.get_prices_for_pair(pair)
        if len(prices) < 2:
            continue
        entries = sorted(prices.items(), key=lambda x: x[1])
        buy_ex,  buy_price  = entries[0]
        sell_ex, sell_price = entries[-1]
        if buy_price <= 0:
            continue

        gross_pct = ((sell_price - buy_price) / buy_price) * 100
        # Net = gross - taker fee on buy - taker fee on sell
        fee_pct = _taker(buy_ex) + _taker(sell_ex)
        net_pct = gross_pct - fee_pct

        result.append({
            "pair":       pair,
            "spread_pct": round(gross_pct, 4),
            "net_pct":    round(net_pct, 4),
            "fee_pct":    round(fee_pct, 4),
            "buy_ex":     buy_ex,
            "buy_price":  buy_price,
            "sell_ex":    sell_ex,
            "sell_price": sell_price,
            "prices":     prices,
            "profitable": net_pct > 0,
        })
    return {"spreads": sorted(result, key=lambda x: x["spread_pct"], reverse=True)}

@router.get("/market/rejected")
async def get_rejected(request: Request):
    """Prices rejected by the outlier/zero filter — useful for diagnosing bad data."""
    ms = request.app.state.brain.market_state
    rejected = dict(ms._rejected)
    return {
        "total_rejections": sum(rejected.values()),
        "by_pair": sorted(
            [{"key": k, "count": v} for k, v in rejected.items()],
            key=lambda x: x["count"], reverse=True
        )
    }

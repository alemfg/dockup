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

    # Use the API's own config_store pool (same event loop as route handlers).
    # Never use brain.persistence.config_store here — it was created in the
    # brain's thread and causes "Future attached to a different loop" errors.
    fee_table: dict = {}
    try:
        api_cs = getattr(request.app.state, "api_config_store", None)
        if api_cs and api_cs._pool:
            rows = await api_cs.get_all_fees()
            fee_table = {r["exchange"]: r["taker_pct"] for r in rows}
    except Exception:
        pass  # silently fall back to graph config fees

    # Fallback to graph config fees
    gcfg = request.app.state.brain.config.graph
    def _taker(exchange: str) -> float:
        if exchange in fee_table:
            return fee_table[exchange]
        return gcfg.fee_for(exchange) * 100  # fee_for returns fraction, we want %

    # Build diagnostics: per-pair exchange coverage
    # pairs_single = pairs that only have 1 exchange (can't form a spread)
    all_prices     = ms.get_all_prices()
    pairs          = list({p["pair"] for p in all_prices})   # was missing — caused NameError
    active_exchanges = sorted({p["exchange"] for p in all_prices})
    pairs_single   = []
    pairs_multi    = []
    for pair in sorted(pairs):
        prices = ms.get_prices_for_pair(pair)
        if len(prices) < 2:
            pairs_single.append({"pair": pair, "exchanges": list(prices.keys())})
        else:
            pairs_multi.append(pair)

    result = []
    for pair in pairs_multi:
        prices = ms.get_prices_for_pair(pair)
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

    return {
        "spreads": sorted(result, key=lambda x: x["spread_pct"], reverse=True),
        # v6.4 diagnostic block — consumed by SpatialArbPanel empty state
        "diag": {
            "active_exchanges":  active_exchanges,
            "total_pairs":       len(pairs),
            "pairs_with_spread": len(pairs_multi),
            "pairs_single_exchange": len(pairs_single),
            "single_exchange_examples": pairs_single[:5],  # first 5 for UI hint
        },
    }

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


@router.get("/market/all-pairs")
async def get_all_pairs_spreads(request: Request):
    """
    v6.5: Returns spreads computed from ALL pairs currently in market_state,
    regardless of the configured PAIRS_ALL_QUOTE_FILTER.
    This is the "full range" mode toggled by the Spatial Arb panel.
    The data set is the same — it's just the filter that's lifted.
    If a pair only has 1 exchange it's still excluded (needs 2+ for a spread).
    """
    ms = request.app.state.brain.market_state
    # Use all pairs in memory, including any outside the quote filter
    all_prices = ms.get_all_prices()
    all_pairs  = list({p["pair"] for p in all_prices})

    cs = getattr(request.app.state.brain.persistence, "config_store", None)
    fee_table: dict = {}
    if cs and cs._pool:
        try:
            rows = await cs.get_all_fees()
            fee_table = {r["exchange"]: r["taker_pct"] for r in rows}
        except Exception:
            pass

    gcfg = request.app.state.brain.config.graph
    def _taker(exchange: str) -> float:
        if exchange in fee_table:
            return fee_table[exchange]
        return gcfg.fee_for(exchange) * 100

    result = []
    for pair in sorted(all_pairs):
        prices = ms.get_prices_for_pair(pair)
        if len(prices) < 2:
            continue
        entries = sorted(prices.items(), key=lambda x: x[1])
        buy_ex,  buy_price  = entries[0]
        sell_ex, sell_price = entries[-1]
        if buy_price <= 0:
            continue
        gross_pct = ((sell_price - buy_price) / buy_price) * 100
        fee_pct   = _taker(buy_ex) + _taker(sell_ex)
        net_pct   = gross_pct - fee_pct
        result.append({
            "pair": pair, "spread_pct": round(gross_pct, 4),
            "net_pct": round(net_pct, 4), "fee_pct": round(fee_pct, 4),
            "buy_ex": buy_ex, "buy_price": buy_price,
            "sell_ex": sell_ex, "sell_price": sell_price,
            "prices": prices, "profitable": net_pct > 0,
        })
    return {
        "spreads": sorted(result, key=lambda x: x["spread_pct"], reverse=True),
        "total_pairs_in_memory": len(all_pairs),
        "pairs_with_spread": len(result),
        "note": "Full range — all pairs in memory with 2+ exchanges, no quote filter applied",
    }

"""
Graph arbitrage API routes — multi-hop path results, graph state, and config.

New in v4.3:
  /graph/paths   — includes algorithm, fees, hub_assets, fw_status
  /graph/state   — includes per-exchange fee config from .env
  /graph/config  — read-only view of current GraphConfig values
"""
from fastapi import APIRouter, Request

router = APIRouter(tags=["Graph Arbitrage"])


@router.get("/graph/paths")
async def get_graph_paths(request: Request, limit: int = 20):
    """Latest profitable multi-hop paths found by the graph algorithm."""
    brain  = request.app.state.brain
    paths  = brain._graph_paths[:limit]
    status = brain.graph_arbitrage.status()

    return {
        "count":       len(paths),
        "algorithm":   status["algorithm"],
        "fw_status": {
            "interval_s":   status["fw_interval_s"],
            "last_run_ago": status["fw_last_run_ago"],
        },
        "config": {
            "max_hops":       status["max_hops"],
            "min_hops":       status["min_hops"],
            "min_profit_pct": status["min_profit_pct"],
            "start_asset":    status["start_asset"],
            "hub_assets":     status["hub_assets"],
            "capital_usd":    status["capital_usd"],
        },
        "paths": paths,
    }


@router.get("/graph/state")
async def get_graph_state(request: Request):
    """Current currency graph — nodes, edges, exchange coverage, and live fee config."""
    brain   = request.app.state.brain
    graph   = brain.currency_graph
    summary = graph.summary()

    # Build adjacency list for dashboard visualisation
    adjacency = {}
    for edge in graph.edges:
        key = edge.from_asset
        if key not in adjacency:
            adjacency[key] = []
        adjacency[key].append({
            "to":             edge.to_asset,
            "exchange":       edge.exchange,
            "effective_rate": round(edge.effective_rate, 8),
            "log_weight":     round(edge.log_weight, 6),
            "fee_pct":        round(edge.fee * 100, 4),
            "gas_usd":        round(edge.gas_usd, 3),
            "stale":          edge.is_stale(),
        })

    return {
        "summary":   summary,   # now includes fees, algorithm, hub_assets etc.
        "adjacency": adjacency,
    }


@router.get("/graph/config")
async def get_graph_config(request: Request):
    """
    Read-only view of the active GraphConfig.
    All values here are what the engine is actually using right now —
    after .env overrides have been applied.
    Call POST /config/reload/brain to pick up .env changes.
    """
    gcfg = request.app.state.brain.config.graph
    return {
        "algorithm":         gcfg.algorithm,
        "fw_interval_s":     gcfg.fw_interval_s,
        "max_hops":          gcfg.max_hops,
        "min_hops":          gcfg.min_hops,
        "min_profit_pct":    gcfg.min_profit_pct,
        "stale_edge_s":      gcfg.stale_edge_s,
        "start_asset":       gcfg.start_asset,
        "hub_assets":        gcfg.hub_assets,
        "capital_usd":       gcfg.capital_usd,
        "dex_max_gas_usd":   gcfg.dex_max_gas_usd,
        "fees_pct": {
            "binance":      gcfg.fee_binance_pct,
            "kraken":       gcfg.fee_kraken_pct,
            "bybit":        gcfg.fee_bybit_pct,
            "coinbase":     gcfg.fee_coinbase_pct,
            "uniswap":      gcfg.fee_uniswap_pct,
            "sushiswap":    gcfg.fee_sushiswap_pct,
            "pancakeswap":  gcfg.fee_pancakeswap_pct,
            "curve":        gcfg.fee_curve_pct,
        },
        "note": (
            "To change any of these values: update .env then call "
            "POST /api/config/reload/brain"
        ),
    }


@router.get("/graph/paths/best")
async def get_best_path(request: Request):
    """Returns the single highest net-profit path currently known."""
    brain = request.app.state.brain
    paths = brain._graph_paths
    if not paths:
        return {"path": None, "message": "No profitable paths found yet"}
    return {"path": paths[0]}

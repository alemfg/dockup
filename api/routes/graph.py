"""Graph arbitrage API routes — multi-hop path results and graph state."""
from fastapi import APIRouter, Request
router = APIRouter(tags=["Graph Arbitrage"])


@router.get("/graph/paths")
async def get_graph_paths(request: Request, limit: int = 20):
    """Latest profitable multi-hop paths found by the graph algorithm."""
    brain = request.app.state.brain
    paths = brain._graph_paths[:limit]
    return {
        "count":     len(paths),
        "algorithm": brain.graph_arbitrage._algorithm,
        "paths":     paths,
    }


@router.get("/graph/state")
async def get_graph_state(request: Request):
    """Current currency graph — nodes, edges, and exchange coverage."""
    brain = request.app.state.brain
    graph = brain.currency_graph
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
            "fee_pct":        round(edge.fee * 100, 3),
            "stale":          edge.is_stale(),
        })

    return {
        "summary":    summary,
        "adjacency":  adjacency,
    }


@router.get("/graph/paths/best")
async def get_best_path(request: Request):
    """Returns the single highest net-profit path currently known."""
    brain = request.app.state.brain
    paths = brain._graph_paths
    if not paths:
        return {"path": None, "message": "No profitable paths found yet"}
    return {"path": paths[0]}

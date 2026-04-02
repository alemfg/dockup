"""
Floyd-Warshall All-Pairs Arbitrage Detector.

Finds ALL profitable cycles across ALL pairs simultaneously in one pass.
Better than running Bellman-Ford from each source when you want a
complete picture of the graph's opportunities.

Time complexity: O(V³)
For 15 nodes: 3,375 ops — still microseconds.
For 30 nodes: 27,000 ops — still well under 1ms.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set

from arbitrage.graph.currency_graph import CurrencyGraph
from arbitrage.graph.models import ArbitragePath, GraphEdge
from messaging.logging import get_logger

logger = get_logger("arbitrage.graph.floyd_warshall")

_INF = float('inf')


def find_all_profitable_cycles(
    graph:          CurrencyGraph,
    max_hops:       int   = 5,
    min_hops:       int   = 3,
    min_profit_pct: float = 0.1,
    capital_usd:    float = 10_000.0,
    start_asset:    str   = "USDT",
) -> List[ArbitragePath]:
    """
    Floyd-Warshall all-pairs shortest path on log-transformed edge weights.
    Detects negative cycles = profitable arbitrage paths.

    Preferred over Bellman-Ford when you want a full map of all
    opportunities in one scan (e.g. every 5 seconds from the brain).
    """
    nodes    = graph.nodes
    edges    = graph.edges
    n        = len(nodes)

    if n < 3:
        return []

    node_idx: Dict[str, int] = {node: i for i, node in enumerate(nodes)}

    # ── Initialize distance matrix ────────────────────────────────────────────
    # dist[i][j] = best known log-weight from node i to node j
    dist = [[_INF] * n for _ in range(n)]
    # next_node[i][j] = next node on best path from i to j (for reconstruction)
    nxt  = [[-1]   * n for _ in range(n)]

    # Self-loops = 0
    for i in range(n):
        dist[i][i] = 0.0

    # Fill from edges — keep best (lowest log_weight) edge between each pair
    for edge in edges:
        u = node_idx.get(edge.from_asset, -1)
        v = node_idx.get(edge.to_asset,   -1)
        if u == -1 or v == -1:
            continue
        w = edge.log_weight
        if w < dist[u][v]:
            dist[u][v] = w
            nxt[u][v]  = v

    # ── Floyd-Warshall relaxation ─────────────────────────────────────────────
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if dist[i][k] != _INF and dist[k][j] != _INF:
                    if dist[i][k] + dist[k][j] < dist[i][j]:
                        dist[i][j] = dist[i][k] + dist[k][j]
                        nxt[i][j]  = nxt[i][k]

    # ── Detect negative cycles — check diagonal ────────────────────────────────
    # A negative cycle exists if dist[i][i] < 0 for any i
    found_paths: List[ArbitragePath] = []
    seen: Set[str] = set()

    for i in range(n):
        if dist[i][i] >= 0:
            continue    # no negative cycle through i

        # Reconstruct the cycle through i
        path = _reconstruct_fw_cycle(i, nodes, node_idx, graph, nxt, max_hops)
        if path is None:
            continue

        if path.path_string in seen:
            continue
        seen.add(path.path_string)

        if path.hops < min_hops:
            continue

        net = path.net_profit_pct(capital_usd)
        if net < min_profit_pct:
            continue

        found_paths.append(path)
        logger.debug(
            f"[FW] Path: {path.path_string} | "
            f"gross={path.gross_profit_pct:.3f}% | net={net:.3f}%"
        )

    found_paths.sort(key=lambda p: p.net_profit_pct(capital_usd), reverse=True)
    return found_paths


def _reconstruct_fw_cycle(
    start:    int,
    nodes:    List[str],
    node_idx: Dict[str, int],
    graph:    CurrencyGraph,
    nxt:      List[List[int]],
    max_hops: int,
) -> Optional[ArbitragePath]:
    """Reconstruct the cycle through node `start` using the next-node matrix."""
    cycle_nodes: List[str] = []
    cycle_edges: List[GraphEdge] = []
    visited:     Set[int] = set()

    current = start
    for _ in range(max_hops + 1):
        if current in visited:
            # Closed the cycle
            break
        visited.add(current)
        cycle_nodes.append(nodes[current])

        next_v = nxt[current][start]
        if next_v == -1:
            return None

        # Find real edge between current and next_v
        from_a = nodes[current]
        to_a   = nodes[next_v]
        candidates = [
            e for e in graph.edges
            if e.from_asset == from_a and e.to_asset == to_a and not e.is_stale()
        ]
        if not candidates:
            return None

        best_edge = min(candidates, key=lambda e: e.log_weight)
        cycle_edges.append(best_edge)
        current = next_v

    if len(cycle_nodes) < 2:
        return None

    # Close the cycle
    cycle_nodes.append(cycle_nodes[0])

    return ArbitragePath(assets=cycle_nodes, edges=cycle_edges)

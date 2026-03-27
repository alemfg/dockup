"""
Bellman-Ford Multi-Hop Arbitrage Detector.

Finds maximum-profit cycles in the currency graph by detecting
negative-weight cycles in the -log(effective_rate) transformed graph.

Key insight:
    Maximize:  r1 × r2 × r3 × r4   (product of rates)
    ≡ Minimize: -log(r1) - log(r2) - log(r3) - log(r4)  (sum of neg-logs)
    ≡ Find:    negative-weight cycle in Bellman-Ford

Time complexity: O(V × E) per source node = O(V² × E) total
For 15 nodes, 60 edges: ~900 × 60 = 54,000 ops — runs in microseconds.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple

from arbitrage.graph.currency_graph import CurrencyGraph
from arbitrage.graph.models import ArbitragePath, GraphEdge
from messaging.logging import get_logger

logger = get_logger("arbitrage.graph.bellman_ford")

_INF = float('inf')


def _reconstruct_cycle(
    pred:  List[int],
    start: int,
    nodes: List[str],
    edges: List[GraphEdge],
    node_idx: Dict[str, int],
    max_hops: int,
) -> Optional[List[int]]:
    """
    Walk the predecessor chain from a detected negative-cycle vertex.
    Returns ordered list of node indices forming the cycle, or None if invalid.
    """
    # Walk back (max_hops + 1) steps to ensure we're inside the cycle
    v = start
    for _ in range(len(nodes)):
        v = pred[v]
        if v == -1:
            return None

    # Now trace the cycle from v back to v
    cycle = []
    current = v
    visited: Set[int] = set()

    while current not in visited:
        visited.add(current)
        cycle.append(current)
        current = pred[current]
        if current == -1:
            return None
        if len(cycle) > max_hops + 1:
            return None    # cycle too long

    # Close the cycle
    cycle.append(current)
    cycle.reverse()

    # Rotate so cycle starts at the entry point
    entry = cycle.index(current)
    cycle = cycle[entry:] + cycle[entry + 1:]
    cycle.append(cycle[0])   # close: start == end

    return cycle if len(cycle) >= 3 else None    # min 2 hops = 3 nodes


def _build_path(
    cycle_indices: List[int],
    nodes:         List[str],
    graph:         CurrencyGraph,
) -> Optional[ArbitragePath]:
    """
    Convert a list of node indices into an ArbitragePath with real edges.
    Picks the best (lowest log-weight) edge between each consecutive pair.
    """
    path_assets: List[str] = [nodes[i] for i in cycle_indices]
    path_edges:  List[GraphEdge] = []

    for i in range(len(cycle_indices) - 1):
        from_asset = nodes[cycle_indices[i]]
        to_asset   = nodes[cycle_indices[i + 1]]

        # Find the best available edge between these two assets
        candidates = [
            e for e in graph.edges
            if e.from_asset == from_asset
            and e.to_asset   == to_asset
            and not e.is_stale()
        ]
        if not candidates:
            return None   # edge no longer available

        best_edge = min(candidates, key=lambda e: e.log_weight)
        path_edges.append(best_edge)

    if len(path_edges) != len(cycle_indices) - 1:
        return None

    return ArbitragePath(assets=path_assets, edges=path_edges)


def find_profitable_cycles(
    graph:               CurrencyGraph,
    max_hops:            int   = 5,
    min_profit_pct:      float = 0.1,
    capital_usd:         float = 10_000.0,
    start_asset:         str   = "USDT",
    allow_cross_exchange: bool  = True,
) -> List[ArbitragePath]:
    """
    Run Bellman-Ford from every node to detect all profitable cycles.

    Parameters
    ----------
    graph               : live CurrencyGraph
    max_hops            : maximum legs in a cycle (default 5)
    min_profit_pct      : minimum net profit % to surface (default 0.1)
    capital_usd         : trade size for net profit calculation
    start_asset         : prefer cycles returning to this asset (default USDT)
    allow_cross_exchange: allow hops across different exchanges (default True)

    Returns list of ArbitragePath objects sorted by net profit descending.
    """
    nodes      = graph.nodes
    edges      = graph.edges
    n          = len(nodes)

    if n < 3 or not edges:
        return []

    node_idx: Dict[str, int] = {node: i for i, node in enumerate(nodes)}

    found_paths: List[ArbitragePath]  = []
    seen_cycles: Set[str]             = set()   # dedup by path string

    # Run Bellman-Ford from every node as source
    for source_idx in range(n):
        dist = [_INF] * n
        pred = [-1]   * n
        dist[source_idx] = 0.0

        # Relax edges (n - 1) times
        for iteration in range(n - 1):
            updated = False
            for edge in edges:
                if not allow_cross_exchange:
                    # Skip edges that would require cross-exchange transfer
                    pass   # handled at path level below

                u = node_idx.get(edge.from_asset, -1)
                v = node_idx.get(edge.to_asset,   -1)
                if u == -1 or v == -1:
                    continue

                w = edge.log_weight
                if w == _INF:
                    continue

                if dist[u] != _INF and dist[u] + w < dist[v]:
                    dist[v] = dist[u] + w
                    pred[v] = u
                    updated = True

            if not updated:
                break   # converged early

        # One more relaxation pass to detect negative cycles
        for edge in edges:
            u = node_idx.get(edge.from_asset, -1)
            v = node_idx.get(edge.to_asset,   -1)
            if u == -1 or v == -1:
                continue

            w = edge.log_weight
            if w == _INF:
                continue

            if dist[u] != _INF and dist[u] + w < dist[v]:
                # Negative cycle detected starting at v
                cycle_indices = _reconstruct_cycle(
                    pred, v, nodes, edges, node_idx, max_hops
                )
                if cycle_indices is None:
                    continue

                path = _build_path(cycle_indices, nodes, graph)
                if path is None:
                    continue

                # Dedup
                if path.path_string in seen_cycles:
                    continue
                seen_cycles.add(path.path_string)

                # Filter: must be profitable after costs
                if path.net_profit_pct(capital_usd) < min_profit_pct:
                    continue

                # Filter: must not exceed max_hops
                if path.hops > max_hops:
                    continue

                # Filter: start/end asset preference
                if start_asset and path.assets[0] != start_asset:
                    # Rotate to start at preferred asset if possible
                    if start_asset in path.assets[:-1]:
                        idx = path.assets[:-1].index(start_asset)
                        rotated_assets = path.assets[idx:-1] + path.assets[:idx] + [start_asset]
                        rotated_edges  = path.edges[idx:] + path.edges[:idx]
                        path = ArbitragePath(assets=rotated_assets, edges=rotated_edges)
                    # If start_asset not in cycle, keep as-is but lower priority

                found_paths.append(path)
                logger.debug(
                    f"Path found: {path.path_string} | "
                    f"gross={path.gross_profit_pct:.3f}% | "
                    f"net={path.net_profit_pct(capital_usd):.3f}%"
                )

    # Sort by net profit descending
    found_paths.sort(key=lambda p: p.net_profit_pct(capital_usd), reverse=True)

    return found_paths

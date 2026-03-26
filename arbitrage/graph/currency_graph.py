"""
Currency Graph — live weighted directed graph of all assets.

Built in real-time as workers stream price ticks.
Each trading pair becomes two directed edges (buy + sell).
All costs (fee, slippage, gas) are baked into the edge weight.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from arbitrage.graph.models import GraphEdge
from messaging.logging import get_logger

logger = get_logger("arbitrage.graph.currency_graph")

# Per-exchange taker fee defaults
EXCHANGE_FEES: Dict[str, float] = {
    "binance":      0.001,
    "kraken":       0.0026,
    "coinbase":     0.006,
    "bybit":        0.001,
    "uniswap":      0.003,
    "sushiswap":    0.003,
    "pancakeswap":  0.0025,
    "curve":        0.0004,
}

# Gas costs per DEX (in USD) — 0 for CEX
EXCHANGE_GAS: Dict[str, float] = {
    "uniswap":      8.0,
    "sushiswap":    8.0,
    "pancakeswap":  2.0,
    "curve":        6.0,
}

# Slippage defaults per exchange type
EXCHANGE_SLIPPAGE: Dict[str, float] = {
    "binance":      0.0002,
    "kraken":       0.0003,
    "coinbase":     0.0005,
    "bybit":        0.0002,
    "uniswap":      0.003,
    "sushiswap":    0.003,
    "pancakeswap":  0.003,
    "curve":        0.0005,
}


class CurrencyGraph:
    """
    Live weighted directed graph of all tradeable assets.

    Nodes  = unique asset symbols seen across all workers
    Edges  = directed exchange rates with cost-adjusted weights
    """

    def __init__(self, stale_threshold_seconds: int = 30):
        # { (from_asset, to_asset, exchange) → GraphEdge }
        self._edges:  Dict[Tuple, GraphEdge] = {}
        self._nodes:  Set[str] = set()
        self._stale_threshold = stale_threshold_seconds

    # ─── Graph Building ───────────────────────────────────────────────────────

    def update_from_tick(
        self,
        exchange:    str,
        pair:        str,
        price:       float,
        volume_usd:  float = 10_000.0,
    ) -> None:
        """
        Called for every incoming price tick from a worker.
        Adds or updates two directed edges for the pair (both directions).
        """
        if "/" not in pair:
            return

        base, quote = pair.split("/", 1)   # "BTC/USDT" → ("BTC", "USDT")
        if price <= 0:
            return

        fee      = EXCHANGE_FEES.get(exchange,     0.001)
        gas      = EXCHANGE_GAS.get(exchange,      0.0)
        slippage = EXCHANGE_SLIPPAGE.get(exchange, 0.0005)

        # Direction 1: SELL base, GET quote   e.g. BTC → USDT  (rate = price)
        self._upsert(GraphEdge(
            from_asset=base,  to_asset=quote,
            exchange=exchange, rate=price,
            fee=fee, slippage=slippage, gas_usd=gas,
            volume_usd=volume_usd,
        ))

        # Direction 2: BUY base with quote   e.g. USDT → BTC  (rate = 1/price)
        self._upsert(GraphEdge(
            from_asset=quote, to_asset=base,
            exchange=exchange, rate=1.0 / price,
            fee=fee, slippage=slippage, gas_usd=gas,
            volume_usd=volume_usd,
        ))

        self._nodes.update([base, quote])

    def _upsert(self, edge: GraphEdge) -> None:
        self._edges[edge.key] = edge

    # ─── Stale Pruning ────────────────────────────────────────────────────────

    def prune_stale(self) -> int:
        """Remove edges older than stale_threshold. Returns count removed."""
        stale = [k for k, e in self._edges.items() if e.is_stale(self._stale_threshold)]
        for k in stale:
            del self._edges[k]

        # Rebuild node set from remaining edges
        self._nodes = set()
        for e in self._edges.values():
            self._nodes.update([e.from_asset, e.to_asset])

        if stale:
            logger.debug(f"Pruned {len(stale)} stale edges. Graph: {self.node_count} nodes, {self.edge_count} edges")
        return len(stale)

    # ─── Queries ─────────────────────────────────────────────────────────────

    @property
    def nodes(self) -> List[str]:
        return sorted(self._nodes)

    @property
    def edges(self) -> List[GraphEdge]:
        return list(self._edges.values())

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def get_edge(self, from_asset: str, to_asset: str, exchange: str) -> Optional[GraphEdge]:
        return self._edges.get((from_asset, to_asset, exchange))

    def get_edges_from(self, asset: str) -> List[GraphEdge]:
        return [e for e in self._edges.values() if e.from_asset == asset]

    def get_edges_to(self, asset: str) -> List[GraphEdge]:
        return [e for e in self._edges.values() if e.to_asset == asset]

    def summary(self) -> dict:
        return {
            "nodes":       self.node_count,
            "edges":       self.edge_count,
            "assets":      self.nodes,
            "exchanges":   sorted({e.exchange for e in self._edges.values()}),
        }

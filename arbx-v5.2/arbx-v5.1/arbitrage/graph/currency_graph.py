"""
Currency Graph — live weighted directed graph of all assets.

Built in real-time as workers stream price ticks.
Each trading pair becomes two directed edges (buy + sell).
All costs (fee, slippage, gas) are baked into the edge weight.

Fee rates are driven by config/.env (FEE_*_PCT variables) via GraphConfig.
Stale threshold is driven by GRAPH_STALE_EDGE_S.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from arbitrage.graph.models import GraphEdge
from messaging.logging import get_logger

if TYPE_CHECKING:
    from config.loader import GraphConfig

logger = get_logger("arbitrage.graph.currency_graph")

# ── Fallback defaults used when no config is injected ─────────────────────────
_DEFAULT_FEES: Dict[str, float] = {
    "binance":      0.00075,
    "kraken":       0.0016,
    "coinbase":     0.006,
    "bybit":        0.001,
    "uniswap":      0.003,
    "sushiswap":    0.003,
    "pancakeswap":  0.0025,
    "curve":        0.0004,
}

_DEFAULT_GAS: Dict[str, float] = {
    "uniswap":      8.0,
    "sushiswap":    8.0,
    "pancakeswap":  2.0,
    "curve":        6.0,
}

_DEFAULT_SLIPPAGE: Dict[str, float] = {
    "binance":      0.0002,
    "kraken":       0.0003,
    "coinbase":     0.0005,
    "bybit":        0.0002,
    "uniswap":      0.003,
    "sushiswap":    0.003,
    "pancakeswap":  0.003,
    "curve":        0.0005,
}

_DEX_EXCHANGES = {"uniswap", "sushiswap", "pancakeswap", "curve"}


class CurrencyGraph:
    """
    Live weighted directed graph of all tradeable assets.

    Nodes  = unique asset symbols seen across all workers
    Edges  = directed exchange rates with cost-adjusted weights

    Pass a GraphConfig on construction so that fees, stale threshold,
    and gas cap are driven by .env variables at runtime.
    """

    def __init__(
        self,
        stale_threshold_seconds: int = 30,
        graph_config=None,          # Optional[GraphConfig]
    ):
        self._edges:  Dict[Tuple, GraphEdge] = {}
        self._nodes:  Set[str] = set()
        self._stale_threshold = stale_threshold_seconds
        self._gcfg = graph_config   # may be None — falls back to defaults

    # ─── Config helpers ───────────────────────────────────────────────────────

    def _fee(self, exchange: str) -> float:
        if self._gcfg is not None:
            return self._gcfg.fee_for(exchange)
        return _DEFAULT_FEES.get(exchange, 0.001)

    def _gas(self, exchange: str) -> float:
        base = _DEFAULT_GAS.get(exchange, 0.0)
        if self._gcfg is not None and exchange in _DEX_EXCHANGES:
            # Cap gas at configured max
            return min(base, self._gcfg.dex_max_gas_usd)
        return base

    def _slippage(self, exchange: str) -> float:
        return _DEFAULT_SLIPPAGE.get(exchange, 0.0005)

    def _effective_stale(self) -> int:
        if self._gcfg is not None:
            return self._gcfg.stale_edge_s
        return self._stale_threshold

    def update_config(self, graph_config) -> None:
        """Hot-reload: replace the config reference at runtime."""
        self._gcfg = graph_config
        self._stale_threshold = graph_config.stale_edge_s

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

        base, quote = pair.split("/", 1)
        if price <= 0:
            return

        fee      = self._fee(exchange)
        gas      = self._gas(exchange)
        slippage = self._slippage(exchange)

        # Direction 1: SELL base, GET quote  e.g. BTC → USDT  (rate = price)
        self._upsert(GraphEdge(
            from_asset=base,  to_asset=quote,
            exchange=exchange, rate=price,
            fee=fee, slippage=slippage, gas_usd=gas,
            volume_usd=volume_usd,
        ))

        # Direction 2: BUY base with quote  e.g. USDT → BTC  (rate = 1/price)
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
        threshold = self._effective_stale()
        stale = [k for k, e in self._edges.items() if e.is_stale(threshold)]
        for k in stale:
            del self._edges[k]

        self._nodes = set()
        for e in self._edges.values():
            self._nodes.update([e.from_asset, e.to_asset])

        if stale:
            logger.debug(
                f"Pruned {len(stale)} stale edges "
                f"(threshold={threshold}s). "
                f"Graph: {self.node_count} nodes, {self.edge_count} edges"
            )
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
        gcfg = self._gcfg
        return {
            "nodes":          self.node_count,
            "edges":          self.edge_count,
            "assets":         self.nodes,
            "exchanges":      sorted({e.exchange for e in self._edges.values()}),
            "algorithm":      gcfg.algorithm        if gcfg else "bellman_ford",
            "stale_edge_s":   gcfg.stale_edge_s     if gcfg else self._stale_threshold,
            "min_profit_pct": gcfg.min_profit_pct   if gcfg else 0.25,
            "max_hops":       gcfg.max_hops          if gcfg else 5,
            "hub_assets":     gcfg.hub_assets        if gcfg else [],
            "fees": {
                ex: round(self._fee(ex) * 100, 4)
                for ex in sorted({e.exchange for e in self._edges.values()})
            },
        }

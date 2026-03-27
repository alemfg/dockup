"""
Graph Arbitrage Strategy — multi-hop maximum-profit path finder.

Uses Bellman-Ford / Floyd-Warshall on a live weighted currency graph
to find arbitrage cycles of 2–5 hops that maximize net profit.

Plugs into the existing BaseStrategy / scheduler architecture.
The brain's stream subscriber feeds price ticks into the CurrencyGraph
on every tick, and this strategy scans the graph every N seconds.

Example paths found:
  3-hop: USDT → BTC  → ETH  → USDT
  4-hop: USDT → BTC  → BNB  → SOL  → USDT
  5-hop: USDT → ETH  → BNB  → XRP  → SOL  → USDT
"""

from __future__ import annotations

from typing import List, Optional

from arbitrage.graph.bellman_ford import find_profitable_cycles
from arbitrage.graph.currency_graph import CurrencyGraph
from arbitrage.graph.floyd_warshall import find_all_profitable_cycles
from arbitrage.graph.path_validator import validate_many
from arbitrage.graph.models import ArbitragePath
from messaging.logging import get_logger
from messaging.models import Confidence, Opportunity, StrategyType

logger = get_logger("strategy.graph_arbitrage")


class GraphArbitrage:
    """
    Multi-hop arbitrage strategy using graph pathfinding algorithms.

    Configuration (from config.yaml):
        strategies:
          graph_arbitrage:
            enabled: true
            algorithm: "bellman_ford"   # or "floyd_warshall"
            max_hops: 5
            min_profit_pct: 0.1
            capital_usd: 10000
            start_asset: "USDT"
    """

    strategy_name = "graph_arbitrage"

    def __init__(self, config, graph: CurrencyGraph):
        self.config    = config
        self.graph     = graph
        self.logger    = get_logger("strategy.graph_arbitrage")

        # Read config values with safe defaults
        ga_cfg = getattr(config, "graph_arbitrage", None)
        self._algorithm     = getattr(ga_cfg, "algorithm",     "bellman_ford")
        self._max_hops      = getattr(ga_cfg, "max_hops",      5)
        self._min_profit    = getattr(ga_cfg, "min_profit_pct", 0.1)
        self._capital_usd   = getattr(ga_cfg, "capital_usd",   10_000.0)
        self._start_asset   = getattr(ga_cfg, "start_asset",   "USDT")

        # Fall back to trading config if graph_arbitrage section absent
        if not ga_cfg:
            self._min_profit  = config.trading.min_profit_percent
            self._capital_usd = config.trading.max_position_usd

    # ─── Main scan ────────────────────────────────────────────────────────────

    async def scan(self) -> List[Opportunity]:
        """Called by scheduler every N seconds."""

        # Prune stale edges before scanning
        self.graph.prune_stale()

        if self.graph.node_count < 3:
            return []

        # Run chosen algorithm
        if self._algorithm == "floyd_warshall":
            raw_paths = find_all_profitable_cycles(
                graph          = self.graph,
                max_hops       = self._max_hops,
                min_profit_pct = self._min_profit,
                capital_usd    = self._capital_usd,
                start_asset    = self._start_asset,
            )
        else:
            raw_paths = find_profitable_cycles(
                graph          = self.graph,
                max_hops       = self._max_hops,
                min_profit_pct = self._min_profit,
                capital_usd    = self._capital_usd,
                start_asset    = self._start_asset,
            )

        if not raw_paths:
            return []

        # Validate each path for execution feasibility
        valid_paths = validate_many(
            raw_paths,
            capital_usd    = self._capital_usd,
            min_profit_pct = self._min_profit,
        )

        if not valid_paths:
            return []

        # Convert to Opportunity objects for the existing pipeline
        opportunities = []
        for path in valid_paths:
            opp = self._path_to_opportunity(path)
            if opp:
                opportunities.append(opp)
                self.logger.info(
                    f"[GRAPH] {path.path_string} | "
                    f"{path.hops} hops | "
                    f"gross={path.gross_profit_pct:.3f}% | "
                    f"net={path.net_profit_pct(self._capital_usd):.3f}% | "
                    f"${path.net_profit_usd(self._capital_usd):.2f}"
                )

        return opportunities

    # ─── Conversion ──────────────────────────────────────────────────────────

    def _path_to_opportunity(self, path: ArbitragePath) -> Optional[Opportunity]:
        """Convert an ArbitragePath to the standard Opportunity dataclass."""
        if not path.edges:
            return None

        net_pct = path.net_profit_pct(self._capital_usd)
        net_usd = path.net_profit_usd(self._capital_usd)

        # For compatibility with existing ranking/alert pipeline,
        # use first and last exchange as buy/sell
        first_edge = path.edges[0]
        last_edge  = path.edges[-1]

        score = self._score_path(path)
        confidence = (
            Confidence.HIGH   if score >= 0.75 else
            Confidence.MEDIUM if score >= 0.50 else
            Confidence.LOW
        )

        return Opportunity(
            strategy             = StrategyType.TRIANGULAR,   # closest existing type
            pair                 = f"{path.assets[0]}/{path.assets[0]}",
            buy_exchange         = first_edge.exchange,
            sell_exchange        = last_edge.exchange,
            buy_price            = first_edge.rate,
            sell_price           = last_edge.rate,
            profit_percent       = net_pct,
            volume               = self._capital_usd / max(first_edge.rate, 1),
            estimated_profit_usd = net_usd,
            fee_estimate         = path.total_fee_pct / 100 * self._capital_usd,
            gas_estimate         = path.total_gas_usd,
            score                = score,
            confidence           = confidence,
            extra = {
                "strategy_type":    "graph_arbitrage",
                "algorithm":        self._algorithm,
                "path":             path.path_string,
                "assets":           path.assets,
                "hops":             path.hops,
                "exchanges":        path.exchanges_used,
                "gross_profit_pct": round(path.gross_profit_pct, 4),
                "net_profit_pct":   round(net_pct, 4),
                "net_profit_usd":   round(net_usd, 2),
                "total_fee_pct":    round(path.total_fee_pct, 4),
                "total_gas_usd":    round(path.total_gas_usd, 4),
                "edges":            [e.to_dict() for e in path.edges],
            },
        )

    def _score_path(self, path: ArbitragePath) -> float:
        """
        Score 0.0–1.0 for a graph path.
        Higher profit, fewer hops, and same-exchange paths score better.
        """
        # Profit contribution (50%)
        profit_score = min(path.net_profit_pct(self._capital_usd) / 3.0, 1.0)

        # Hop penalty (20%) — fewer hops = faster execution = higher score
        hop_score = max(0.0, 1.0 - (path.hops - 2) * 0.15)

        # Cross-exchange penalty (20%)
        unique_exchanges = len(set(path.exchanges_used))
        exchange_score = max(0.0, 1.0 - (unique_exchanges - 1) * 0.25)

        # Freshness (10%) — all edges fresh = 1.0
        import time
        max_age = max(
            (time.time() - e.timestamp.timestamp()) for e in path.edges
        )
        freshness_score = max(0.0, 1.0 - max_age / 30.0)

        return round(
            profit_score   * 0.50 +
            hop_score      * 0.20 +
            exchange_score * 0.20 +
            freshness_score * 0.10,
            4
        )

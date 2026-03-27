"""
Graph Arbitrage Strategy — multi-hop maximum-profit path finder.

Uses Bellman-Ford / Floyd-Warshall on a live weighted currency graph
to find arbitrage cycles of 2–5 hops that maximize net profit.

Configuration is driven entirely by config.graph (GraphConfig),
which is populated from .env variables — no hardcoded values here.

Algorithm behaviour:
  bellman_ford   — runs every scan tick (~5s). Low latency, detects
                   negative cycles from each source node in O(V²E).
  floyd_warshall — runs on its own scheduled interval (GRAPH_FW_INTERVAL_S,
                   default 45s). Computes full all-pairs distance matrix
                   O(V³), surfaces every profitable cycle simultaneously.
                   Results replace BF results when FW fires.

The switch (GRAPH_ALGORITHM env var) selects which algorithm drives the
live scan loop. When set to "bellman_ford", FW still runs in the background
on its interval as a cross-check. When set to "floyd_warshall", BF is
skipped and only FW results are surfaced.
"""

from __future__ import annotations

import asyncio
import time
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

    All parameters are read from config.graph (GraphConfig), which is
    populated from .env at startup and on every hot-reload.
    """

    strategy_name = "graph_arbitrage"

    def __init__(self, config, graph: CurrencyGraph):
        self.config  = config
        self.graph   = graph
        self._fw_last_run: float = 0.0   # timestamp of last FW run

    # ── Config properties (always read live so hot-reload takes effect) ───────

    @property
    def _gcfg(self):
        return self.config.graph

    @property
    def _algorithm(self) -> str:
        return self._gcfg.algorithm

    @property
    def _max_hops(self) -> int:
        return self._gcfg.max_hops

    @property
    def _min_hops(self) -> int:
        return self._gcfg.min_hops

    @property
    def _min_profit(self) -> float:
        return self._gcfg.min_profit_pct

    @property
    def _capital_usd(self) -> float:
        return self._gcfg.capital_usd

    @property
    def _start_asset(self) -> str:
        return self._gcfg.start_asset

    @property
    def _fw_interval(self) -> int:
        return self._gcfg.fw_interval_s

    # ─── Main scan ────────────────────────────────────────────────────────────

    async def scan(self) -> List[ArbitragePath]:
        """Called by brain's graph_scan_loop every N seconds."""
        self.graph.prune_stale()

        if self.graph.node_count < 3:
            return []

        now = time.monotonic()

        if self._algorithm == "floyd_warshall":
            # FW is the primary algorithm — run on every call
            raw_paths = self._run_floyd_warshall()
        else:
            # BF is primary; FW runs as background cross-check on its own interval
            raw_paths = self._run_bellman_ford()

            # Also fire FW in the background if its interval has elapsed
            if now - self._fw_last_run >= self._fw_interval:
                self._fw_last_run = now
                fw_paths = self._run_floyd_warshall()
                if fw_paths:
                    # Log any FW-only finds (cycles BF missed)
                    bf_keys = {p.path_string for p in raw_paths}
                    new = [p for p in fw_paths if p.path_string not in bf_keys]
                    if new:
                        logger.info(
                            f"[FW cross-check] found {len(new)} extra cycle(s) "
                            f"missed by Bellman-Ford: "
                            f"{', '.join(p.path_string for p in new[:3])}"
                        )
                    # Merge: FW results may include paths BF found and some it didn't
                    seen = {p.path_string for p in raw_paths}
                    for p in fw_paths:
                        if p.path_string not in seen:
                            raw_paths.append(p)
                            seen.add(p.path_string)
                    raw_paths.sort(
                        key=lambda p: p.net_profit_pct(self._capital_usd),
                        reverse=True
                    )

        if not raw_paths:
            return []

        valid_paths = validate_many(
            raw_paths,
            capital_usd    = self._capital_usd,
            min_profit_pct = self._min_profit,
        )

        for path in valid_paths[:3]:
            logger.info(
                f"[GRAPH/{self._algorithm.upper()[:2]}] {path.path_string} | "
                f"{path.hops} hops | "
                f"gross={path.gross_profit_pct:.3f}% | "
                f"net={path.net_profit_pct(self._capital_usd):.3f}% | "
                f"${path.net_profit_usd(self._capital_usd):.2f}"
            )

        return valid_paths

    def _run_bellman_ford(self) -> List[ArbitragePath]:
        try:
            return find_profitable_cycles(
                graph          = self.graph,
                max_hops       = self._max_hops,
                min_hops       = self._min_hops,
                min_profit_pct = self._min_profit,
                capital_usd    = self._capital_usd,
                start_asset    = self._start_asset,
            )
        except Exception as exc:
            logger.error(f"Bellman-Ford error: {exc}")
            return []

    def _run_floyd_warshall(self) -> List[ArbitragePath]:
        try:
            return find_all_profitable_cycles(
                graph          = self.graph,
                max_hops       = self._max_hops,
                min_hops       = self._min_hops,
                min_profit_pct = self._min_profit,
                capital_usd    = self._capital_usd,
                start_asset    = self._start_asset,
            )
        except Exception as exc:
            logger.error(f"Floyd-Warshall error: {exc}")
            return []

    # ─── Conversion ──────────────────────────────────────────────────────────

    def _path_to_opportunity(self, path: ArbitragePath) -> Optional[Opportunity]:
        if not path.edges:
            return None

        net_pct    = path.net_profit_pct(self._capital_usd)
        net_usd    = path.net_profit_usd(self._capital_usd)
        first_edge = path.edges[0]
        last_edge  = path.edges[-1]
        score      = self._score_path(path)
        confidence = (
            Confidence.HIGH   if score >= 0.75 else
            Confidence.MEDIUM if score >= 0.50 else
            Confidence.LOW
        )

        return Opportunity(
            strategy             = StrategyType.TRIANGULAR,
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
        profit_score    = min(path.net_profit_pct(self._capital_usd) / 3.0, 1.0)
        hop_score       = max(0.0, 1.0 - (path.hops - 2) * 0.15)
        unique_exchanges = len(set(path.exchanges_used))
        exchange_score  = max(0.0, 1.0 - (unique_exchanges - 1) * 0.25)
        max_age         = max(
            (time.time() - e.timestamp.timestamp()) for e in path.edges
        )
        freshness_score = max(0.0, 1.0 - max_age / 30.0)
        return round(
            profit_score    * 0.50 +
            hop_score       * 0.20 +
            exchange_score  * 0.20 +
            freshness_score * 0.10,
            4,
        )

    # ── Runtime state (for API) ───────────────────────────────────────────────

    def status(self) -> dict:
        """Expose current algorithm config for the /graph/paths endpoint."""
        gcfg = self._gcfg
        return {
            "algorithm":       gcfg.algorithm,
            "fw_interval_s":   gcfg.fw_interval_s,
            "fw_last_run_ago": round(time.monotonic() - self._fw_last_run, 1),
            "max_hops":        gcfg.max_hops,
            "min_hops":        gcfg.min_hops,
            "min_profit_pct":  gcfg.min_profit_pct,
            "stale_edge_s":    gcfg.stale_edge_s,
            "start_asset":     gcfg.start_asset,
            "hub_assets":      gcfg.hub_assets,
            "capital_usd":     gcfg.capital_usd,
            "fees": {
                "binance":     gcfg.fee_binance_pct,
                "kraken":      gcfg.fee_kraken_pct,
                "bybit":       gcfg.fee_bybit_pct,
                "coinbase":    gcfg.fee_coinbase_pct,
                "uniswap":     gcfg.fee_uniswap_pct,
            },
        }

"""
Currency Graph Models — data structures for the weighted directed graph.

Nodes  = currencies / assets (USDT, BTC, ETH, BNB, ...)
Edges  = exchange rates between pairs, with all costs baked in
Weights = -log(effective_rate) for Bellman-Ford negative-cycle detection
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import uuid4


# ─── Edge ─────────────────────────────────────────────────────────────────────

@dataclass
class GraphEdge:
    """
    A single directed exchange from one asset to another on one exchange.

    from_asset : "BTC"
    to_asset   : "USDT"
    exchange   : "binance"
    rate       : effective conversion rate BEFORE costs (e.g. 65000.0)
    fee        : taker fee as decimal (e.g. 0.001 = 0.1%)
    slippage   : estimated slippage as decimal (e.g. 0.0005)
    gas_usd    : gas cost in USD (0 for CEX, ~8 for DEX swap)
    volume_usd : available liquidity in USD (used for gas normalisation)
    """

    from_asset:  str
    to_asset:    str
    exchange:    str
    rate:        float
    fee:         float         = 0.001
    slippage:    float         = 0.0005
    gas_usd:     float         = 0.0
    volume_usd:  float         = 10_000.0
    timestamp:   datetime      = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def effective_rate(self) -> float:
        """
        Rate after fee, slippage, and gas costs.
        This is the real conversion rate you receive.
        """
        gas_pct = self.gas_usd / self.volume_usd if self.volume_usd > 0 else 0.0
        return self.rate * (1.0 - self.fee) * (1.0 - self.slippage) * (1.0 - gas_pct)

    @property
    def log_weight(self) -> float:
        """
        Negative log of effective rate — used as Bellman-Ford edge weight.
        A negative-weight cycle = profitable arbitrage path.
        """
        er = self.effective_rate
        if er <= 0:
            return float('inf')
        return -math.log(er)

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.from_asset, self.to_asset, self.exchange)

    def is_stale(self, max_age_seconds: int = 30) -> bool:
        age = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return age > max_age_seconds

    def to_dict(self) -> dict:
        return {
            "from":           self.from_asset,
            "to":             self.to_asset,
            "exchange":       self.exchange,
            "rate":           self.rate,
            "effective_rate": round(self.effective_rate, 8),
            "fee":            self.fee,
            "slippage":       self.slippage,
            "gas_usd":        self.gas_usd,
            "log_weight":     round(self.log_weight, 8),
            "timestamp":      self.timestamp.isoformat(),
        }


# ─── Path ─────────────────────────────────────────────────────────────────────

@dataclass
class ArbitragePath:
    """
    A complete multi-hop arbitrage cycle found by the graph algorithm.

    assets   : ordered list of assets visited  e.g. ["USDT","BTC","BNB","SOL","USDT"]
    edges    : ordered list of GraphEdge objects traversed
    """

    assets:       List[str]
    edges:        List[GraphEdge]
    id:           str = field(default_factory=lambda: str(uuid4())[:8])
    timestamp:    datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Computed properties ──────────────────────────────────────────────────

    @property
    def hops(self) -> int:
        return len(self.edges)

    @property
    def exchanges_used(self) -> List[str]:
        return [e.exchange for e in self.edges]

    @property
    def gross_product(self) -> float:
        """
        Product of all effective rates computed in log-space to avoid
        numerical overflow when raw rates span many orders of magnitude
        (e.g. BTC/USDT ≈ 85 000, USDT/BTC ≈ 0.0000118).

        log-space: sum(-log_weight) = log(product_of_effective_rates)
        Result is clamped to [-0.99, 5.0] (i.e. -99% to +500%) to prevent
        display bugs from stale or inconsistent prices.
        """
        import math
        log_sum = sum(e.log_weight for e in self.edges)  # sum of -log(er)
        # product = exp(sum of log(er)) = exp(-log_sum)
        # Guard: if log_sum is a large negative number the exp() overflows,
        # which means at least one edge has an extreme/stale rate.
        # Return 0.0 (unprofitable) so these phantom paths are filtered out
        # instead of being clamped to 6.0 (500%) and shown as real opportunities.
        if -log_sum > 20:   # exp(20) ≈ 485M — clearly bogus
            return 0.0
        try:
            product = math.exp(-log_sum)
        except OverflowError:
            return 0.0
        # Clamp to a tight sane range — no real arb exceeds ~5% on CEX
        # Upper cap of 1.5 (50%) allows for genuine new-listing premiums
        # while rejecting stale-data phantoms
        return max(0.0, min(1.5, product))

    @property
    def gross_profit_pct(self) -> float:
        return round((self.gross_product - 1.0) * 100.0, 4)

    @property
    def total_fee_pct(self) -> float:
        return sum(e.fee for e in self.edges) * 100.0

    @property
    def total_gas_usd(self) -> float:
        return sum(e.gas_usd for e in self.edges)

    @property
    def is_profitable(self) -> bool:
        return self.gross_product > 1.0

    @property
    def path_string(self) -> str:
        return " → ".join(self.assets)

    def net_profit_pct(self, capital_usd: float = 10_000.0) -> float:
        """Net profit after deducting gas costs from gross profit."""
        gross_usd = (self.gross_product - 1.0) * capital_usd
        net_usd   = gross_usd - self.total_gas_usd
        return (net_usd / capital_usd) * 100.0

    def net_profit_usd(self, capital_usd: float = 10_000.0) -> float:
        gross_usd = (self.gross_product - 1.0) * capital_usd
        return gross_usd - self.total_gas_usd

    def max_edge_age_s(self) -> float:
        """Age in seconds of the stalest edge in this path."""
        if not self.edges:
            return 0.0
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return max((now - e.timestamp).total_seconds() for e in self.edges)

    def to_dict(self, capital_usd: float = 10_000.0) -> dict:
        max_age = self.max_edge_age_s()
        return {
            "id":               self.id,
            "path":             self.path_string,
            "assets":           self.assets,
            "hops":             self.hops,
            "exchanges":        self.exchanges_used,
            "gross_product":    round(self.gross_product, 8),
            "gross_profit_pct": round(self.gross_profit_pct, 4),
            "net_profit_pct":   round(self.net_profit_pct(capital_usd), 4),
            "net_profit_usd":   round(self.net_profit_usd(capital_usd), 2),
            "total_fee_pct":    round(self.total_fee_pct, 4),
            "total_gas_usd":    round(self.total_gas_usd, 4),
            "max_edge_age_s":   round(max_age, 1),
            "is_stale":         max_age > 30,
            "edges":            [e.to_dict() for e in self.edges],
            "timestamp":        self.timestamp.isoformat(),
        }

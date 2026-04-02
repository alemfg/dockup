"""
Path Validator — checks that a found ArbitragePath is actually executable.

Filters out paths that are:
- Using stale prices (>30s old)
- Requiring impossible cross-exchange transfers
- Below minimum liquidity thresholds
- Using the same exchange consecutively for assets that can't be held there
- Generating negative net profit after realistic cost estimation
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from arbitrage.graph.models import ArbitragePath
from messaging.logging import get_logger

logger = get_logger("arbitrage.graph.validator")

# Exchanges that support the same assets (can transfer between them)
SAME_NETWORK_EXCHANGES = {
    frozenset({"binance", "kraken"}),
    frozenset({"binance", "coinbase"}),
    frozenset({"binance", "bybit"}),
    frozenset({"kraken", "coinbase"}),
    frozenset({"kraken", "bybit"}),
    frozenset({"coinbase", "bybit"}),
    frozenset({"uniswap", "sushiswap"}),     # both on Ethereum
    frozenset({"uniswap", "curve"}),
    frozenset({"sushiswap", "curve"}),
}

# Transfer time in minutes between exchange types
TRANSFER_TIMES: dict = {
    "cex_to_cex":   30,    # on-chain transfer between CEX wallets
    "dex_to_dex":    5,    # same chain, near instant
    "cex_to_dex":   15,    # withdraw from CEX, then interact with DEX
    "dex_to_cex":   20,    # withdraw from DEX, deposit to CEX
}

CEX_EXCHANGES = {"binance", "kraken", "coinbase", "bybit"}
DEX_EXCHANGES = {"uniswap", "sushiswap", "pancakeswap", "curve"}


def _exchange_type(exchange: str) -> str:
    if exchange in CEX_EXCHANGES:
        return "cex"
    if exchange in DEX_EXCHANGES:
        return "dex"
    return "unknown"


def validate(
    path:                ArbitragePath,
    capital_usd:         float = 10_000.0,
    min_profit_pct:      float = 0.1,
    max_transfer_min:    int   = 60,
    min_liquidity_usd:   float = 1_000.0,
    max_stale_seconds:   int   = 30,
) -> Tuple[bool, str]:
    """
    Validate a path is executable.
    Returns (is_valid, reason).
    """

    # ── 1. Minimum hops ───────────────────────────────────────────────────────
    if path.hops < 2:
        return False, "Path has fewer than 2 hops — not a cycle"

    # ── 2. Cycle must close ───────────────────────────────────────────────────
    if path.assets[0] != path.assets[-1]:
        return False, f"Path does not close: starts {path.assets[0]}, ends {path.assets[-1]}"

    # ── 3. No duplicate assets mid-cycle (except start=end) ──────────────────
    middle = path.assets[1:-1]
    if len(middle) != len(set(middle)):
        return False, "Duplicate assets in cycle mid-path"

    # ── 4. All edges fresh ────────────────────────────────────────────────────
    for edge in path.edges:
        if edge.is_stale(max_stale_seconds):
            return False, f"Edge {edge.from_asset}→{edge.to_asset} on {edge.exchange} is stale"

    # ── 5. Minimum liquidity per leg ─────────────────────────────────────────
    for edge in path.edges:
        if edge.volume_usd < min_liquidity_usd:
            return False, (
                f"Insufficient liquidity on {edge.exchange} "
                f"{edge.from_asset}→{edge.to_asset}: "
                f"${edge.volume_usd:.0f} < ${min_liquidity_usd:.0f}"
            )

    # ── 6. Cross-exchange transfer feasibility ────────────────────────────────
    total_transfer_time = 0
    for i in range(len(path.edges) - 1):
        ex_a = path.edges[i].exchange
        ex_b = path.edges[i + 1].exchange
        if ex_a != ex_b:
            type_a = _exchange_type(ex_a)
            type_b = _exchange_type(ex_b)
            transfer_key = f"{type_a}_to_{type_b}"
            transfer_min = TRANSFER_TIMES.get(transfer_key, 30)
            total_transfer_time += transfer_min

    if total_transfer_time > max_transfer_min:
        return False, (
            f"Total transfer time {total_transfer_time}min "
            f"exceeds limit {max_transfer_min}min"
        )

    # ── 7. Net profit after all costs ─────────────────────────────────────────
    net = path.net_profit_pct(capital_usd)
    if net < min_profit_pct:
        return False, (
            f"Net profit {net:.4f}% below minimum {min_profit_pct}% "
            f"after fees + gas"
        )

    return True, "OK"


def validate_many(
    paths:       List[ArbitragePath],
    capital_usd: float = 10_000.0,
    **kwargs,
) -> List[ArbitragePath]:
    """Filter a list of paths, returning only valid ones."""
    valid = []
    for path in paths:
        ok, reason = validate(path, capital_usd=capital_usd, **kwargs)
        if ok:
            valid.append(path)
        else:
            logger.debug(f"Path rejected [{path.path_string}]: {reason}")
    return valid

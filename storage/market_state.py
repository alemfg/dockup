"""
Market State — unified in-memory store for all market data.
Updated by the stream subscriber as worker data arrives.
Read by the API, strategies, and analysis engine.
"""
from __future__ import annotations

import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from messaging.logging import get_logger

logger = get_logger("storage.market_state")

# Prices deviating more than this multiple from the median are rejected.
# e.g. 10.0 means a price must be within 10x of the median across exchanges.
# This catches unit mismatches (BTC-denominated vs USDT-denominated prices).
_OUTLIER_THRESHOLD = float(os.getenv("PRICE_OUTLIER_THRESHOLD", "10.0"))


class MarketState:
    """
    Thread-safe (asyncio-safe) unified market data store.
    Holds the latest prices, orderbooks, candles, balances,
    and order results from all workers.
    """

    def __init__(self):
        # { "exchange:pair" → { price, worker_id, timestamp } }
        self._prices:     Dict[str, dict] = {}
        # { "exchange:pair:timeframe" → [candle, ...] }
        self._candles:    Dict[str, List[dict]] = defaultdict(list)
        # { "exchange:pair" → orderbook }
        self._orderbooks: Dict[str, dict] = {}
        # { "exchange:asset" → balance }
        self._balances:   Dict[str, dict] = {}
        # Recent order results
        self._order_results: List[dict] = []
        # Rejection counters per exchange:pair for diagnostics
        self._rejected: Dict[str, int] = defaultdict(int)

    # ─── Prices ──────────────────────────────────────────────────────────────

    def update_price(
        self, exchange: str, pair: str, price: float, worker_id: str = ""
    ) -> None:
        # ── Reject invalid prices ─────────────────────────────────────────────
        if not price or price <= 0:
            key = f"{exchange}:{pair}"
            self._rejected[key] += 1
            if self._rejected[key] == 1:
                logger.warning(f"[PriceFilter] Rejected zero/null price: {key} = {price}")
            return

        # ── Outlier filter (cross-unit mismatch guard) ────────────────────────
        # Compare the incoming price against all existing prices for this pair.
        # If the ratio vs the median exceeds _OUTLIER_THRESHOLD, reject it.
        # This runs even when there is only 1 existing price (not ≥2), so the
        # *second* price that arrives for a pair is always validated against the
        # first. This prevents LBank/MEXC 100-unit prices from polluting the
        # state when they are the first to report.
        existing = self.get_prices_for_pair(pair)
        if existing:
            vals = list(existing.values())
            try:
                med = statistics.median(vals) if len(vals) > 1 else vals[0]
                if med > 0:
                    ratio = price / med
                    if ratio > _OUTLIER_THRESHOLD or ratio < (1.0 / _OUTLIER_THRESHOLD):
                        key = f"{exchange}:{pair}"
                        self._rejected[key] += 1
                        if self._rejected[key] <= 3:
                            logger.warning(
                                f"[PriceFilter] Outlier rejected {key}: "
                                f"price={price:.6g} median={med:.6g} ratio={ratio:.2f}x "
                                f"(threshold={_OUTLIER_THRESHOLD}x)"
                            )
                        return
            except Exception:
                pass  # if stats fail, accept the price

        key = f"{exchange}:{pair}"
        # Reset rejection counter on successful update
        self._rejected.pop(key, None)
        self._prices[key] = {
            "exchange":  exchange,
            "pair":      pair,
            "price":     price,
            "worker_id": worker_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "updated_at": time.time(),
        }

    def get_price(self, exchange: str, pair: str) -> Optional[float]:
        entry = self._prices.get(f"{exchange}:{pair}")
        return entry["price"] if entry else None

    def get_prices_for_pair(self, pair: str) -> Dict[str, float]:
        # Snapshot items() first to avoid "dictionary changed size during iteration"
        # when workers write prices concurrently while the API reads them.
        return {
            k.split(":")[0]: v["price"]
            for k, v in list(self._prices.items())
            if k.endswith(f":{pair}")
        }

    def get_all_prices(self) -> List[dict]:
        return list(self._prices.values())

    def get_all_pairs(self) -> List[str]:
        return list({v["pair"] for v in list(self._prices.values())})

    def get_all_exchanges(self) -> List[str]:
        return list({v["exchange"] for v in self._prices.values()})

    def get_stale_pairs(self, threshold_s: int = 30) -> List[str]:
        now = time.time()
        return [
            k for k, v in list(self._prices.items())
            if (now - v.get("updated_at", 0)) > threshold_s
        ]

    # ─── Candles ─────────────────────────────────────────────────────────────

    def update_candle(
        self, exchange: str, pair: str, timeframe: str, candle: dict
    ) -> None:
        key = f"{exchange}:{pair}:{timeframe}"
        history = self._candles[key]
        history.append(candle)
        if len(history) > 200:
            self._candles[key] = history[-200:]

    def get_candles(
        self, exchange: str, pair: str, timeframe: str, limit: int = 100
    ) -> List[dict]:
        key = f"{exchange}:{pair}:{timeframe}"
        return self._candles[key][-limit:]

    # ─── Orderbooks ──────────────────────────────────────────────────────────

    def update_orderbook(self, exchange: str, pair: str, book: dict) -> None:
        self._orderbooks[f"{exchange}:{pair}"] = book

    def get_orderbook(self, exchange: str, pair: str) -> Optional[dict]:
        return self._orderbooks.get(f"{exchange}:{pair}")

    # ─── Balances ────────────────────────────────────────────────────────────

    def update_balance(
        self,
        exchange:  str,
        asset:     str,
        free:      float,
        locked:    float = 0.0,
        usd_value: float = 0.0,
        worker_id: str = "",
    ) -> None:
        key = f"{exchange}:{asset}"
        self._balances[key] = {
            "exchange":  exchange,
            "asset":     asset,
            "free":      free,
            "locked":    locked,
            "total":     free + locked,
            "usd_value": usd_value,
            "worker_id": worker_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_all_balances(self) -> List[dict]:
        return list(self._balances.values())

    def get_total_usd(self) -> float:
        return sum(b.get("usd_value", 0.0) for b in self._balances.values())

    def get_balances_by_exchange(self) -> Dict[str, List[dict]]:
        result: Dict[str, List[dict]] = defaultdict(list)
        for b in self._balances.values():
            result[b["exchange"]].append(b)
        return dict(result)

    def get_rebalance_suggestions(
        self,
        target_pct: Optional[Dict[str, float]] = None,
        threshold_pct: float = 5.0,
    ) -> List[dict]:
        """
        v3.2 — Compute suggested rebalance transfers.
        target_pct: {exchange: target_%} e.g. {"binance": 50, "kraken": 50}
        threshold_pct: minimum imbalance % before suggesting a transfer.
        Returns a list of suggested transfers for user approval.
        """
        total = self.get_total_usd()
        if total <= 0:
            return []

        by_exchange = self.get_balances_by_exchange()
        exchange_usd: Dict[str, float] = {
            ex: sum(b.get("usd_value", 0.0) for b in bals)
            for ex, bals in by_exchange.items()
        }

        # Default: equal distribution
        exchanges = list(exchange_usd.keys())
        if not exchanges:
            return []

        if not target_pct:
            equal = round(100.0 / len(exchanges), 2)
            target_pct = {ex: equal for ex in exchanges}

        suggestions = []
        for ex, current_usd in exchange_usd.items():
            current_pct = (current_usd / total) * 100
            target      = target_pct.get(ex, 100.0 / len(exchanges))
            diff_pct    = target - current_pct
            diff_usd    = abs(diff_pct / 100 * total)

            if abs(diff_pct) >= threshold_pct:
                suggestions.append({
                    "exchange":     ex,
                    "current_usd":  round(current_usd, 2),
                    "current_pct":  round(current_pct, 2),
                    "target_pct":   round(target, 2),
                    "diff_pct":     round(diff_pct, 2),
                    "action":       "deposit" if diff_pct > 0 else "withdraw",
                    "amount_usd":   round(diff_usd, 2),
                    "status":       "pending_approval",
                })

        return sorted(suggestions, key=lambda x: abs(x["diff_pct"]), reverse=True)

    # ─── Order Results ───────────────────────────────────────────────────────

    def record_order_result(self, result: dict) -> None:
        self._order_results.append(result)
        if len(self._order_results) > 1000:
            self._order_results.pop(0)

    def get_order_results(self, limit: int = 50) -> List[dict]:
        return list(reversed(self._order_results))[:limit]

    # ─── Summary ─────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "price_contexts":    len(self._prices),
            "candle_series":     len(self._candles),
            "orderbook_entries": len(self._orderbooks),
            "balance_entries":   len(self._balances),
            "total_usd":         round(self.get_total_usd(), 2),
            "stale_pairs":       len(self.get_stale_pairs()),
        }

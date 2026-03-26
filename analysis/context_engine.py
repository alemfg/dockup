"""
Context Engine — manages per-(exchange × pair) analysis contexts.
Each context has its own price history, plugin config, and signal output.
New contexts are created automatically when workers stream new pairs.
"""
from __future__ import annotations

import asyncio
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Any, Deque, Dict, List, Optional

# Import plugin modules so they self-register via @register decorator
import analysis.plugins.indicators  # noqa: F401 — triggers RSI/MACD/Bollinger registration
import analysis.plugins.cr_9am      # noqa: F401 — triggers CR9AM registration

from analysis.plugins.registry import get_enabled
from messaging.logging import get_logger
from messaging.models import Confidence, MarketSignal, PluginResult

logger = get_logger("analysis.context_engine")

HISTORY_SIZE = 500


@dataclass
class AnalysisContext:
    exchange:      str
    pair:          str
    plugin_config: dict
    price_history: Deque[float]            = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    candle_history: Dict[str, List[dict]]  = field(default_factory=lambda: {"1M": [], "15M": [], "1H": []})
    last_signal:   Optional[MarketSignal]  = None
    created_at:    datetime                = field(default_factory=lambda: datetime.now(timezone.utc))
    tick_count:    int                     = 0

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.pair}"

    @property
    def has_enough_data(self) -> bool:
        return len(self.price_history) >= 30


def _resolve_plugin_config(
    exchange: str,
    pair:     str,
    global_config: dict,
) -> dict:
    """
    Merge plugin configs in priority order:
    global defaults < exchange override < pair override < context override.
    More specific always wins.
    """
    def deep_merge(base: dict, override: dict) -> dict:
        result = dict(base)
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(result.get(k), dict):
                result[k] = deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    resolved = dict(global_config.get("plugins", {}))

    # Exchange-level override
    exchange_overrides = global_config.get("exchanges", {}).get(exchange, {})
    if exchange_overrides:
        resolved = deep_merge(resolved, exchange_overrides.get("plugins", {}))

    # Pair-level override
    pair_overrides = global_config.get("pairs", {}).get(pair, {})
    if pair_overrides:
        resolved = deep_merge(resolved, pair_overrides.get("plugins", {}))

    # Context-level override (most specific)
    ctx_key = f"{exchange}:{pair}"
    ctx_overrides = global_config.get("contexts", {}).get(ctx_key, {})
    if ctx_overrides:
        resolved = deep_merge(resolved, ctx_overrides.get("plugins", {}))

    # Always include cr_9am config
    if "cr_9am" in global_config:
        resolved["cr_9am"] = deep_merge(
            resolved.get("cr_9am", {}),
            global_config["cr_9am"],
        )

    return resolved


class ContextEngine:
    """
    Manages all analysis contexts and runs plugins per context.
    Called by the brain's stream subscriber when new ticks arrive.
    """

    def __init__(self, analysis_config: dict):
        self._config   = analysis_config
        self._contexts: Dict[str, AnalysisContext] = {}

    def _get_or_create(self, exchange: str, pair: str) -> AnalysisContext:
        key = f"{exchange}:{pair}"
        if key not in self._contexts:
            plugin_config = _resolve_plugin_config(exchange, pair, self._config)
            ctx = AnalysisContext(
                exchange=exchange,
                pair=pair,
                plugin_config=plugin_config,
            )
            self._contexts[key] = ctx
            logger.info(f"New analysis context: {key}")
        return self._contexts[key]

    async def on_price_tick(
        self,
        exchange: str,
        pair:     str,
        price:    float,
    ) -> Optional[MarketSignal]:
        """Called for every price tick. Returns updated signal if computed."""
        ctx = self._get_or_create(exchange, pair)
        ctx.price_history.append(price)
        ctx.tick_count += 1

        # Run analysis every 10 ticks to avoid thrashing
        if ctx.tick_count % 10 != 0:
            return ctx.last_signal

        if not ctx.has_enough_data:
            return None

        return await self._run_plugins(ctx)

    def on_candle(self, exchange: str, pair: str, timeframe: str, candle: dict) -> None:
        """Store candle data for strategies that need OHLCV."""
        ctx = self._get_or_create(exchange, pair)
        history = ctx.candle_history[timeframe]
        history.append(candle)
        # Keep last 200 candles per timeframe
        if len(history) > 200:
            ctx.candle_history[timeframe] = history[-200:]

    async def _run_plugins(self, ctx: AnalysisContext) -> Optional[MarketSignal]:
        """Run all enabled plugins for this context and aggregate results."""
        enabled_plugins = get_enabled(ctx.plugin_config)
        if not enabled_plugins:
            return None

        results: List[PluginResult] = []
        prices = list(ctx.price_history)

        for plugin in enabled_plugins:
            try:
                result = await plugin.run(
                    exchange=ctx.exchange,
                    pair=ctx.pair,
                    prices=prices,
                    candles=ctx.candle_history,
                )
                if result:
                    results.append(result)
            except Exception as exc:
                logger.warning(f"Plugin [{plugin.name}] failed for {ctx.key}: {exc}")

        if not results:
            return None

        signal = self._aggregate(ctx, results)
        ctx.last_signal = signal
        return signal

    def _aggregate(self, ctx: AnalysisContext, results: List[PluginResult]) -> MarketSignal:
        """Combine plugin results into a weighted composite signal."""
        total_weight = sum(r.weight for r in results)
        if total_weight == 0:
            total_weight = 1.0

        weighted_score = sum(
            r.signal_score * (r.weight / total_weight)
            for r in results
        )
        weighted_score = max(0.0, min(1.0, weighted_score))

        # Trend from predictor plugin if present
        trend = "NEUTRAL"
        for r in results:
            if r.signal_type in ("prediction", "cr_9am_setup"):
                direction = r.data.get("direction") or r.data.get("prediction_direction", "NEUTRAL")
                if direction in ("long", "BULLISH"):
                    trend = "BULLISH"
                elif direction in ("short", "BEARISH"):
                    trend = "BEARISH"
                break

        # Volatility from bollinger if present
        volatility = "MEDIUM"
        for r in results:
            if r.plugin == "bollinger_bands" and r.data:
                bw = r.data.get("band_width_pct", 2.0)
                volatility = "HIGH" if bw > 4.0 else "LOW" if bw < 1.0 else "MEDIUM"
                break

        confidence = (
            Confidence.HIGH   if weighted_score >= 0.75 else
            Confidence.MEDIUM if weighted_score >= 0.50 else
            Confidence.LOW
        )

        return MarketSignal(
            exchange=ctx.exchange,
            pair=ctx.pair,
            signal_score=round(weighted_score, 4),
            confidence=confidence,
            trend=trend,
            volatility=volatility,
            plugin_results=results,
        )

    def get_signal(self, exchange: str, pair: str) -> Optional[MarketSignal]:
        ctx = self._contexts.get(f"{exchange}:{pair}")
        return ctx.last_signal if ctx else None

    def get_all_signals(self) -> List[MarketSignal]:
        return [
            ctx.last_signal
            for ctx in self._contexts.values()
            if ctx.last_signal
        ]

    def get_all_contexts(self) -> List[dict]:
        return [
            {
                "key":         ctx.key,
                "exchange":    ctx.exchange,
                "pair":        ctx.pair,
                "tick_count":  ctx.tick_count,
                "data_points": len(ctx.price_history),
                "has_signal":  ctx.last_signal is not None,
                "signal_score": ctx.last_signal.signal_score if ctx.last_signal else None,
                "plugins_active": len(get_enabled(ctx.plugin_config)),
                "created_at":  ctx.created_at.isoformat(),
            }
            for ctx in self._contexts.values()
        ]

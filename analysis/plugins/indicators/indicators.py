"""
Technical Indicator Plugins (v4)
Implements RSI, MACD, and Bollinger Bands as AnalysisPlugin subclasses.
All use only price history (no external dependencies beyond stdlib + numpy).
numpy is already a transitive dependency of ccxt/pandas.
"""
from __future__ import annotations

import math
from typing import List, Optional, Dict

from analysis.plugins.registry import AnalysisPlugin, register
from messaging.models import PluginResult
from messaging.logging import get_logger

logger = get_logger("analysis.indicators")


def _ema(prices: List[float], period: int) -> List[float]:
    """Exponential moving average."""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for p in prices[period:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema


def _sma(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return 0.0
    return sum(prices[-period:]) / period


def _stdev(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return 0.0
    window = prices[-period:]
    mean   = sum(window) / period
    return math.sqrt(sum((p - mean) ** 2 for p in window) / period)


# ─── RSI ─────────────────────────────────────────────────────────────────────

@register
class RSIPlugin(AnalysisPlugin):
    """
    Relative Strength Index.
    Config params: period (default 14), overbought (70), oversold (30).
    Signal: 1.0 = extremely oversold (strong buy), 0.0 = extremely overbought (strong sell),
            0.5 = neutral.
    """

    name = "rsi"
    enabled_by_default = True

    def __init__(self):
        super().__init__()
        self._period      = 14
        self._overbought  = 70.0
        self._oversold    = 30.0
        self._weight      = 0.15

    def apply_config(self, config: dict) -> None:
        super().apply_config(config)
        p = config.get("params", config)
        self._period     = int(p.get("period",     self._period))
        self._overbought = float(p.get("overbought", self._overbought))
        self._oversold   = float(p.get("oversold",   self._oversold))

    async def run(
        self,
        exchange: str, pair: str,
        prices: List[float],
        candles: Optional[Dict] = None,
        extra: Optional[dict] = None,
    ) -> Optional[PluginResult]:
        if len(prices) < self._period + 1:
            return None

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains  = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]

        avg_gain = sum(gains[-self._period:]) / self._period
        avg_loss = sum(losses[-self._period:]) / self._period

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs  = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # Convert RSI to signal score
        # Oversold → high score (bullish), Overbought → low score (bearish)
        if rsi <= self._oversold:
            score = 1.0 - (rsi / self._oversold) * 0.3  # 0.7–1.0
        elif rsi >= self._overbought:
            score = (100 - rsi) / (100 - self._overbought) * 0.3  # 0.0–0.3
        else:
            # Neutral zone — scale 0.3–0.7
            score = 0.3 + ((self._overbought - rsi) / (self._overbought - self._oversold)) * 0.4

        score = max(0.0, min(1.0, score))
        direction = "BULLISH" if rsi < 50 else "BEARISH"

        return PluginResult(
            plugin=self.name,
            signal_score=round(score, 4),
            weight=self._weight,
            data={
                "rsi":           round(rsi, 2),
                "period":        self._period,
                "overbought":    self._overbought,
                "oversold":      self._oversold,
                "direction":     direction,
                "signal":        "oversold" if rsi <= self._oversold else
                                 "overbought" if rsi >= self._overbought else "neutral",
            },
            signal_type="rsi",
        )


# ─── MACD ─────────────────────────────────────────────────────────────────────

@register
class MACDPlugin(AnalysisPlugin):
    """
    Moving Average Convergence Divergence.
    Config params: fast (12), slow (26), signal (9).
    Signal: histogram crossover above/below zero line.
    """

    name = "macd"
    enabled_by_default = True

    def __init__(self):
        super().__init__()
        self._fast   = 12
        self._slow   = 26
        self._signal = 9
        self._weight = 0.15

    def apply_config(self, config: dict) -> None:
        super().apply_config(config)
        p = config.get("params", config)
        self._fast   = int(p.get("fast",   self._fast))
        self._slow   = int(p.get("slow",   self._slow))
        self._signal = int(p.get("signal", self._signal))

    async def run(
        self,
        exchange: str, pair: str,
        prices: List[float],
        candles: Optional[Dict] = None,
        extra: Optional[dict] = None,
    ) -> Optional[PluginResult]:
        min_len = self._slow + self._signal + 1
        if len(prices) < min_len:
            return None

        ema_fast = _ema(prices, self._fast)
        ema_slow = _ema(prices, self._slow)

        # Align to same length
        offset    = len(ema_fast) - len(ema_slow)
        ema_fast  = ema_fast[offset:]
        macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]

        if len(macd_line) < self._signal:
            return None

        sig_line  = _ema(macd_line, self._signal)
        histogram = [m - s for m, s in zip(macd_line[-len(sig_line):], sig_line)]

        if len(histogram) < 2:
            return None

        curr_hist = histogram[-1]
        prev_hist = histogram[-2]
        curr_macd = macd_line[-1]

        # Bullish: histogram positive and growing, or just crossed above zero
        # Bearish: histogram negative and falling, or just crossed below zero
        bullish_cross = prev_hist <= 0 < curr_hist
        bearish_cross = prev_hist >= 0 > curr_hist
        histogram_growing   = curr_hist > prev_hist
        histogram_shrinking = curr_hist < prev_hist

        if bullish_cross or (curr_hist > 0 and histogram_growing):
            score = 0.65 + (0.20 if bullish_cross else 0.0)
            direction = "BULLISH"
        elif bearish_cross or (curr_hist < 0 and histogram_shrinking):
            score = 0.35 - (0.20 if bearish_cross else 0.0)
            direction = "BEARISH"
        else:
            score     = 0.5
            direction = "NEUTRAL"

        score = max(0.0, min(1.0, score))

        return PluginResult(
            plugin=self.name,
            signal_score=round(score, 4),
            weight=self._weight,
            data={
                "macd":           round(curr_macd, 6),
                "signal_line":    round(sig_line[-1], 6),
                "histogram":      round(curr_hist, 6),
                "prev_histogram": round(prev_hist, 6),
                "direction":      direction,
                "signal":         "bullish_cross" if bullish_cross else
                                  "bearish_cross" if bearish_cross else
                                  "bullish" if direction == "BULLISH" else
                                  "bearish" if direction == "BEARISH" else "neutral",
            },
            signal_type="macd",
        )


# ─── Bollinger Bands ──────────────────────────────────────────────────────────

@register
class BollingerBandsPlugin(AnalysisPlugin):
    """
    Bollinger Bands (SMA ± N standard deviations).
    Config params: period (20), std_dev (2.0).
    Signal: price near lower band → bullish, near upper band → bearish,
    band width used for volatility classification.
    """

    name = "bollinger_bands"
    enabled_by_default = True

    def __init__(self):
        super().__init__()
        self._period  = 20
        self._std_dev = 2.0
        self._weight  = 0.10

    def apply_config(self, config: dict) -> None:
        super().apply_config(config)
        p = config.get("params", config)
        self._period  = int(p.get("period",  self._period))
        self._std_dev = float(p.get("std_dev", self._std_dev))

    async def run(
        self,
        exchange: str, pair: str,
        prices: List[float],
        candles: Optional[Dict] = None,
        extra: Optional[dict] = None,
    ) -> Optional[PluginResult]:
        if len(prices) < self._period:
            return None

        mid   = _sma(prices, self._period)
        std   = _stdev(prices, self._period)
        upper = mid + self._std_dev * std
        lower = mid - self._std_dev * std
        price = prices[-1]

        if upper == lower:
            return None

        # Position within band (0 = at lower, 1 = at upper)
        band_position = (price - lower) / (upper - lower)
        band_position = max(0.0, min(1.0, band_position))

        # Band width as % of mid price (volatility proxy)
        band_width_pct = ((upper - lower) / mid) * 100

        # Score: price at lower band → bullish (0.7–1.0),
        #        price at upper band → bearish (0.0–0.3),
        #        middle → neutral (0.4–0.6)
        if band_position <= 0.2:
            score     = 0.7 + (0.2 - band_position) * 1.5
            direction = "BULLISH"
            signal    = "near_lower_band"
        elif band_position >= 0.8:
            score     = 0.3 - (band_position - 0.8) * 1.5
            direction = "BEARISH"
            signal    = "near_upper_band"
        else:
            score     = 0.5
            direction = "NEUTRAL"
            signal    = "mid_band"

        score = max(0.0, min(1.0, score))

        return PluginResult(
            plugin=self.name,
            signal_score=round(score, 4),
            weight=self._weight,
            data={
                "upper":          round(upper, 6),
                "middle":         round(mid, 6),
                "lower":          round(lower, 6),
                "price":          round(price, 6),
                "band_position":  round(band_position, 4),
                "band_width_pct": round(band_width_pct, 4),
                "direction":      direction,
                "signal":         signal,
            },
            signal_type="bollinger_bands",
        )

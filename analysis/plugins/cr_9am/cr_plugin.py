"""
9AM CR (Candle Range) Plugin — ICT-based intraday model.

Time-gated: only active 09:00–10:30 NY time.
Uses nested timeframe ranges (8AM 1H + 9:15 15M) to identify
high-probability reversals after a range sweep.

Steps:
  1. Mark 8AM 1H candle range (HTF)
  2. Mark 9:15 15M candle range (LTF, nested inside HTF)
  3. Wait for price to sweep one side of the LTF range
  4. Look for BOS + OB + FVG in reversal direction
  5. Enter on confirmed FVG/OB in discount/premium zone
  6. TP1 = opposite LTF range end, TP2 = opposite HTF range end
"""
from __future__ import annotations

import pytz
from datetime import datetime
from typing import Dict, List, Optional

from analysis.plugins.registry import AnalysisPlugin, register
from messaging.logging import get_logger
from messaging.models import (
    CRRange, CRSignal, FVG, OrderBlock, PluginResult, Sweep,
)

logger = get_logger("analysis.cr_9am")


# ─── Range Builder ───────────────────────────────────────────────────────────

class RangeBuilder:
    def __init__(self, tz_name: str):
        self._tz = pytz.timezone(tz_name)

    def build_htf(self, candles_1h: List[dict]) -> Optional[CRRange]:
        """Find 8AM 1H candle → HTF range."""
        for c in candles_1h:
            t = self._local(c["time"])
            if t.hour == 8 and t.minute == 0:
                return CRRange(
                    timeframe="1H", candle_time=t,
                    high=c["high"], low=c["low"],
                )
        return None

    def build_ltf(self, candles_15m: List[dict]) -> Optional[CRRange]:
        """Find 9:00 15M candle → LTF range (the '9:15 range')."""
        for c in candles_15m:
            t = self._local(c["time"])
            if t.hour == 9 and t.minute == 0:
                return CRRange(
                    timeframe="15M", candle_time=t,
                    high=c["high"], low=c["low"],
                )
        return None

    def _local(self, ts) -> datetime:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, tz=pytz.utc)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts).replace(tzinfo=pytz.utc)
        else:
            dt = ts if ts.tzinfo else ts.replace(tzinfo=pytz.utc)
        return dt.astimezone(self._tz)


# ─── Sweep Detector ──────────────────────────────────────────────────────────

class SweepDetector:
    def detect(self, candles_1m: List[dict], ltf: CRRange) -> Optional[Sweep]:
        """
        Sweep = wick beyond range high/low, then close back inside.
        """
        for c in candles_1m:
            # High sweep → bearish reversal setup
            if c["high"] > ltf.high and c["close"] < ltf.high:
                return Sweep(
                    direction="high_sweep",
                    sweep_price=c["high"],
                    sweep_time=self._ts(c["time"]),
                    range_level=ltf.high,
                    confirmed=True,
                )
            # Low sweep → bullish reversal setup
            if c["low"] < ltf.low and c["close"] > ltf.low:
                return Sweep(
                    direction="low_sweep",
                    sweep_price=c["low"],
                    sweep_time=self._ts(c["time"]),
                    range_level=ltf.low,
                    confirmed=True,
                )
        return None

    def _ts(self, t) -> datetime:
        if isinstance(t, datetime):
            return t
        if isinstance(t, (int, float)):
            return datetime.fromtimestamp(t / 1000 if t > 1e10 else t)
        return datetime.fromisoformat(str(t))


# ─── Structure Detector ──────────────────────────────────────────────────────

class StructureDetector:

    def detect_bos(self, candles_1m: List[dict], sweep: Sweep) -> bool:
        """Break of Structure after sweep."""
        lookback = candles_1m[-15:]
        if sweep.direction == "high_sweep":
            # Bearish BOS: close below recent swing low
            recent_low = min(c["low"] for c in lookback)
            return any(c["close"] < recent_low for c in candles_1m[-5:])
        if sweep.direction == "low_sweep":
            # Bullish BOS: close above recent swing high
            recent_high = max(c["high"] for c in lookback)
            return any(c["close"] > recent_high for c in candles_1m[-5:])
        return False

    def detect_ob(self, candles_1m: List[dict], sweep: Sweep) -> Optional[OrderBlock]:
        """Last opposing candle before the impulse that caused the sweep."""
        if sweep.direction == "high_sweep":
            # Last bullish (green) candle → bearish OB
            for c in reversed(candles_1m[-20:]):
                if c["close"] > c["open"]:
                    return OrderBlock(
                        direction="bearish_ob",
                        high=c["high"], low=c["low"],
                        open=c["open"], close=c["close"],
                        time=self._ts(c["time"]),
                    )
        if sweep.direction == "low_sweep":
            # Last bearish (red) candle → bullish OB
            for c in reversed(candles_1m[-20:]):
                if c["close"] < c["open"]:
                    return OrderBlock(
                        direction="bullish_ob",
                        high=c["high"], low=c["low"],
                        open=c["open"], close=c["close"],
                        time=self._ts(c["time"]),
                    )
        return None

    def detect_fvg(
        self,
        candles_1m: List[dict],
        sweep: Sweep,
        min_size_pct: float = 0.0001,
    ) -> Optional[FVG]:
        """
        FVG = 3-candle imbalance after sweep.
        Requires 2nd candle to have closed (confirmation).
        """
        post = [c for c in candles_1m if self._ts(c["time"]) >= sweep.sweep_time]
        if len(post) < 3:
            return None

        for i in range(1, len(post) - 1):
            c1, c2, c3 = post[i - 1], post[i], post[i + 1]

            if sweep.direction == "low_sweep":
                # Bullish FVG: gap between c1 high and c3 low
                if c3["low"] > c1["high"]:
                    size = c3["low"] - c1["high"]
                    if size / c1["high"] >= min_size_pct:
                        return FVG(
                            direction="bullish_fvg",
                            top=c3["low"], bottom=c1["high"],
                            time=self._ts(c2["time"]),
                            confirmed=True,
                        )
            if sweep.direction == "high_sweep":
                # Bearish FVG: gap between c1 low and c3 high
                if c3["high"] < c1["low"]:
                    size = c1["low"] - c3["high"]
                    if size / c1["low"] >= min_size_pct:
                        return FVG(
                            direction="bearish_fvg",
                            top=c1["low"], bottom=c3["high"],
                            time=self._ts(c2["time"]),
                            confirmed=True,
                        )
        return None

    def _ts(self, t) -> datetime:
        if isinstance(t, datetime):
            return t
        if isinstance(t, (int, float)):
            return datetime.fromtimestamp(t / 1000 if t > 1e10 else t)
        return datetime.fromisoformat(str(t))


# ─── Entry Validator ─────────────────────────────────────────────────────────

class EntryValidator:

    def validate(
        self,
        sweep: Sweep,
        htf: CRRange,
        ltf: CRRange,
        bos: bool,
        ob: Optional[OrderBlock],
        fvg: Optional[FVG],
        current_price: float,
    ) -> Optional[dict]:

        direction = "long" if sweep.direction == "low_sweep" else "short"
        notes, score = [], 0.0

        # Sweep confirmed (required)
        score += 0.20
        notes.append(f"{'Low' if direction == 'long' else 'High'} swept ✅")

        # BOS
        if bos:
            score += 0.20
            notes.append("BOS confirmed ✅")
        else:
            notes.append("BOS pending ⏳")

        # OB
        if ob and not ob.violated:
            score += 0.15
            notes.append(f"OB at {ob.low:.5f}–{ob.high:.5f} ✅")

        # FVG
        if fvg and fvg.confirmed and not fvg.filled:
            score += 0.20
            notes.append(f"FVG confirmed {fvg.bottom:.5f}–{fvg.top:.5f} ✅")

        # IFVG + OB alignment
        ifvg_ob = False
        if ob and fvg and not fvg.filled:
            overlap = (
                max(ob.low, fvg.bottom) < min(ob.high, fvg.top)
            )
            if overlap:
                ifvg_ob = True
                score += 0.10
                notes.append("IFVG + OB alignment ✅ (strongest)")

        # Discount/premium check
        if direction == "long" and ltf.is_discount(current_price):
            score += 0.15
            notes.append("Price in discount ✅")
        elif direction == "short" and ltf.is_premium(current_price):
            score += 0.15
            notes.append("Price in premium ✅")
        else:
            notes.append("Price zone suboptimal ⚠️")

        # Need at least OB or FVG for entry zone
        if not ob and not fvg:
            return None

        # Build entry zone
        if fvg and fvg.confirmed:
            entry_price  = fvg.midpoint
            entry_top    = fvg.top
            entry_bottom = fvg.bottom
        else:
            entry_price  = (ob.high + ob.low) / 2
            entry_top    = ob.high
            entry_bottom = ob.low

        # Stop loss beyond sweep extreme with small buffer
        buf = ltf.size * 0.10
        if direction == "long":
            stop_loss = sweep.sweep_price - buf
            tp1 = ltf.high
            tp2 = htf.high
        else:
            stop_loss = sweep.sweep_price + buf
            tp1 = ltf.low
            tp2 = htf.low

        if score < 0.40:
            return None

        confidence = "HIGH" if score >= 0.75 else "MEDIUM" if score >= 0.55 else "LOW"

        return {
            "direction":         direction,
            "entry_price":       entry_price,
            "entry_zone_top":    entry_top,
            "entry_zone_bottom": entry_bottom,
            "stop_loss":         stop_loss,
            "tp1":               tp1,
            "tp2":               tp2,
            "bos_confirmed":     bos,
            "ifvg_ob_alignment": ifvg_ob,
            "order_block":       ob,
            "fvg":               fvg,
            "setup_score":       round(score, 3),
            "confidence":        confidence,
            "notes":             notes,
        }


# ─── Plugin ──────────────────────────────────────────────────────────────────

@register
class CR9AMPlugin(AnalysisPlugin):
    """
    9AM CR model — time-gated, per-pair, self-registering plugin.
    """

    name = "cr_9am"
    enabled_by_default = False

    def __init__(self):
        super().__init__()
        self._weight      = 0.30
        self._timezone    = "America/New_York"
        self._active_from = 9
        self._active_to   = 10
        self._min_score   = 0.55
        self._pairs       = ["BTC/USDT", "ETH/USDT"]
        self._tz          = pytz.timezone(self._timezone)

        self._range_builder = RangeBuilder(self._timezone)
        self._sweep         = SweepDetector()
        self._structure     = StructureDetector()
        self._validator     = EntryValidator()

        # Per-pair daily state
        self._state: Dict[str, dict] = {}

    def apply_config(self, config: dict) -> None:
        super().apply_config(config)
        p = config.get("params", config)
        self._timezone    = p.get("timezone",         self._timezone)
        self._active_from = p.get("active_from_hour", self._active_from)
        self._active_to   = p.get("active_to_hour",   self._active_to)
        self._min_score   = p.get("min_setup_score",  self._min_score)
        self._pairs       = p.get("pairs",             self._pairs)
        self._tz          = pytz.timezone(self._timezone)
        self._range_builder = RangeBuilder(self._timezone)

    def _is_active(self) -> bool:
        now = datetime.now(self._tz)
        return self._active_from <= now.hour < self._active_to

    def _today(self):
        return datetime.now(self._tz).date()

    def _reset_if_new_day(self, pair: str) -> None:
        state = self._state.get(pair, {})
        if state.get("date") != self._today():
            self._state[pair] = {
                "date":      self._today(),
                "htf_range": None,
                "ltf_range": None,
                "sweep":     None,
                "signal":    None,
            }

    async def run(
        self,
        exchange:  str,
        pair:      str,
        prices:    List[float],
        candles:   Optional[Dict[str, List[dict]]] = None,
        extra:     Optional[dict] = None,
    ) -> Optional[PluginResult]:

        if pair not in self._pairs:
            return None

        self._reset_if_new_day(pair)
        state = self._state[pair]
        c1h   = (candles or {}).get("1H",  [])
        c15m  = (candles or {}).get("15M", [])
        c1m   = (candles or {}).get("1M",  [])

        # Step 1: Build 8AM 1H HTF range
        if not state["htf_range"] and c1h:
            state["htf_range"] = self._range_builder.build_htf(c1h)
            if state["htf_range"]:
                logger.info(f"[CR] {pair} HTF range: H={state['htf_range'].high} L={state['htf_range'].low}")

        # Step 2: Build 9:15 15M LTF range
        if state["htf_range"] and not state["ltf_range"] and c15m:
            state["ltf_range"] = self._range_builder.build_ltf(c15m)
            if state["ltf_range"]:
                logger.info(f"[CR] {pair} LTF range: H={state['ltf_range'].high} L={state['ltf_range'].low}")

        # Only monitor during active window
        if not self._is_active():
            return None

        if not state["htf_range"] or not state["ltf_range"] or not c1m:
            return None

        htf, ltf = state["htf_range"], state["ltf_range"]

        # Step 3: Detect sweep
        if not state["sweep"]:
            state["sweep"] = self._sweep.detect(c1m, ltf)
            if state["sweep"]:
                logger.info(f"[CR] {pair} Sweep detected: {state['sweep'].direction}")

        if not state["sweep"]:
            return None

        sweep = state["sweep"]

        # Step 4: Detect structure
        bos = self._structure.detect_bos(c1m, sweep)
        ob  = self._structure.detect_ob(c1m, sweep)
        fvg = self._structure.detect_fvg(c1m, sweep)

        current_price = prices[-1] if prices else (c1m[-1]["close"] if c1m else 0)

        # Step 5: Validate entry
        validated = self._validator.validate(
            sweep, htf, ltf, bos, ob, fvg, current_price
        )

        if not validated or validated["setup_score"] < self._min_score:
            return None

        # Step 6: Build CRSignal
        signal = CRSignal(
            pair=pair, exchange=exchange,
            htf_range=htf, ltf_range=ltf, sweep=sweep,
            **validated,
        )

        state["signal"] = signal

        logger.info(
            f"[CR] ✅ {pair} {signal.direction.upper()} setup | "
            f"score={signal.setup_score:.2f} {signal.confidence} | "
            f"entry={signal.entry_price:.4f} TP1={signal.tp1:.4f} TP2={signal.tp2:.4f} "
            f"SL={signal.stop_loss:.4f} RR={signal.risk_reward_tp1}/{signal.risk_reward_tp2}"
        )

        return PluginResult(
            plugin=self.name,
            signal_score=signal.setup_score,
            weight=self._weight,
            data=signal.to_dict(),
            signal_type="cr_9am_setup",
        )

    def get_active_signals(self) -> List[dict]:
        """Return all current daily signals across pairs."""
        return [
            s["signal"].to_dict()
            for s in self._state.values()
            if s.get("signal")
        ]

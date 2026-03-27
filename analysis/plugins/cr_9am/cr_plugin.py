"""
9AM CRT (Candle Range Theory) Plugin — v4 complete rewrite.

Based on Bruce_Loki/@Currency_Raid CRT methodology:
  Step 1 — Build Narrative: market stage + PD arrays
  Step 2 — Determine Range: Reversal (5AM range) or Continuation (1AM range)
  Step 3 — Daily Profile: NY Reversal or NY Continuation
  Step 4 — Draw on Liquidity: opposite side of swept range

Key changes from previous implementation:
  - Range is PRIOR SESSION CANDLE (1AM or 5AM), not 8AM 1H candle
  - TWO models: Reversal AND Continuation
  - Session boundaries tracked from 5M/1M data
  - DOL is explicit and model-dependent
  - TP1 = 50% of range candle (configurable)
  - H4 manipulation check for high-volatility setups

Full config.yaml config under analysis.cr_9am:
  reversal_range:       "5am"
  continuation_range:   "1am"
  session_tz:           "America/New_York"
  active_from_hour:     9
  active_to_hour:       12
  min_setup_score:      0.55
  tp1_pct_of_range:     0.50
  require_bos:          true
  require_fvg:          false
  check_h4_manipulation: true
  pairs:                ["BTC/USDT", "ETH/USDT"]
"""
from __future__ import annotations
import pytz
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from analysis.plugins.registry import AnalysisPlugin, register
from messaging.logging import get_logger
from messaging.models import CRRange, CRSignal, FVG, OrderBlock, PluginResult, Sweep

logger = get_logger("analysis.cr_9am")

SESSION_HOURS = {"1am": (1,0), "5am": (5,0), "9am": (9,0), "1pm": (13,0)}


def _to_local(ts, tz) -> datetime:
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, tz=pytz.utc)
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
            if not dt.tzinfo: dt = dt.replace(tzinfo=pytz.utc)
        except Exception: return datetime.now(tz)
    elif isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=pytz.utc)
    else: return datetime.now(tz)
    return dt.astimezone(tz)


def _find_session_candle(candles, hour, minute, tz, tolerance_min=5):
    best, best_diff = None, float("inf")
    for c in candles:
        t = _to_local(c["time"], tz)
        diff = abs((t.hour * 60 + t.minute) - (hour * 60 + minute))
        if diff < best_diff and diff <= tolerance_min:
            best_diff, best = diff, c
    return best


class CRTRangeBuilder:
    def __init__(self, tz_name):
        self._tz = pytz.timezone(tz_name)

    def build_session_range(self, candles, session, timeframe="session"):
        hour, minute = SESSION_HOURS.get(session, (9, 0))
        c = _find_session_candle(candles, hour, minute, self._tz)
        if not c: return None
        return CRRange(timeframe=timeframe, candle_time=_to_local(c["time"], self._tz),
                       high=c["high"], low=c["low"])


class CRTSweepDetector:
    def detect(self, candles, cr_range):
        for c in reversed(candles[-30:]):
            if c["high"] > cr_range.high and c["close"] < cr_range.high:
                return Sweep(direction="high_sweep", sweep_price=c["high"],
                             sweep_time=self._ts(c["time"]), range_level=cr_range.high, confirmed=True)
            if c["low"] < cr_range.low and c["close"] > cr_range.low:
                return Sweep(direction="low_sweep", sweep_price=c["low"],
                             sweep_time=self._ts(c["time"]), range_level=cr_range.low, confirmed=True)
        return None

    def _ts(self, t):
        if isinstance(t, datetime): return t
        if isinstance(t, (int, float)): return datetime.fromtimestamp(t / 1000 if t > 1e10 else t)
        return datetime.fromisoformat(str(t))


class CRTStructureDetector:
    def detect_bos(self, candles, sweep):
        post = [c for c in candles if self._ts(c["time"]) > sweep.sweep_time]
        if not post: return False
        lookback = candles[-20:]
        if sweep.direction == "low_sweep":
            h = max(c["high"] for c in lookback)
            return any(c["close"] > h for c in post[-5:])
        else:
            l = min(c["low"] for c in lookback)
            return any(c["close"] < l for c in post[-5:])

    def detect_ob(self, candles, sweep):
        pre = [c for c in candles if self._ts(c["time"]) <= sweep.sweep_time][-20:]
        if sweep.direction == "low_sweep":
            for c in reversed(pre):
                if c["close"] < c["open"]:
                    return OrderBlock(direction="bullish_ob", high=c["high"], low=c["low"],
                                      open=c["open"], close=c["close"], time=self._ts(c["time"]))
        else:
            for c in reversed(pre):
                if c["close"] > c["open"]:
                    return OrderBlock(direction="bearish_ob", high=c["high"], low=c["low"],
                                      open=c["open"], close=c["close"], time=self._ts(c["time"]))
        return None

    def detect_fvg(self, candles, sweep):
        post = [c for c in candles if self._ts(c["time"]) >= sweep.sweep_time]
        if len(post) < 3: return None
        for i in range(1, len(post) - 1):
            c1, c2, c3 = post[i-1], post[i], post[i+1]
            if sweep.direction == "low_sweep" and c3["low"] > c1["high"]:
                return FVG(direction="bullish_fvg", top=c3["low"], bottom=c1["high"],
                           time=self._ts(c2["time"]), confirmed=True)
            if sweep.direction == "high_sweep" and c3["high"] < c1["low"]:
                return FVG(direction="bearish_fvg", top=c1["low"], bottom=c3["high"],
                           time=self._ts(c2["time"]), confirmed=True)
        return None

    def check_h4_manipulation(self, candles_4h, sweep):
        if not candles_4h or len(candles_4h) < 2: return False
        prior = candles_4h[-2]
        return (sweep.sweep_price > prior["high"] if sweep.direction == "high_sweep"
                else sweep.sweep_price < prior["low"])

    def _ts(self, t):
        if isinstance(t, datetime): return t
        if isinstance(t, (int, float)): return datetime.fromtimestamp(t / 1000 if t > 1e10 else t)
        return datetime.fromisoformat(str(t))


class CRTModelClassifier:
    def classify(self, candles_5m, range_1am, range_5am, tz):
        if not range_1am or not range_5am: return "unknown", "unknown"
        session = [c for c in candles_5m
                   if SESSION_HOURS["5am"][0] <= _to_local(c["time"], tz).hour < SESSION_HOURS["9am"][0]]
        if not session: return "reversal", "unknown"
        hi = max(c["high"] for c in session)
        lo = min(c["low"]  for c in session)
        swept_hi = hi > range_1am.high
        swept_lo = lo < range_1am.low
        if swept_hi and not swept_lo: return "continuation", "long"
        if swept_lo and not swept_hi: return "continuation", "short"
        return "reversal", "unknown"


class CRTEntryValidator:
    def validate(self, sweep, cr_range, dol_range, bos, ob, fvg,
                 current_price, model_type, tp1_pct=0.50, h4_manipulation=False):
        direction = "long" if sweep.direction == "low_sweep" else "short"
        notes, score = [], 0.0
        score += 0.20; notes.append(f"Sweep ✅")
        if bos: score += 0.20; notes.append("BOS confirmed ✅")
        else: notes.append("BOS pending ⏳")
        if ob and not ob.violated: score += 0.15; notes.append(f"OB ✅")
        if fvg and fvg.confirmed and not fvg.filled: score += 0.20; notes.append(f"FVG ✅")
        ifvg_ob = False
        if ob and fvg and not fvg.filled:
            if max(ob.low, fvg.bottom) < min(ob.high, fvg.top):
                ifvg_ob = True; score += 0.10; notes.append("IFVG+OB ✅")
        if h4_manipulation: score += 0.10; notes.append("H4 manip ⚡")
        if direction == "long" and cr_range.is_discount(current_price): score += 0.15
        elif direction == "short" and cr_range.is_premium(current_price): score += 0.15
        if not ob and not fvg: return None
        entry_price  = fvg.midpoint if (fvg and fvg.confirmed) else (ob.high + ob.low) / 2
        entry_top    = fvg.top    if (fvg and fvg.confirmed) else ob.high
        entry_bottom = fvg.bottom if (fvg and fvg.confirmed) else ob.low
        buf = cr_range.size * 0.10
        stop_loss = sweep.sweep_price - buf if direction == "long" else sweep.sweep_price + buf
        rs = cr_range.high - cr_range.low
        if direction == "long":
            tp1 = cr_range.low  + rs * tp1_pct
            tp2 = dol_range.high if dol_range else cr_range.high
        else:
            tp1 = cr_range.high - rs * tp1_pct
            tp2 = dol_range.low  if dol_range else cr_range.low
        if score < 0.40: return None
        confidence = "HIGH" if score >= 0.75 else "MEDIUM" if score >= 0.55 else "LOW"
        notes.append(f"Model: {model_type}")
        return {"direction": direction, "entry_price": entry_price,
                "entry_zone_top": entry_top, "entry_zone_bottom": entry_bottom,
                "stop_loss": stop_loss, "tp1": tp1, "tp2": tp2, "tp1_is_50pct": True,
                "bos_confirmed": bos, "ifvg_ob_alignment": ifvg_ob,
                "order_block": ob, "fvg": fvg, "h4_manipulation": h4_manipulation,
                "model_type": model_type,
                "setup_score": round(min(score, 1.0), 3), "confidence": confidence, "notes": notes}


@register
class CR9AMPlugin(AnalysisPlugin):
    """9AM CRT — v4 rewrite. Reversal + Continuation models."""
    name = "cr_9am"
    enabled_by_default = False

    def __init__(self):
        super().__init__()
        self._weight = 0.30
        self._timezone = "America/New_York"
        self._tz = pytz.timezone(self._timezone)
        self._active_from_hour = 9
        self._active_to_hour = 12
        self._min_score = 0.55
        self._pairs = ["BTC/USDT", "ETH/USDT"]
        self._reversal_range = "5am"
        self._continuation_range = "1am"
        self._tp1_pct = 0.50
        self._require_bos = True
        self._require_fvg = False
        self._check_h4 = True
        self._range_builder = CRTRangeBuilder(self._timezone)
        self._sweep = CRTSweepDetector()
        self._structure = CRTStructureDetector()
        self._classifier = CRTModelClassifier()
        self._validator = CRTEntryValidator()
        self._state: Dict[str, dict] = {}
        self._force_active: bool = False

    def apply_config(self, config: dict) -> None:
        super().apply_config(config)
        p = config.get("params", config)
        self._timezone           = p.get("timezone",             self._timezone)
        self._active_from_hour   = p.get("active_from_hour",     self._active_from_hour)
        self._active_to_hour     = p.get("active_to_hour",       self._active_to_hour)
        self._min_score          = p.get("min_setup_score",      self._min_score)
        self._pairs              = p.get("pairs",                self._pairs)
        self._reversal_range     = p.get("reversal_range",       self._reversal_range)
        self._continuation_range = p.get("continuation_range",   self._continuation_range)
        self._tp1_pct            = float(p.get("tp1_pct_of_range", self._tp1_pct))
        self._require_bos        = p.get("require_bos",          self._require_bos)
        self._require_fvg        = p.get("require_fvg",          self._require_fvg)
        self._check_h4           = p.get("check_h4_manipulation", self._check_h4)
        self._tz                 = pytz.timezone(self._timezone)
        self._range_builder      = CRTRangeBuilder(self._timezone)

    def _is_active(self):
        if self._force_active: return True
        now = datetime.now(self._tz)
        return self._active_from_hour <= now.hour < self._active_to_hour

    def set_force_active(self, value: bool) -> None:
        self._force_active = value

    def _today(self): return datetime.now(self._tz).date()

    def _reset_if_new_day(self, pair):
        state = self._state.get(pair, {})
        if state.get("date") != self._today():
            self._state[pair] = {"date": self._today(), "range_1am": None, "range_5am": None,
                                  "model_type": None, "cr_range": None, "dol_range": None,
                                  "sweep": None, "signal": None}

    async def run(self, exchange, pair, prices, candles=None, extra=None):
        if pair not in self._pairs: return None
        self._reset_if_new_day(pair)
        state = self._state[pair]
        c5m = (candles or {}).get("5M", [])
        c1m = (candles or {}).get("1M", [])
        c4h = (candles or {}).get("4H", [])
        cr  = c5m or (candles or {}).get("1H", [])

        if not state["range_1am"] and cr:
            state["range_1am"] = self._range_builder.build_session_range(cr, "1am", "1AM")
            if state["range_1am"]: logger.info(f"[CRT] {pair} 1AM H={state['range_1am'].high:.5f} L={state['range_1am'].low:.5f}")

        if not state["range_5am"] and cr:
            state["range_5am"] = self._range_builder.build_session_range(cr, "5am", "5AM")
            if state["range_5am"]: logger.info(f"[CRT] {pair} 5AM H={state['range_5am'].high:.5f} L={state['range_5am'].low:.5f}")

        if not state["model_type"] and state["range_1am"] and state["range_5am"]:
            model_type, _ = self._classifier.classify(cr, state["range_1am"], state["range_5am"], self._tz)
            state["model_type"] = model_type
            if model_type == "reversal":
                state["cr_range"] = state["range_5am"]
                state["dol_range"] = state["range_5am"]
            else:
                state["cr_range"] = state["range_1am"]
                state["dol_range"] = state["range_1am"]
            logger.info(f"[CRT] {pair} model={model_type}")

        if not self._is_active(): return None
        if not state.get("cr_range"): return None

        ac = c1m or c5m
        if not ac: return None

        if not state["sweep"]:
            state["sweep"] = self._sweep.detect(ac, state["cr_range"])
            if state["sweep"]: logger.info(f"[CRT] {pair} sweep {state['sweep'].direction} @ {state['sweep'].sweep_price:.5f}")

        if not state["sweep"]: return None
        sweep = state["sweep"]

        bos = self._structure.detect_bos(ac, sweep)
        ob  = self._structure.detect_ob(ac, sweep)
        fvg = self._structure.detect_fvg(ac, sweep)
        h4  = self._structure.check_h4_manipulation(c4h, sweep) if self._check_h4 else False

        if self._require_bos and not bos: return None
        if self._require_fvg and not fvg: return None

        validated = self._validator.validate(
            sweep=sweep, cr_range=state["cr_range"], dol_range=state["dol_range"],
            bos=bos, ob=ob, fvg=fvg, current_price=prices[-1] if prices else 0.0,
            model_type=state["model_type"] or "reversal", tp1_pct=self._tp1_pct, h4_manipulation=h4
        )

        if not validated or validated["setup_score"] < self._min_score: return None

        signal = CRSignal(pair=pair, exchange=exchange,
                          htf_range=state["range_1am"] or state["cr_range"],
                          ltf_range=state["range_5am"] or state["cr_range"],
                          sweep=sweep, **validated)
        state["signal"] = signal

        logger.info(f"[CRT] ✅ {pair} {signal.direction.upper()} | model={validated['model_type']} | "
                    f"score={signal.setup_score:.2f} {signal.confidence} | "
                    f"entry={signal.entry_price:.5f} TP1={signal.tp1:.5f} TP2={signal.tp2:.5f} SL={signal.stop_loss:.5f}")

        return PluginResult(plugin=self.name, signal_score=signal.setup_score,
                            weight=self._weight, data=signal.to_dict(), signal_type="cr_9am_setup")

    def get_active_signals(self):
        return [s["signal"].to_dict() for s in self._state.values() if s.get("signal")]

    def get_daily_state(self):
        return [{"pair": p, "date": str(s.get("date","")), "model_type": s.get("model_type"),
                 "range_1am": s["range_1am"].to_dict() if s.get("range_1am") else None,
                 "range_5am": s["range_5am"].to_dict() if s.get("range_5am") else None,
                 "sweep": s["sweep"].to_dict() if s.get("sweep") else None,
                 "has_signal": s.get("signal") is not None}
                for p, s in self._state.items()]

"""
Shared data models for ArbitrageEngine v2.
Used by brain, workers, messaging, analysis, and API layers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


# ─── Enums ───────────────────────────────────────────────────────────────────

class StrategyType(str, Enum):
    SPATIAL       = "spatial"
    TRIANGULAR    = "triangular"
    DEX           = "dex"
    CROSS_CHAIN   = "cross_chain"
    FLASHLOAN     = "flashloan"
    FX            = "fx"
    MULTI_COUNTRY = "multi_country"


class WorkerStatus(str, Enum):
    HEALTHY     = "healthy"
    DEGRADED    = "degraded"
    BLOCKED     = "blocked"
    OVERLOADED  = "overloaded"
    DEAD        = "dead"
    STARTING    = "starting"


class WorkerCondition(str, Enum):
    NONE          = "none"
    IP_BLOCK      = "ip_block"
    RATE_LIMIT    = "rate_limit"
    EXCHANGE_DOWN = "exchange_down"
    AUTH_ERROR    = "auth_error"
    OVERLOADED    = "overloaded"
    STALE_DATA    = "stale_data"
    CRASHED       = "crashed"


class FleetActionType(str, Enum):
    NONE              = "none"
    RESPAWN           = "respawn"
    SPAWN_REPLACEMENT = "spawn_replacement"
    SPAWN_COMPANION   = "spawn_companion"
    SPAWN_PARALLEL    = "spawn_parallel"
    SPLIT_PAIRS       = "split_pairs"
    SUGGEST           = "suggest"
    REVOKE            = "revoke"


class Confidence(str, Enum):
    LOW    = "LOW"
    MEDIUM = "MEDIUM"
    HIGH   = "HIGH"


class TradeDirection(str, Enum):
    LONG  = "long"
    SHORT = "short"


class ExecutionStatus(str, Enum):
    PENDING   = "pending"
    SIMULATED = "simulated"
    SENT      = "sent"
    FILLED    = "filled"
    PARTIAL   = "partial"
    CANCELLED = "cancelled"
    FAILED    = "failed"
    SKIPPED   = "skipped"
    EXPIRED   = "expired"


class OrderType(str, Enum):
    MARKET      = "market"
    LIMIT       = "limit"
    LIMIT_MAKER = "limit_maker"   # post-only limit
    STOP_LIMIT  = "stop_limit"    # fallback SL for non-OCO exchanges
    OCO         = "oco"           # one-cancels-other (entry + SL + TP in one)


class OrderSide(str, Enum):
    BUY  = "buy"
    SELL = "sell"


class SignalSource(str, Enum):
    CR_9AM      = "cr_9am"
    GRAPH_ARB   = "graph_arb"
    SPATIAL     = "spatial"
    MANUAL      = "manual"


# ─── Market Data ─────────────────────────────────────────────────────────────

@dataclass
class Candle:
    exchange:  str
    pair:      str
    timeframe: str         # "1M", "15M", "1H"
    time:      datetime
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float = 0.0

    def is_bullish(self) -> bool:
        return self.close > self.open

    def is_bearish(self) -> bool:
        return self.close < self.open

    def body_size(self) -> float:
        return abs(self.close - self.open)

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange, "pair": self.pair,
            "timeframe": self.timeframe,
            "time": self.time.isoformat(),
            "open": self.open, "high": self.high,
            "low": self.low, "close": self.close,
            "volume": self.volume,
        }


@dataclass
class PriceTick:
    exchange:   str
    pair:       str
    price:      float
    volume_24h: float = 0.0
    timestamp:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    worker_id:  str = ""


@dataclass
class OrderBook:
    exchange:  str
    pair:      str
    bids:      List[List[float]]
    asks:      List[List[float]]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    worker_id: str = ""

    @property
    def best_bid(self) -> float:
        return self.bids[0][0] if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0][0] if self.asks else 0.0

    @property
    def spread_pct(self) -> float:
        if not self.bids or not self.asks:
            return 0.0
        return ((self.best_ask - self.best_bid) / self.best_bid) * 100


@dataclass
class FxRate:
    base:      str
    quote:     str
    rate:      float
    source:    str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def pair(self) -> str:
        return f"{self.base}/{self.quote}"


# ─── Worker ───────────────────────────────────────────────────────────────────

@dataclass
class WorkerHeartbeat:
    worker_id:       str
    exchange:        str
    pairs:           List[str]
    machine:         str
    status:          WorkerStatus
    condition:       WorkerCondition
    ticks_last_60s:  int
    latency_ms:      float
    error_count:     int
    last_error:      Optional[str]
    cpu_pct:         float
    memory_mb:       float
    is_replacement:  bool = False
    replaced_worker: Optional[str] = None
    timestamp:       datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "worker_id":       self.worker_id,
            "exchange":        self.exchange,
            "pairs":           self.pairs,
            "machine":         self.machine,
            "status":          self.status.value,
            "condition":       self.condition.value,
            "ticks_last_60s":  self.ticks_last_60s,
            "latency_ms":      self.latency_ms,
            "error_count":     self.error_count,
            "last_error":      self.last_error,
            "cpu_pct":         self.cpu_pct,
            "memory_mb":       self.memory_mb,
            "is_replacement":  self.is_replacement,
            "replaced_worker": self.replaced_worker,
            "timestamp":       self.timestamp.isoformat(),
        }


@dataclass
class WorkerRegistration:
    worker_id:          str
    exchange:           str
    pairs:              List[str]
    machine:            str
    role:               str    # "collector_only" | "collector_and_executor"
    can_execute_orders: bool
    max_order_size_usd: float
    cert_fingerprint:   str
    version:            str
    timestamp:          datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FleetAction:
    action_type:   FleetActionType
    worker_id:     str
    reason:        str
    urgency:       str = "NORMAL"
    same_machine:  bool = False
    kill_original: bool = False
    split_pairs:   bool = False
    probe_mode:    bool = False
    avoid_machine: Optional[str] = None
    suggestion:    Optional[str] = None
    timestamp:     datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "action_type":   self.action_type.value,
            "worker_id":     self.worker_id,
            "reason":        self.reason,
            "urgency":       self.urgency,
            "kill_original": self.kill_original,
            "split_pairs":   self.split_pairs,
            "suggestion":    self.suggestion,
            "timestamp":     self.timestamp.isoformat(),
        }


# ─── Analysis ─────────────────────────────────────────────────────────────────

@dataclass
class PluginResult:
    plugin:      str
    signal_score: float        # 0.0–1.0
    weight:       float        # contribution to final score
    data:         Dict[str, Any] = field(default_factory=dict)
    signal_type:  str = "general"
    error:        Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "plugin":       self.plugin,
            "signal_score": round(self.signal_score, 4),
            "weight":       self.weight,
            "signal_type":  self.signal_type,
            "data":         self.data,
        }


@dataclass
class MarketSignal:
    exchange:             str
    pair:                 str
    signal_score:         float
    confidence:           Confidence
    trend:                str = "NEUTRAL"
    volatility:           str = "MEDIUM"
    plugin_results:       List[PluginResult] = field(default_factory=list)
    prediction_direction: str = "NEUTRAL"
    timestamp:            datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "exchange":     self.exchange,
            "pair":         self.pair,
            "signal_score": round(self.signal_score, 4),
            "confidence":   self.confidence.value,
            "trend":        self.trend,
            "volatility":   self.volatility,
            "plugins":      [p.to_dict() for p in self.plugin_results],
            "prediction_direction": self.prediction_direction,
            "timestamp":    self.timestamp.isoformat(),
        }


# ─── CR 9AM Model ─────────────────────────────────────────────────────────────

@dataclass
class CRRange:
    timeframe:    str
    candle_time:  datetime
    high:         float
    low:          float

    @property
    def equilibrium(self) -> float:
        return (self.high + self.low) / 2

    @property
    def size(self) -> float:
        return self.high - self.low

    def is_discount(self, price: float) -> bool:
        return price < self.equilibrium

    def is_premium(self, price: float) -> bool:
        return price > self.equilibrium

    def to_dict(self) -> dict:
        return {
            "timeframe":    self.timeframe,
            "candle_time":  self.candle_time.isoformat(),
            "high":         self.high,
            "low":          self.low,
            "equilibrium":  self.equilibrium,
            "size":         round(self.size, 6),
        }


@dataclass
class Sweep:
    direction:   str
    sweep_price: float
    sweep_time:  datetime
    range_level: float
    confirmed:   bool = False

    def to_dict(self) -> dict:
        return {
            "direction":   self.direction,
            "sweep_price": self.sweep_price,
            "range_level": self.range_level,
            "sweep_time":  self.sweep_time.isoformat(),
            "confirmed":   self.confirmed,
        }


@dataclass
class OrderBlock:
    direction: str
    high:      float
    low:       float
    open:      float
    close:     float
    time:      datetime
    violated:  bool = False

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "high": self.high, "low": self.low,
            "open": self.open, "close": self.close,
            "time": self.time.isoformat(),
            "violated": self.violated,
        }


@dataclass
class FVG:
    direction:   str
    top:         float
    bottom:      float
    time:        datetime
    confirmed:   bool = False
    filled:      bool = False

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def size(self) -> float:
        return self.top - self.bottom

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "top": self.top, "bottom": self.bottom,
            "midpoint": self.midpoint,
            "time": self.time.isoformat(),
            "confirmed": self.confirmed,
            "filled": self.filled,
        }


@dataclass
class CRSignal:
    pair:              str
    exchange:          str
    direction:         str
    htf_range:         CRRange
    ltf_range:         CRRange
    sweep:             Sweep
    bos_confirmed:     bool
    order_block:       Optional[OrderBlock]
    fvg:               Optional[FVG]
    ifvg_ob_alignment: bool
    entry_price:       float
    entry_zone_top:    float
    entry_zone_bottom: float
    tp1:               float
    tp2:               float
    stop_loss:         float
    setup_score:       float
    confidence:        str
    notes:             List[str] = field(default_factory=list)
    timestamp:         datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def risk_reward_tp1(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.tp1 - self.entry_price)
        return round(reward / risk, 2) if risk > 0 else 0.0

    @property
    def risk_reward_tp2(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.tp2 - self.entry_price)
        return round(reward / risk, 2) if risk > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "pair": self.pair, "exchange": self.exchange,
            "direction": self.direction,
            "htf_range": self.htf_range.to_dict(),
            "ltf_range": self.ltf_range.to_dict(),
            "sweep": self.sweep.to_dict(),
            "bos_confirmed": self.bos_confirmed,
            "order_block": self.order_block.to_dict() if self.order_block else None,
            "fvg": self.fvg.to_dict() if self.fvg else None,
            "ifvg_ob_alignment": self.ifvg_ob_alignment,
            "entry": {
                "price": self.entry_price,
                "zone_top": self.entry_zone_top,
                "zone_bottom": self.entry_zone_bottom,
            },
            "targets": {
                "tp1": self.tp1, "tp2": self.tp2,
                "stop_loss": self.stop_loss,
                "rr_tp1": self.risk_reward_tp1,
                "rr_tp2": self.risk_reward_tp2,
            },
            "quality": {
                "score": self.setup_score,
                "confidence": self.confidence,
                "notes": self.notes,
            },
            "timestamp": self.timestamp.isoformat(),
        }


# ─── Opportunity ──────────────────────────────────────────────────────────────

@dataclass
class Opportunity:
    strategy:             StrategyType
    pair:                 str
    buy_exchange:         str
    sell_exchange:        str
    buy_price:            float
    sell_price:           float
    profit_percent:       float
    volume:               float
    estimated_profit_usd: float = 0.0
    fee_estimate:         float = 0.0
    gas_estimate:         float = 0.0
    score:                float = 0.0
    confidence:           Confidence = Confidence.LOW
    chain:                Optional[str] = None
    source_worker:        Optional[str] = None
    extra:                Dict = field(default_factory=dict)
    id:                   str = field(default_factory=lambda: str(uuid4()))
    timestamp:            datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def cache_key(self) -> str:
        return f"{self.pair}-{self.buy_exchange}-{self.sell_exchange}-{self.strategy.value}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategy": self.strategy.value,
            "pair": self.pair,
            "buy_exchange": self.buy_exchange,
            "sell_exchange": self.sell_exchange,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "profit_percent": round(self.profit_percent, 4),
            "volume": self.volume,
            "estimated_profit_usd": round(self.estimated_profit_usd, 2),
            "score": round(self.score, 4),
            "confidence": self.confidence.value,
            "chain": self.chain,
            "source_worker": self.source_worker,
            "timestamp": self.timestamp.isoformat(),
        }


# ─── Balance ──────────────────────────────────────────────────────────────────

@dataclass
class Balance:
    exchange:  str
    asset:     str
    free:      float
    locked:    float = 0.0
    usd_value: float = 0.0
    worker_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total(self) -> float:
        return self.free + self.locked

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange, "asset": self.asset,
            "free": self.free, "locked": self.locked,
            "total": self.total, "usd_value": round(self.usd_value, 2),
            "worker_id": self.worker_id,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RebalanceSuggestion:
    from_exchange: str
    to_exchange:   str
    asset:         str
    amount:        float
    reason:        str
    urgency:       str = "NORMAL"
    timestamp:     datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "from_exchange": self.from_exchange,
            "to_exchange": self.to_exchange,
            "asset": self.asset,
            "amount": self.amount,
            "reason": self.reason,
            "urgency": self.urgency,
            "timestamp": self.timestamp.isoformat(),
        }


# ─── Orders (v3.3) ───────────────────────────────────────────────────────────

@dataclass
class OrderCommand:
    """
    Full order specification sent from brain → worker.
    Contains entry, stop loss, and take profit levels so the worker
    can place an OCO order (or separate stop-limit) in one atomic operation.
    """
    id:              str   = field(default_factory=lambda: str(uuid4()))
    exchange:        str   = ""
    pair:            str   = ""
    side:            OrderSide    = OrderSide.BUY
    order_type:      OrderType    = OrderType.LIMIT
    price:           float = 0.0        # entry price (limit orders)
    volume:          float = 0.0        # base asset volume
    capital_usd:     float = 0.0        # USD equivalent at entry
    stop_loss:       float = 0.0        # hard stop — exchange managed
    take_profit_1:   float = 0.0        # TP1 — partial close
    take_profit_2:   float = 0.0        # TP2 — full close
    tp1_pct:         float = 0.5        # fraction of position to close at TP1
    source:          SignalSource = SignalSource.MANUAL
    signal_score:    float = 0.0
    confidence:      str   = "LOW"
    trading_mode:    str   = "simulate"
    dry_run:         bool  = True
    created_at:      datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at:      Optional[datetime] = None   # discard if not filled by this time
    notes:           str   = ""

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "exchange":      self.exchange,
            "pair":          self.pair,
            "side":          self.side.value,
            "order_type":    self.order_type.value,
            "price":         self.price,
            "volume":        self.volume,
            "capital_usd":   self.capital_usd,
            "stop_loss":     self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "tp1_pct":       self.tp1_pct,
            "source":        self.source.value,
            "signal_score":  round(self.signal_score, 4),
            "confidence":    self.confidence,
            "trading_mode":  self.trading_mode,
            "dry_run":       self.dry_run,
            "created_at":    self.created_at.isoformat(),
            "expires_at":    self.expires_at.isoformat() if self.expires_at else None,
            "notes":         self.notes,
        }


@dataclass
class OrderResult:
    """Result returned from worker after order execution attempt."""
    order_id:           str
    exchange:           str
    exchange_order_id:  str   = ""
    status:             ExecutionStatus = ExecutionStatus.PENDING
    filled_price:       float = 0.0
    filled_volume:      float = 0.0
    fees_paid:          float = 0.0
    fees_currency:      str   = ""
    slippage_pct:       float = 0.0
    execution_time_ms:  float = 0.0
    stop_loss_order_id: str   = ""    # separate SL order ID if not OCO
    error:              Optional[str] = None
    raw_response:       Optional[dict] = None
    timestamp:          datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "order_id":           self.order_id,
            "exchange":           self.exchange,
            "exchange_order_id":  self.exchange_order_id,
            "status":             self.status.value,
            "filled_price":       self.filled_price,
            "filled_volume":      self.filled_volume,
            "fees_paid":          self.fees_paid,
            "fees_currency":      self.fees_currency,
            "slippage_pct":       round(self.slippage_pct, 4),
            "execution_time_ms":  round(self.execution_time_ms, 2),
            "stop_loss_order_id": self.stop_loss_order_id,
            "error":              self.error,
            "timestamp":          self.timestamp.isoformat(),
        }


@dataclass
class Position:
    """Tracks an open position from entry to close."""
    id:               str   = field(default_factory=lambda: str(uuid4()))
    order_id:         str   = ""
    exchange:         str   = ""
    pair:             str   = ""
    side:             str   = "buy"
    entry_price:      float = 0.0
    current_price:    float = 0.0
    volume:           float = 0.0
    capital_usd:      float = 0.0
    stop_loss:        float = 0.0
    take_profit_1:    float = 0.0
    take_profit_2:    float = 0.0
    source:           str   = ""
    status:           str   = "open"   # open | closed | cancelled
    pnl_usd:          float = 0.0
    pnl_pct:          float = 0.0
    opened_at:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at:        Optional[datetime] = None
    close_reason:     str   = ""       # sl_hit | tp1_hit | tp2_hit | manual | expired

    def update_price(self, price: float) -> None:
        self.current_price = price
        if self.entry_price > 0:
            raw_pnl = (price - self.entry_price) / self.entry_price
            self.pnl_pct = raw_pnl * 100 if self.side == "buy" else -raw_pnl * 100
            self.pnl_usd = self.capital_usd * (self.pnl_pct / 100)

    def sl_hit(self, price: float) -> bool:
        if not self.stop_loss:
            return False
        return (self.side == "buy"  and price <= self.stop_loss) or \
               (self.side == "sell" and price >= self.stop_loss)

    def tp1_hit(self, price: float) -> bool:
        if not self.take_profit_1:
            return False
        return (self.side == "buy"  and price >= self.take_profit_1) or \
               (self.side == "sell" and price <= self.take_profit_1)

    def tp2_hit(self, price: float) -> bool:
        if not self.take_profit_2:
            return False
        return (self.side == "buy"  and price >= self.take_profit_2) or \
               (self.side == "sell" and price <= self.take_profit_2)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "order_id":      self.order_id,
            "exchange":      self.exchange,
            "pair":          self.pair,
            "side":          self.side,
            "entry_price":   self.entry_price,
            "current_price": self.current_price,
            "volume":        self.volume,
            "capital_usd":   self.capital_usd,
            "stop_loss":     self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "source":        self.source,
            "status":        self.status,
            "pnl_usd":       round(self.pnl_usd, 2),
            "pnl_pct":       round(self.pnl_pct, 4),
            "opened_at":     self.opened_at.isoformat(),
            "closed_at":     self.closed_at.isoformat() if self.closed_at else None,
            "close_reason":  self.close_reason,
        }

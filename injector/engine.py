"""
Price Injector — publishes synthetic price ticks directly to the Redis
message bus, bypassing workers entirely.

The brain receives injected ticks identically to real worker ticks.
All analysis, graph arbitrage, CR model, and strategies respond normally.

Use for:
  - Testing specific price scenarios (sudden pump, crash, spread spike)
  - Triggering graph arbitrage paths with known profitable cycles
  - Reproducing bugs observed in production
  - Testing alert thresholds without waiting for real market moves
  - CI/CD — deterministic price sequences for integration tests
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from messaging.bus import MessageBus, STREAM_PRICES, STREAM_CANDLES
from messaging.logging import get_logger, setup_logging

logger = get_logger("injector.engine")

INJECTOR_WORKER_ID = "injector-synthetic"


# ─── Tick model ──────────────────────────────────────────────────────────────

@dataclass
class SyntheticTick:
    """A single injected price tick."""
    exchange:    str
    pair:        str
    price:       float
    volume_24h:  float = 50_000.0
    delay_ms:    int   = 0          # ms to wait BEFORE publishing this tick
    note:        str   = ""         # human label — logged and visible in dashboard

    def to_stream_message(self) -> dict:
        return {
            "worker_id":  INJECTOR_WORKER_ID,
            "exchange":   self.exchange,
            "pair":       self.pair,
            "price":      self.price,
            "volume_24h": self.volume_24h,
            "timestamp":  datetime.utcnow().isoformat(),
            "_injected":  True,
            "_note":      self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SyntheticTick":
        return cls(
            exchange=d["exchange"],
            pair=d["pair"],
            price=float(d["price"]),
            volume_24h=float(d.get("volume_24h", 50_000)),
            delay_ms=int(d.get("delay_ms", 0)),
            note=str(d.get("note", "")),
        )


@dataclass
class SyntheticCandle:
    """An injected OHLCV candle (for CR model testing)."""
    exchange:  str
    pair:      str
    timeframe: str      # "1M", "15M", "1H"
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float = 100.0
    time:      Optional[str] = None   # ISO8601, defaults to now

    def to_stream_message(self) -> dict:
        return {
            "worker_id": INJECTOR_WORKER_ID,
            "exchange":  self.exchange,
            "pair":      self.pair,
            "timeframe": self.timeframe,
            "open":      self.open,
            "high":      self.high,
            "low":       self.low,
            "close":     self.close,
            "volume":    self.volume,
            "time":      self.time or datetime.utcnow().isoformat(),
            "_injected": True,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SyntheticCandle":
        return cls(
            exchange=d["exchange"],
            pair=d["pair"],
            timeframe=d.get("timeframe", "1M"),
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
            volume=float(d.get("volume", 100)),
            time=d.get("time"),
        )


# ─── Injector engine ─────────────────────────────────────────────────────────

class PriceInjector:
    """
    Connects to Redis and publishes synthetic ticks to the price stream.
    """

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        verbose:    bool = True,
    ):
        self._host    = redis_host
        self._port    = redis_port
        self._verbose = verbose
        self._bus:    Optional[MessageBus] = None
        setup_logging()

    async def connect(self) -> None:
        self._bus = MessageBus(host=self._host, port=self._port)
        await self._bus.connect()
        logger.info(f"Injector connected to Redis {self._host}:{self._port}")

    async def disconnect(self) -> None:
        if self._bus:
            await self._bus.disconnect()

    # ─── Single tick ─────────────────────────────────────────────────────────

    async def inject_tick(self, tick: SyntheticTick) -> str:
        """Publish one synthetic price tick. Returns stream message ID."""
        if tick.delay_ms > 0:
            await asyncio.sleep(tick.delay_ms / 1000)

        msg = tick.to_stream_message()
        msg_id = await self._bus.publish(STREAM_PRICES, msg)

        if self._verbose:
            label = f"  [{tick.note}]" if tick.note else ""
            logger.info(
                f"INJECTED  {tick.exchange:<12} {tick.pair:<12} "
                f"@ {tick.price:>12.4f}{label}"
            )
        return msg_id

    async def inject_candle(self, candle: SyntheticCandle) -> str:
        """Publish one synthetic candle (for CR model testing)."""
        msg = candle.to_stream_message()
        msg_id = await self._bus.publish(STREAM_CANDLES, msg)

        if self._verbose:
            logger.info(
                f"CANDLE    {candle.exchange:<12} {candle.pair:<12} "
                f"{candle.timeframe}  O={candle.open} H={candle.high} "
                f"L={candle.low} C={candle.close}"
            )
        return msg_id

    # ─── Sequence ────────────────────────────────────────────────────────────

    async def inject_sequence(self, ticks: List[SyntheticTick]) -> int:
        """
        Publish a sequence of ticks in order.
        Respects delay_ms between ticks.
        Returns count published.
        """
        logger.info(f"Injecting sequence of {len(ticks)} ticks...")
        count = 0
        for tick in ticks:
            await self.inject_tick(tick)
            count += 1
        logger.info(f"Sequence complete — {count} ticks injected.")
        return count

    # ─── Scenario ────────────────────────────────────────────────────────────

    async def inject_scenario(self, scenario: dict) -> dict:
        """
        Run a named test scenario from a dict (loaded from YAML or JSON).

        Scenario format:
          name: "BTC pump + spread spike"
          description: "..."
          ticks:
            - {exchange: binance, pair: BTC/USDT, price: 65000}
            - {exchange: kraken,  pair: BTC/USDT, price: 66500, delay_ms: 100}
          candles:
            - {exchange: binance, pair: BTC/USDT, timeframe: 1H,
               open: 64500, high: 65200, low: 64400, close: 65000}
        """
        name = scenario.get("name", "unnamed")
        logger.info(f"Running scenario: {name}")
        if scenario.get("description"):
            logger.info(f"  {scenario['description']}")

        tick_count = 0
        candle_count = 0

        for item in scenario.get("ticks", []):
            tick = SyntheticTick.from_dict(item)
            await self.inject_tick(tick)
            tick_count += 1

        for item in scenario.get("candles", []):
            candle = SyntheticCandle.from_dict(item)
            await self.inject_candle(candle)
            candle_count += 1

        result = {
            "scenario":    name,
            "ticks":       tick_count,
            "candles":     candle_count,
            "timestamp":   datetime.utcnow().isoformat(),
        }
        logger.info(
            f"Scenario '{name}' done — "
            f"{tick_count} ticks, {candle_count} candles."
        )
        return result

    # ─── Convenience builders ─────────────────────────────────────────────────

    async def inject_spread(
        self,
        pair:        str,
        buy_exchange: str, buy_price:  float,
        sell_exchange: str, sell_price: float,
        note:        str = "",
    ) -> None:
        """Inject a spread between two exchanges for spatial arbitrage testing."""
        spread_pct = ((sell_price - buy_price) / buy_price) * 100
        note = note or f"spread {spread_pct:.3f}%"
        await self.inject_tick(SyntheticTick(buy_exchange,  pair, buy_price,  note=f"{note} BUY"))
        await self.inject_tick(SyntheticTick(sell_exchange, pair, sell_price, note=f"{note} SELL"))

    async def inject_graph_cycle(
        self,
        ticks: List[tuple],
        note:  str = "graph cycle",
    ) -> None:
        """
        Inject prices that form a profitable graph cycle.
        ticks = [(exchange, pair, price), ...]

        Example — profitable 3-hop cycle:
          [
            ("binance", "BTC/USDT", 65000),
            ("binance", "ETH/BTC",  0.04900),   # ETH slightly cheap vs BTC
            ("binance", "ETH/USDT", 3250),       # ETH slightly expensive vs USDT
          ]
        """
        for exchange, pair, price in ticks:
            await self.inject_tick(SyntheticTick(exchange, pair, price, note=note))

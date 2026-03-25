"""
Stream Subscriber — consumes all worker streams from the message bus.
Routes each message type to the appropriate handler in brain.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from analysis.context_engine import ContextEngine
from arbitrage.graph.currency_graph import CurrencyGraph
from brain.security.auth_manager import AuthManager
from config.loader import AppConfig
from messaging.bus import (
    MessageBus,
    STREAM_PRICES, STREAM_CANDLES, STREAM_ORDERBOOKS,
    STREAM_HEARTBEATS, STREAM_REGISTRATION,
    STREAM_ORDER_RESULTS, STREAM_BALANCES, STREAM_EVENTS,
)
from messaging.logging import get_logger
from storage.market_state import MarketState

logger = get_logger("brain.stream.subscriber")


class StreamSubscriber:
    """
    Subscribes to all worker-published streams.
    Verifies message authenticity, then routes to handlers.
    """

    def __init__(
        self,
        bus:            MessageBus,
        market_state:   MarketState,
        context_engine: ContextEngine,
        auth_manager:   AuthManager,
        config:         AppConfig,
        currency_graph: Optional[CurrencyGraph] = None,
    ):
        self._bus            = bus
        self._market         = market_state
        self._ctx_engine     = context_engine
        self._auth           = auth_manager
        self._config         = config
        self._verify_enabled = config.security.enabled
        self._graph          = currency_graph   # feeds graph arbitrage strategy

    async def run(self) -> None:
        await self._bus.subscribe(
            streams=[
                STREAM_PRICES, STREAM_CANDLES, STREAM_ORDERBOOKS,
                STREAM_HEARTBEATS, STREAM_REGISTRATION,
                STREAM_ORDER_RESULTS, STREAM_BALANCES,
            ],
            consumer_id="brain_subscriber",
            handler=self._route,
        )

    async def _route(self, stream: str, msg: dict) -> None:
        """Route message to handler based on stream name."""

        # Verify signature for data streams (not heartbeats — those verified by fleet monitor)
        if self._verify_enabled and stream not in (STREAM_HEARTBEATS, STREAM_REGISTRATION):
            valid, reason = self._auth.verify_message(
                {"payload": msg, "signature": msg.pop("_sig", "")},
                source_ip=msg.get("machine", ""),
            )
            if not valid:
                logger.warning(f"Message rejected [{stream}]: {reason}")
                return

        if stream == STREAM_PRICES:
            await self._on_price(msg)
        elif stream == STREAM_CANDLES:
            await self._on_candle(msg)
        elif stream == STREAM_ORDERBOOKS:
            self._on_orderbook(msg)
        elif stream == STREAM_HEARTBEATS:
            pass  # handled by FleetMonitor directly
        elif stream == STREAM_REGISTRATION:
            self._on_registration(msg)
        elif stream == STREAM_ORDER_RESULTS:
            self._on_order_result(msg)
        elif stream == STREAM_BALANCES:
            self._on_balance(msg)

    async def _on_price(self, msg: dict) -> None:
        exchange  = msg.get("exchange", "")
        pair      = msg.get("pair", "")
        price     = msg.get("price", 0.0)
        volume_24h = msg.get("volume_24h", 10_000.0)
        worker_id = msg.get("worker_id", "")

        if not exchange or not pair or not price:
            return

        # Update shared market state
        self._market.update_price(exchange, pair, price, worker_id)

        # Feed into currency graph for multi-hop arbitrage detection
        if self._graph is not None:
            self._graph.update_from_tick(
                exchange=exchange,
                pair=pair,
                price=price,
                volume_usd=volume_24h,
            )

        # Feed into per-context analysis engine
        signal = await self._ctx_engine.on_price_tick(exchange, pair, price)

        # Publish signal back to stream if generated
        if signal:
            await self._bus.publish_signal(signal.to_dict())

    async def _on_candle(self, msg: dict) -> None:
        exchange  = msg.get("exchange", "")
        pair      = msg.get("pair", "")
        timeframe = msg.get("timeframe", "1M")
        self._ctx_engine.on_candle(exchange, pair, timeframe, msg)
        self._market.update_candle(exchange, pair, timeframe, msg)

    def _on_orderbook(self, msg: dict) -> None:
        exchange = msg.get("exchange", "")
        pair     = msg.get("pair", "")
        if exchange and pair:
            self._market.update_orderbook(exchange, pair, msg)

    def _on_registration(self, msg: dict) -> None:
        worker_id = msg.get("worker_id", "")
        logger.info(f"Worker self-registered: {worker_id}")
        # Auto-register with a temporary secret if not already known
        if not self._auth.get_worker(worker_id):
            logger.warning(
                f"Worker {worker_id} is not pre-registered — "
                f"operating in open mode. Add to registry for production."
            )

    def _on_order_result(self, msg: dict) -> None:
        logger.info(
            f"Order result: worker={msg.get('worker_id')} "
            f"order={msg.get('order_id')} status={msg.get('status')}"
        )
        self._market.record_order_result(msg)

    def _on_balance(self, msg: dict) -> None:
        self._market.update_balance(
            exchange=msg.get("exchange", ""),
            asset=msg.get("asset", ""),
            free=msg.get("free", 0.0),
            locked=msg.get("locked", 0.0),
            usd_value=msg.get("usd_value", 0.0),
            worker_id=msg.get("worker_id", ""),
        )

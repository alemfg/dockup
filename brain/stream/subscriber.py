"""
Stream Subscriber — consumes all worker streams from the message bus.
v3.3: Routes signals to decision engine, order results to position tracker and order log.
"""
from __future__ import annotations

from typing import Optional

from analysis.context_engine import ContextEngine
from arbitrage.graph.currency_graph import CurrencyGraph
from brain.security.auth_manager import AuthManager
from config.loader import AppConfig
from messaging.bus import (
    MessageBus,
    STREAM_PRICES, STREAM_CANDLES, STREAM_ORDERBOOKS,
    STREAM_HEARTBEATS, STREAM_REGISTRATION,
    STREAM_ORDER_RESULTS, STREAM_BALANCES,
)
from messaging.logging import get_logger
from storage.market_state import MarketState

logger = get_logger("brain.stream.subscriber")


class StreamSubscriber:

    def __init__(
        self,
        bus:              MessageBus,
        market_state:     MarketState,
        context_engine:   ContextEngine,
        auth_manager:     AuthManager,
        config:           AppConfig,
        currency_graph:   Optional[CurrencyGraph] = None,
        decision_engine=None,
        position_tracker=None,
        order_log=None,
        risk_manager=None,
        alert_sender=None,
    ):
        self._bus             = bus
        self._market          = market_state
        self._ctx_engine      = context_engine
        self._auth            = auth_manager
        self._config          = config
        self._verify_enabled  = config.security.enabled
        self._graph           = currency_graph
        self._decision        = decision_engine
        self._positions       = position_tracker
        self._order_log       = order_log
        self._risk            = risk_manager
        self._alert           = alert_sender

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
        if self._verify_enabled and stream not in (STREAM_HEARTBEATS, STREAM_REGISTRATION):
            # Check if this worker is known (may have registered via STREAM_REGISTRATION)
            worker_id = msg.get("worker_id", "")
            if worker_id and not self._auth.get_worker(worker_id):
                # Worker not yet registered — auto-register in open mode immediately.
                # This handles the race where price ticks arrive before the
                # registration message is consumed from the stream.
                self._auth.auto_register_worker(worker_id, msg)
                logger.info(
                    f"Worker {worker_id} auto-registered on first data message (open mode)."
                )

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
            pass
        elif stream == STREAM_REGISTRATION:
            self._on_registration(msg)
        elif stream == STREAM_ORDER_RESULTS:
            await self._on_order_result(msg)
        elif stream == STREAM_BALANCES:
            self._on_balance(msg)

    async def _on_price(self, msg: dict) -> None:
        exchange   = msg.get("exchange", "")
        pair       = msg.get("pair", "")
        price      = msg.get("price", 0.0)
        volume_24h = msg.get("volume_24h", 10_000.0)
        worker_id  = msg.get("worker_id", "")

        if not exchange or not pair or not price:
            return

        self._market.update_price(exchange, pair, price, worker_id)
        logger.debug(f"[TICK] {exchange} {pair} = {price}")

        if self._graph is not None:
            self._graph.update_from_tick(exchange=exchange, pair=pair,
                                         price=price, volume_usd=volume_24h)

        # Position tracker — check SL/TP on every tick
        if self._positions:
            actions = self._positions.on_price_tick(exchange, pair, price)
            for action in actions:
                event = action.get("event", "")
                pos   = action.get("position", {})
                if event in ("sl_hit", "tp2_hit"):
                    # Record close in order log and notify risk manager
                    pnl = pos.get("pnl_usd", 0.0)
                    if self._order_log:
                        self._order_log.record_close(
                            pos.get("order_id", ""), event, pnl, price
                        )
                    if self._risk:
                        self._risk.record_result(pnl)
                    logger.info(f"[POSITION] {event} for {pair} @ {price} | PnL=${pnl:+.2f}")

        # Analysis engine
        signal = await self._ctx_engine.on_price_tick(exchange, pair, price)

        if signal:
            await self._bus.publish_signal(signal.to_dict())

            # Feed CR signals into decision engine
            if self._decision:
                for pr in signal.plugin_results:
                    if pr.signal_type == "cr_9am_setup" and pr.data:
                        await self._decision.on_cr_signal(pr.data)

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
        if not worker_id:
            return
        if not self._auth.get_worker(worker_id):
            # Worker sent a valid registration but has no pre-shared key.
            # Auto-register it in "open mode" — no HMAC key, all messages pass.
            self._auth.auto_register_worker(worker_id, msg)
            logger.info(
                f"Worker {worker_id} auto-registered (open mode — no pre-shared key)."
            )
        else:
            logger.info(f"Worker {worker_id} re-registered (already known).")

    async def _on_order_result(self, msg: dict) -> None:
        order_id = msg.get("order_id", "")
        status   = msg.get("status", "")
        source   = msg.get("source", "")

        logger.info(
            f"Order result: worker={msg.get('worker_id')} "
            f"order={order_id} status={status}"
            + (f" [SYNC]" if source == "exchange_sync" else "")
        )

        # Update order log
        if self._order_log:
            if source == "exchange_sync":
                self._order_log.sync_exchange_order(order_id, msg)
            else:
                self._order_log.record_result(msg)

        # Open a position when an order fills
        if self._positions and status in ("filled", "closed") and source != "exchange_sync":
            order_record = self._order_log.get(order_id) if self._order_log else None
            if order_record:
                from messaging.models import OrderCommand, OrderSide, OrderType, SignalSource
                try:
                    cmd = OrderCommand(
                        id           = order_id,
                        exchange     = order_record.get("exchange", ""),
                        pair         = order_record.get("pair", ""),
                        side         = OrderSide(order_record.get("side", "buy")),
                        order_type   = OrderType(order_record.get("order_type", "limit")),
                        price        = order_record.get("price", 0.0),
                        volume       = msg.get("filled_volume", order_record.get("volume", 0.0)),
                        capital_usd  = order_record.get("capital_usd", 0.0),
                        stop_loss    = order_record.get("stop_loss", 0.0),
                        take_profit_1 = order_record.get("take_profit_1", 0.0),
                        take_profit_2 = order_record.get("take_profit_2", 0.0),
                        source       = SignalSource(order_record.get("source", "manual")),
                    )
                    fill_price = msg.get("filled_price", cmd.price)
                    self._positions.open_position(cmd, fill_price)
                except Exception as exc:
                    logger.warning(f"Could not open position for order {order_id}: {exc}")

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

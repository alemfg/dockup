"""
Message Bus — Redis Streams implementation.
All communication between brain, workers, and worker_manager
flows through named streams. Interface is abstracted so Redis
can be swapped for NATS without changing callers.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from messaging.logging import get_logger

logger = get_logger("messaging.bus")

# ─── Stream Names ─────────────────────────────────────────────────────────────
STREAM_PRICES       = "stream:prices"
STREAM_CANDLES      = "stream:candles"
STREAM_ORDERBOOKS   = "stream:orderbooks"
STREAM_HEARTBEATS   = "stream:heartbeats"
STREAM_REGISTRATION = "stream:registration"
STREAM_ORDERS       = "stream:orders"
STREAM_ORDER_RESULTS= "stream:order_results"
STREAM_SPAWN        = "stream:spawn_requests"
STREAM_WORKER_CMD   = "stream:worker_commands"
STREAM_EVENTS       = "stream:events"
STREAM_SIGNALS      = "stream:signals"
STREAM_BALANCES     = "stream:balances"


class MessageBus:
    """
    Async Redis Streams message bus.
    Workers publish data; brain subscribes and processes.
    Brain publishes commands; workers subscribe and execute.
    """

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self._host = host
        self._port = port
        self._db   = db
        self._redis = None
        self._consumer_group = "brain"

    async def connect(self) -> None:
        import redis.asyncio as aioredis
        self._redis = aioredis.Redis(
            host=self._host,
            port=self._port,
            db=self._db,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        await self._redis.ping()
        logger.info(f"MessageBus connected to Redis {self._host}:{self._port}")

        # Ensure consumer groups exist for all streams
        streams = [
            STREAM_PRICES, STREAM_CANDLES, STREAM_ORDERBOOKS,
            STREAM_HEARTBEATS, STREAM_REGISTRATION,
            STREAM_ORDERS, STREAM_ORDER_RESULTS,
            STREAM_SPAWN, STREAM_WORKER_CMD,
            STREAM_EVENTS, STREAM_SIGNALS, STREAM_BALANCES,
        ]
        for stream in streams:
            try:
                await self._redis.xgroup_create(stream, self._consumer_group, id="0", mkstream=True)
            except Exception:
                pass  # group already exists

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.aclose()
            logger.info("MessageBus disconnected.")

    # ─── Publish ─────────────────────────────────────────────────────────────

    async def publish(self, stream: str, message: dict, maxlen: int = 10000) -> str:
        """Publish a message to a stream. Returns message ID."""
        if not self._redis:
            raise RuntimeError("MessageBus not connected")
        payload = {"data": json.dumps(message), "ts": str(time.time())}
        msg_id = await self._redis.xadd(stream, payload, maxlen=maxlen, approximate=True)
        return msg_id

    # ─── Subscribe ───────────────────────────────────────────────────────────

    async def subscribe(
        self,
        streams: List[str],
        consumer_id: str,
        handler: Callable[[str, dict], Any],
        batch_size: int = 10,
        block_ms:   int = 1000,
    ) -> None:
        """
        Subscribe to one or more streams as a consumer group member.
        Calls handler(stream_name, message_dict) for each message.
        Automatically acknowledges after handler completes.
        """
        if not self._redis:
            raise RuntimeError("MessageBus not connected")

        stream_ids = {s: ">" for s in streams}

        logger.info(f"Subscribing to {streams} as consumer '{consumer_id}'")

        while True:
            try:
                results = await self._redis.xreadgroup(
                    groupname=self._consumer_group,
                    consumername=consumer_id,
                    streams=stream_ids,
                    count=batch_size,
                    block=block_ms,
                )
                if not results:
                    continue

                for stream_name, messages in results:
                    for msg_id, fields in messages:
                        try:
                            data = json.loads(fields.get("data", "{}"))
                            await handler(stream_name, data)
                            await self._redis.xack(stream_name, self._consumer_group, msg_id)
                        except Exception as exc:
                            logger.error(f"Handler error [{stream_name}]: {exc}")

                # Yield to event loop after every batch so API/other tasks
                # can run even under heavy stream load
                await asyncio.sleep(0)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Subscribe loop error: {exc}")
                await asyncio.sleep(1)

    async def subscribe_simple(
        self,
        stream: str,
        last_id: str = "$",
        block_ms: int = 1000,
    ) -> AsyncGenerator[dict, None]:
        """
        Simple non-group subscription — for brain internal consumers
        that don't need group semantics (e.g. WebSocket broadcast).
        """
        current_id = last_id
        while True:
            results = await self._redis.xread(
                streams={stream: current_id},
                count=50,
                block=block_ms,
            )
            if results:
                for _, messages in results:
                    for msg_id, fields in messages:
                        current_id = msg_id
                        try:
                            yield json.loads(fields.get("data", "{}"))
                        except Exception:
                            pass

    # ─── Typed Publishers (used by workers) ──────────────────────────────────

    async def publish_price_tick(self, tick: dict) -> None:
        await self.publish(STREAM_PRICES, tick)

    async def publish_candle(self, candle: dict) -> None:
        await self.publish(STREAM_CANDLES, candle)

    async def publish_orderbook(self, book: dict) -> None:
        await self.publish(STREAM_ORDERBOOKS, book, maxlen=5000)

    async def publish_heartbeat(self, heartbeat: dict) -> None:
        await self.publish(STREAM_HEARTBEATS, heartbeat, maxlen=1000)

    async def publish_registration(self, registration: dict) -> None:
        await self.publish(STREAM_REGISTRATION, registration, maxlen=500)

    async def publish_order_result(self, result: dict) -> None:
        await self.publish(STREAM_ORDER_RESULTS, result, maxlen=5000)

    async def publish_balance(self, balance: dict) -> None:
        await self.publish(STREAM_BALANCES, balance, maxlen=2000)

    # ─── Typed Publishers (used by brain) ────────────────────────────────────

    async def publish_order_command(self, command: dict) -> None:
        await self.publish(STREAM_ORDERS, command, maxlen=2000)

    async def publish_spawn_request(self, request: dict) -> None:
        await self.publish(STREAM_SPAWN, request, maxlen=500)

    async def publish_worker_command(self, command: dict) -> None:
        await self.publish(STREAM_WORKER_CMD, command, maxlen=500)

    async def publish_event(self, event: dict) -> None:
        await self.publish(STREAM_EVENTS, event, maxlen=5000)

    async def publish_signal(self, signal: dict) -> None:
        await self.publish(STREAM_SIGNALS, signal, maxlen=2000)

    # ─── Utility ─────────────────────────────────────────────────────────────

    async def stream_length(self, stream: str) -> int:
        return await self._redis.xlen(stream)

    async def get_consumer_lag(self, stream: str) -> int:
        """Returns number of pending messages not yet processed by brain."""
        try:
            info = await self._redis.xpending(stream, self._consumer_group)
            return info.get("pending", 0)
        except Exception:
            return 0

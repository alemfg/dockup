"""
Worker — self-contained exchange connector.
Streams price ticks, candles, and orderbooks to the brain via message bus.
Receives and executes order commands from the brain.
Sends heartbeats every N seconds.
"""
from __future__ import annotations

import asyncio
import os
import platform
import random
import resource
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from messaging.bus import (
    MessageBus,
    STREAM_ORDERS, STREAM_WORKER_CMD,
)
from messaging.logging import get_logger, setup_logging
from messaging.models import WorkerCondition, WorkerStatus
from config.loader import _read_version

logger = get_logger("worker.main")


class Worker:
    """
    Self-contained exchange worker.
    Config is provided via environment variables or a bundle file.
    """

    def __init__(self):
        self.worker_id   = os.getenv("WORKER_ID",   f"worker-{os.getenv('EXCHANGE', 'unknown')}-{os.getpid()}")
        self.exchange    = os.getenv("EXCHANGE",     "binance")
        self.pairs       = os.getenv("PAIRS",        "BTC/USDT,ETH/USDT").split(",")
        self.machine     = os.getenv("MACHINE_ID",   platform.node())
        self.role        = os.getenv("ROLE",         "collector_only")
        self.secret_key  = os.getenv("WORKER_SECRET_KEY", "")
        self.redis_host  = os.getenv("REDIS_HOST",   "localhost")
        self.redis_port  = int(os.getenv("REDIS_PORT", "6379"))
        self.interval_ms = int(os.getenv("TICK_INTERVAL_MS", "2000"))
        self.is_replacement = os.getenv("IS_REPLACEMENT", "false").lower() == "true"
        self.replaced_worker = os.getenv("REPLACED_WORKER", "")

        self._bus:       Optional[MessageBus] = None
        self._running    = False
        self._status     = WorkerStatus.STARTING
        self._condition  = WorkerCondition.NONE
        self._error_count = 0
        self._last_error: Optional[str] = None
        self._ticks_this_minute = 0
        self._tick_minute_start = time.time()
        self._latency_samples: List[float] = []

        setup_logging()

    # ─── Startup ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info(f"Worker {self.worker_id} starting — exchange={self.exchange} pairs={self.pairs}")

        self._bus = MessageBus(host=self.redis_host, port=self.redis_port)
        await self._bus.connect()

        # Register with brain
        await self._register()

        self._running = True
        self._status  = WorkerStatus.HEALTHY

        await asyncio.gather(
            self._tick_loop(),
            self._heartbeat_loop(),
            self._command_listener(),
        )

    async def _register(self) -> None:
        await self._bus.publish_registration({
            "worker_id":          self.worker_id,
            "exchange":           self.exchange,
            "pairs":              self.pairs,
            "machine":            self.machine,
            "role":               self.role,
            "can_execute_orders": self.role == "collector_and_executor",
            "is_replacement":     self.is_replacement,
            "replaced_worker":    self.replaced_worker,
            "version":            _read_version(),
            "timestamp":          datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Worker {self.worker_id} registered.")

    # ─── Tick Loop ───────────────────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        """Main collection loop — fetch and publish prices."""
        while self._running:
            try:
                await self._collect_and_publish()
                self._status    = WorkerStatus.HEALTHY
                self._condition = WorkerCondition.NONE
            except Exception as exc:
                self._handle_error(exc)

            await asyncio.sleep(self.interval_ms / 1000)

    async def _collect_and_publish(self) -> None:
        """Fetch prices from exchange and publish to message bus."""
        for pair in self.pairs:
            t0 = time.time()
            price = await self._fetch_price(pair)
            latency_ms = (time.time() - t0) * 1000

            if price:
                self._latency_samples.append(latency_ms)
                if len(self._latency_samples) > 60:
                    self._latency_samples.pop(0)

                await self._bus.publish_price_tick({
                    "worker_id":  self.worker_id,
                    "exchange":   self.exchange,
                    "pair":       pair,
                    "price":      price,
                    "latency_ms": round(latency_ms, 2),
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                })
                self._ticks_this_minute += 1

    async def _fetch_price(self, pair: str) -> Optional[float]:
        """
        Fetch live price via CCXT if keys are configured,
        otherwise generate a realistic simulated price.
        """
        api_key = os.getenv(f"{self.exchange.upper()}_API_KEY", "")

        if api_key:
            try:
                import ccxt.async_support as ccxt
                client = getattr(ccxt, self.exchange)({
                    "apiKey":     api_key,
                    "secret":     os.getenv(f"{self.exchange.upper()}_API_SECRET", ""),
                    "enableRateLimit": True,
                })
                ticker = await client.fetch_ticker(pair)
                await client.close()
                return ticker["last"]
            except Exception as exc:
                raise exc

        # Simulation mode — realistic prices with noise
        base_prices = {
            "BTC/USDT": 65000.0, "ETH/USDT": 3200.0, "BNB/USDT": 420.0,
            "SOL/USDT": 145.0,   "XRP/USDT": 0.62,   "ADA/USDT": 0.58,
            "DOGE/USDT": 0.12,   "AVAX/USDT": 38.0,  "LINK/USDT": 14.2,
            "UNI/USDT": 9.8,     "EUR/USD": 1.085,
        }
        base = base_prices.get(pair, 100.0)
        noise = random.uniform(-0.003, 0.003)
        return round(base * (1 + noise), 6)

    # ─── Heartbeat Loop ──────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(5)

            # Compute ticks/min
            elapsed = time.time() - self._tick_minute_start
            if elapsed >= 60:
                self._ticks_this_minute = 0
                self._tick_minute_start = time.time()

            avg_latency = (
                sum(self._latency_samples) / len(self._latency_samples)
                if self._latency_samples else 0.0
            )

            # CPU/memory (approximate)
            try:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                mem_mb = usage.ru_maxrss / 1024
            except Exception:
                mem_mb = 0.0

            await self._bus.publish_heartbeat({
                "worker_id":        self.worker_id,
                "exchange":         self.exchange,
                "pairs":            self.pairs,
                "machine":          self.machine,
                "status":           self._status.value,
                "condition":        self._condition.value,
                "ticks_last_60s":   self._ticks_this_minute,
                "latency_ms":       round(avg_latency, 2),
                "error_count":      self._error_count,
                "last_error":       self._last_error,
                "cpu_pct":          0.0,  # platform-dependent, simplified
                "memory_mb":        round(mem_mb, 1),
                "is_replacement":   self.is_replacement,
                "replaced_worker":  self.replaced_worker,
                "timestamp":        datetime.now(timezone.utc).isoformat(),
            })

    # ─── Command Listener ────────────────────────────────────────────────────

    async def _command_listener(self) -> None:
        """Listen for brain commands (kill, pair reassignment, orders)."""
        async def handler(stream: str, msg: dict) -> None:
            target = msg.get("worker_id", "")
            if target and target != self.worker_id:
                return

            cmd = msg.get("command", "")

            if cmd == "kill":
                logger.info(f"Received kill command — shutting down.")
                self._running = False

            elif cmd == "reassign_pairs":
                new_pairs = msg.get("pairs", self.pairs)
                logger.info(f"Pair reassignment: {self.pairs} → {new_pairs}")
                self.pairs = new_pairs

            elif cmd == "execute_order" and self.role == "collector_and_executor":
                await self._execute_order(msg.get("order", {}))

        await self._bus.subscribe(
            streams=[STREAM_WORKER_CMD, STREAM_ORDERS],
            consumer_id=self.worker_id,
            handler=handler,
        )

    async def _execute_order(self, order: dict) -> None:
        """Execute a trade order (dry-run by default)."""
        dry_run = order.get("dry_run", True)
        logger.info(
            f"[{'DRYRUN' if dry_run else 'LIVE'}] "
            f"{order.get('side','BUY').upper()} {order.get('pair')} "
            f"@ {order.get('price')} vol={order.get('volume')}"
        )
        # Publish result back to brain
        await self._bus.publish_order_result({
            "worker_id":   self.worker_id,
            "order_id":    order.get("order_id"),
            "status":      "simulated" if dry_run else "sent",
            "filled_price": order.get("price"),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        })

    # ─── Error Handling ──────────────────────────────────────────────────────

    def _handle_error(self, exc: Exception) -> None:
        self._error_count += 1
        self._last_error = str(exc)
        error_str = str(exc).lower()

        if any(p in error_str for p in ["403", "418", "banned", "forbidden"]):
            self._condition = WorkerCondition.IP_BLOCK
            self._status    = WorkerStatus.BLOCKED
            logger.error(f"IP BLOCK detected on {self.exchange}: {exc}")
        elif "429" in error_str or "rate limit" in error_str:
            self._condition = WorkerCondition.RATE_LIMIT
            self._status    = WorkerStatus.DEGRADED
            logger.warning(f"Rate limited on {self.exchange}: {exc}")
        else:
            self._status = WorkerStatus.DEGRADED
            logger.error(f"Worker error: {exc}")


def run():
    worker = Worker()
    asyncio.run(worker.start())


if __name__ == "__main__":
    run()

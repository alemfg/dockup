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
        self._balance_interval = int(os.getenv("BALANCE_INTERVAL_S", "60"))  # v3.2
        self._sync_interval    = int(os.getenv("ORDER_SYNC_INTERVAL_S", "30"))  # v3.3

        # Persistent CCXT client — created once if API key present, reused for all ticks
        self._ccxt_client = None

        setup_logging()

    # ─── Startup ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info(f"Worker {self.worker_id} starting — exchange={self.exchange} pairs={self.pairs}")

        self._bus = MessageBus(host=self.redis_host, port=self.redis_port)
        await self._bus.connect()

        # Initialise persistent exchange client once if API keys are present
        api_key = os.getenv(f"{self.exchange.upper()}_API_KEY", "")
        if api_key:
            try:
                import ccxt.async_support as ccxt
                self._ccxt_client = getattr(ccxt, self.exchange)({
                    "apiKey":          api_key,
                    "secret":          os.getenv(f"{self.exchange.upper()}_API_SECRET", ""),
                    "enableRateLimit": True,
                })
                logger.info(f"CCXT client initialised for {self.exchange} (live mode)")
            except Exception as exc:
                logger.error(f"Failed to initialise CCXT client for {self.exchange}: {exc}")
                self._ccxt_client = None

        # Register with brain
        await self._register()

        self._running = True
        self._status  = WorkerStatus.HEALTHY

        await asyncio.gather(
            self._tick_loop(),
            self._heartbeat_loop(),
            self._command_listener(),
            self._balance_loop(),
            self._order_sync_loop(),
        )

        # Clean up persistent CCXT client on shutdown
        if self._ccxt_client:
            try:
                await self._ccxt_client.close()
            except Exception:
                pass

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
        Fetch live price via the persistent CCXT client (initialised once at startup).
        Falls back to simulation if no API key is configured.
        """
        if self._ccxt_client:
            try:
                ticker = await self._ccxt_client.fetch_ticker(pair)
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
        base  = base_prices.get(pair, 100.0)
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

    # ─── Balance Loop ────────────────────────────────────────────────────────

    async def _balance_loop(self) -> None:
        """Fetch and publish exchange balances every BALANCE_INTERVAL_S seconds.
        Only runs when the persistent CCXT client was initialised (i.e. API key present)."""
        if not self._ccxt_client:
            logger.info(f"No CCXT client for {self.exchange} — balance fetching disabled.")
            return

        while self._running:
            try:
                await self._fetch_and_publish_balances()
            except Exception as exc:
                logger.warning(f"Balance fetch error ({self.exchange}): {exc}")
            await asyncio.sleep(self._balance_interval)

    async def _fetch_and_publish_balances(self) -> None:
        """Fetch real balances using the persistent CCXT client and publish to bus."""
        if not self._ccxt_client:
            return

        raw = await self._ccxt_client.fetch_balance()

        # Build a price map from already-known market state to estimate USD values
        # without making extra API calls — use ticker cache if available
        ticker_cache: dict = {}
        try:
            tickers = await self._ccxt_client.fetch_tickers()
            ticker_cache = {sym: t["last"] for sym, t in tickers.items() if t.get("last")}
        except Exception:
            pass  # USD estimation is best-effort — missing it is not fatal

        for asset, total in raw.get("total", {}).items():
            if not total or total == 0:
                continue
            free   = raw.get("free", {}).get(asset, 0.0) or 0.0
            locked = raw.get("used", {}).get(asset, 0.0) or 0.0

            usd_value = 0.0
            for quote in ("USDT", "USDC", "USD"):
                price = ticker_cache.get(f"{asset}/{quote}") or ticker_cache.get(f"{asset}{quote}")
                if price:
                    usd_value = round(free * price, 2)
                    break

            await self._bus.publish_balance({
                "worker_id": self.worker_id,
                "exchange":  self.exchange,
                "asset":     asset,
                "free":      free,
                "locked":    locked,
                "usd_value": usd_value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        logger.info(f"Published balances for {self.exchange} ({len(raw.get('total', {}))} assets)")

    # ─── Order Sync Loop (v3.3) ──────────────────────────────────────────────

    async def _order_sync_loop(self) -> None:
        """
        Fetch open orders from the exchange every ORDER_SYNC_INTERVAL_S seconds
        and publish them so the brain can reconcile its internal order log.
        Also detects manual orders and cancellations placed outside ARBX.
        Only runs when API keys are configured.
        """
        if not self._ccxt_client:
            return

        while self._running:
            await asyncio.sleep(self._sync_interval)
            try:
                open_orders = await self._ccxt_client.fetch_open_orders()
                logger.debug(f"[SYNC] {self.exchange}: {len(open_orders)} open orders on exchange")

                for o in open_orders:
                    await self._bus.publish_order_result({
                        "worker_id":         self.worker_id,
                        "exchange":          self.exchange,
                        "order_id":          o.get("clientOrderId") or o.get("id", ""),
                        "exchange_order_id": o.get("id", ""),
                        "status":            o.get("status", "open"),
                        "filled_price":      o.get("average") or o.get("price", 0.0),
                        "filled_volume":     o.get("filled", 0.0),
                        "side":              o.get("side", ""),
                        "pair":              o.get("symbol", ""),
                        "source":            "exchange_sync",
                        "timestamp":         datetime.now(timezone.utc).isoformat(),
                    })

                # Also check recently closed orders for fills/cancellations
                closed_orders = await self._ccxt_client.fetch_orders(limit=20)
                for o in closed_orders:
                    if o.get("status") in ("closed", "canceled", "cancelled", "expired"):
                        await self._bus.publish_order_result({
                            "worker_id":         self.worker_id,
                            "exchange":          self.exchange,
                            "order_id":          o.get("clientOrderId") or o.get("id", ""),
                            "exchange_order_id": o.get("id", ""),
                            "status":            o.get("status", ""),
                            "filled_price":      o.get("average") or o.get("price", 0.0),
                            "filled_volume":     o.get("filled", 0.0),
                            "fees_paid":         o.get("fee", {}).get("cost", 0.0) if o.get("fee") else 0.0,
                            "fees_currency":     o.get("fee", {}).get("currency", "") if o.get("fee") else "",
                            "side":              o.get("side", ""),
                            "pair":              o.get("symbol", ""),
                            "source":            "exchange_sync",
                            "timestamp":         datetime.now(timezone.utc).isoformat(),
                        })

            except Exception as exc:
                logger.warning(f"[SYNC] Order sync error ({self.exchange}): {exc}")

    async def _execute_order(self, order: dict) -> None:
        """
        Execute a trade order via CCXT.
        v3.3: Supports OCO (entry + SL + TP in one) where available.
        Falls back to limit order + separate stop-limit for non-OCO exchanges.
        """
        dry_run      = order.get("dry_run", True)
        pair         = order.get("pair", "")
        side         = order.get("side", "buy")
        order_type   = order.get("order_type", "limit")
        price        = order.get("price", 0.0)
        volume       = order.get("volume", 0.0)
        stop_loss    = order.get("stop_loss", 0.0)
        take_profit  = order.get("take_profit_1", 0.0)
        order_id     = order.get("id", "")

        log_prefix = f"[{'DRYRUN' if dry_run else 'LIVE'}]"
        logger.info(
            f"{log_prefix} {side.upper()} {pair} @ {price} "
            f"vol={volume} SL={stop_loss} TP={take_profit}"
        )

        if dry_run or not self._ccxt_client:
            await self._bus.publish_order_result({
                "worker_id":         self.worker_id,
                "exchange":          self.exchange,
                "order_id":          order_id,
                "exchange_order_id": f"sim_{order_id[:8]}",
                "status":            "simulated",
                "filled_price":      price,
                "filled_volume":     volume,
                "fees_paid":         0.0,
                "slippage_pct":      0.0,
                "execution_time_ms": 0.0,
                "timestamp":         datetime.now(timezone.utc).isoformat(),
            })
            return

        # Live execution
        t0 = time.time()
        try:
            # Attempt OCO if exchange supports it and SL/TP are set
            oco_exchanges = {"binance", "coinbase", "bybit"}
            result = None

            if self.exchange in oco_exchanges and stop_loss and take_profit:
                try:
                    # Binance OCO: place a limit + stop-limit + take-profit in one call
                    result = await self._ccxt_client.create_order(
                        symbol     = pair,
                        type       = "oco",
                        side       = side,
                        amount     = volume,
                        price      = take_profit,
                        params     = {
                            "stopPrice":           stop_loss,
                            "stopLimitPrice":      stop_loss * (0.999 if side == "sell" else 1.001),
                            "stopLimitTimeInForce": "GTC",
                        }
                    )
                    logger.info(f"[LIVE] OCO order placed: {result.get('id')}")
                except Exception as oco_exc:
                    logger.warning(f"OCO failed ({oco_exc}), falling back to limit order")
                    result = None

            if result is None:
                # Standard limit order
                result = await self._ccxt_client.create_order(
                    symbol = pair,
                    type   = order_type if order_type != "oco" else "limit",
                    side   = side,
                    amount = volume,
                    price  = price if order_type != "market" else None,
                )
                logger.info(f"[LIVE] Limit order placed: {result.get('id')}")

                # Place separate stop-limit if no OCO and SL is set
                sl_order_id = ""
                if stop_loss and self.exchange not in oco_exchanges:
                    try:
                        sl_side  = "sell" if side == "buy" else "buy"
                        sl_order = await self._ccxt_client.create_order(
                            symbol = pair,
                            type   = "stop_limit",
                            side   = sl_side,
                            amount = volume,
                            price  = stop_loss * (0.999 if sl_side == "sell" else 1.001),
                            params = {"stopPrice": stop_loss},
                        )
                        sl_order_id = sl_order.get("id", "")
                        logger.info(f"[LIVE] Stop-limit placed: {sl_order_id}")
                    except Exception as sl_exc:
                        logger.warning(f"Stop-limit placement failed: {sl_exc}")

            elapsed_ms = (time.time() - t0) * 1000
            filled_price = result.get("average") or result.get("price") or price

            await self._bus.publish_order_result({
                "worker_id":         self.worker_id,
                "exchange":          self.exchange,
                "order_id":          order_id,
                "exchange_order_id": result.get("id", ""),
                "status":            result.get("status", "sent"),
                "filled_price":      filled_price,
                "filled_volume":     result.get("filled", volume),
                "fees_paid":         result.get("fee", {}).get("cost", 0.0) if result.get("fee") else 0.0,
                "fees_currency":     result.get("fee", {}).get("currency", "") if result.get("fee") else "",
                "slippage_pct":      abs(filled_price - price) / max(price, 1) * 100,
                "execution_time_ms": round(elapsed_ms, 2),
                "stop_loss_order_id": sl_order_id if "sl_order_id" in dir() else "",
                "timestamp":         datetime.now(timezone.utc).isoformat(),
            })

        except Exception as exc:
            logger.error(f"[LIVE] Order execution failed: {exc}")
            await self._bus.publish_order_result({
                "worker_id":   self.worker_id,
                "exchange":    self.exchange,
                "order_id":    order_id,
                "status":      "failed",
                "error":       str(exc),
                "timestamp":   datetime.now(timezone.utc).isoformat(),
            })

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

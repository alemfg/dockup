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
from worker.rate_limit import RateLimitGuard

logger = get_logger("worker.main")


class Worker:
    """
    Self-contained exchange worker.
    Config is provided via environment variables or a bundle file.
    """

    def __init__(self):
        self.worker_id   = os.getenv("WORKER_ID",   f"worker-{os.getenv('EXCHANGE', 'unknown')}-{os.getpid()}")
        self.exchange    = os.getenv("EXCHANGE",     "binance")
        self.machine     = os.getenv("MACHINE_ID",   platform.node())
        self.role        = os.getenv("ROLE",         "collector_only")
        self.secret_key  = os.getenv("WORKER_SECRET_KEY", "")
        self.redis_host  = os.getenv("REDIS_HOST",   "localhost")
        self.redis_port  = int(os.getenv("REDIS_PORT", "6379"))
        self.interval_ms = int(os.getenv("TICK_INTERVAL_MS", "2000"))
        self.is_replacement  = os.getenv("IS_REPLACEMENT", "false").lower() == "true"
        self.replaced_worker = os.getenv("REPLACED_WORKER", "")

        # Pairs: "ALL" expands to every active spot market via CCXT load_markets().
        # Otherwise, provide a comma-separated list e.g. BTC/USDT,ETH/USDT
        _pairs_raw = os.getenv("PAIRS", "BTC/USDT,ETH/USDT").strip()
        self._pairs_mode = "all" if _pairs_raw.upper() == "ALL" else "explicit"
        self.pairs = [] if self._pairs_mode == "all" else [p.strip() for p in _pairs_raw.split(",") if p.strip()]

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
        self._candle_interval  = int(os.getenv("CANDLE_INTERVAL_S",  "60"))   # v4: fetch candles every N seconds
        self._candle_timeframes = os.getenv("CANDLE_TIMEFRAMES", "1m,5m,15m,1h").split(",")
        self._sync_interval    = int(os.getenv("ORDER_SYNC_INTERVAL_S", "30"))  # v3.3

        # Persistent CCXT client — created once if API key present, reused for all ticks
        self._ccxt_client = None
        self._paused      = False   # v4.1: pause ticks without disconnecting

        # v6.4: Per-exchange rate limit guard — token bucket + back-off
        self._rate_guard  = RateLimitGuard(
            exchange=self.exchange,
            tick_interval_ms=self.interval_ms,
        )

        setup_logging()

    # ─── Startup ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        build_ver  = os.getenv("ARBX_BUILD_VERSION", "dev")
        build_date = os.getenv("ARBX_BUILD_DATE", "unknown")
        logger.info(
            f"Worker {self.worker_id} starting — "
            f"exchange={self.exchange} "
            f"pairs={'ALL' if self._pairs_mode == 'all' else len(self.pairs)} "
            f"[image build: {build_ver} / {build_date}]"
        )

        self._bus = MessageBus(host=self.redis_host, port=self.redis_port)
        await self._bus.connect()

        # Initialise persistent exchange client once if API keys are present
        # v6.4: normalise exchange name to CCXT id (e.g. "gateio" → "gate")
        api_key = os.getenv(f"{self.exchange.upper()}_API_KEY", "")
        if api_key:
            try:
                import ccxt.async_support as ccxt
                from worker.rate_limit import ccxt_exchange_id as _ccxt_id
                _cid = _ccxt_id(self.exchange)
                self._ccxt_client = getattr(ccxt, _cid)({
                    "apiKey":          api_key,
                    "secret":          os.getenv(f"{self.exchange.upper()}_API_SECRET", ""),
                    "enableRateLimit": True,
                })
                logger.info(f"CCXT client initialised for {self.exchange} (ccxt={_cid}, live mode)")
            except Exception as exc:
                logger.error(f"Failed to initialise CCXT client for {self.exchange}: {exc}")
                self._ccxt_client = None

        # Resolve PAIRS=ALL → full market list from exchange
        if self._pairs_mode == "all":
            self.pairs = await self._resolve_all_pairs()

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
            self._candle_loop(),
        )

        # Clean up persistent CCXT client on shutdown
        if self._ccxt_client:
            try:
                await self._ccxt_client.close()
            except Exception:
                pass

    # ─── Pairs resolution ────────────────────────────────────────────────────

    # DEX exchanges don't expose a useful market list via CCXT public API.
    _DEX_DEFAULT_PAIRS: dict = {
        "uniswap":     ["ETH/USDT", "WBTC/USDT", "ETH/USDC", "LINK/USDT", "UNI/USDT", "MATIC/USDT"],
        "sushiswap":   ["ETH/USDT", "WBTC/USDT", "ETH/USDC", "SUSHI/USDT"],
        "pancakeswap": ["BNB/USDT", "ETH/USDT", "BTC/USDT", "CAKE/USDT"],
        "curve":       ["USDT/USDC", "USDT/DAI", "USDC/DAI"],
    }
    async def _resolve_all_pairs(self) -> List[str]:
        """
        Expand PAIRS=ALL to every active spot market on this exchange.
        Used when the worker is started manually (not via AutoSpawner).
        When spawned by AutoSpawner the pairs are already split and passed
        as an explicit list — ALL is resolved brain-side before spawning.

        DEX exchanges fall back to a curated default (no public market list).
        Quote filter: PAIRS_ALL_QUOTE_FILTER (default USDT,USDC,BTC,ETH).
        No hard cap — if you want to limit pairs use PAIRS_ALL_QUOTE_FILTER
        or set PAIRS_WORKER_SIZE so AutoSpawner splits across multiple workers.
        """
        exchange_lower = self.exchange.lower()

        if exchange_lower in self._DEX_DEFAULT_PAIRS:
            pairs = self._DEX_DEFAULT_PAIRS[exchange_lower]
            logger.info(
                f"[ALL] DEX {self.exchange} — curated default {len(pairs)} pairs. "
                f"Set explicit PAIRS= to override."
            )
            return pairs

        try:
            import ccxt.async_support as ccxt_async
            from worker.rate_limit import ccxt_exchange_id as _ccxt_id
            ccxt_id = _ccxt_id(exchange_lower)   # "gateio" → "gate", etc.
            ex = getattr(ccxt_async, ccxt_id)({"enableRateLimit": True})
            markets = await ex.load_markets()
            await ex.close()

            quote_filter_raw = os.getenv("PAIRS_ALL_QUOTE_FILTER", "USDT,USDC,BTC,ETH")
            allowed_quotes = {q.strip().upper() for q in quote_filter_raw.split(",") if q.strip()}

            pairs = sorted([
                symbol for symbol, mkt in markets.items()
                if mkt.get("active", True)
                and mkt.get("type", "spot") == "spot"
                and mkt.get("quote", "").upper() in allowed_quotes
                and "/" in symbol
            ])

            logger.info(f"[ALL] {self.exchange} expanded to {len(pairs)} pairs")
            if len(pairs) > 200:
                logger.warning(
                    f"[ALL] {self.exchange}: {len(pairs)} pairs on a single worker. "
                    f"Consider using EXCHANGES + AutoSpawner which splits automatically."
                )
            return pairs or ["BTC/USDT", "ETH/USDT"]

        except Exception as exc:
            logger.error(f"[ALL] load_markets failed for {self.exchange}: {exc} — using BTC/USDT,ETH/USDT")
            return ["BTC/USDT", "ETH/USDT"]

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
        if self._paused:
            return
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
        v6.4: Rate limit guard applied before every live request.
        """
        if self._ccxt_client:
            # Acquire a token from the bucket — blocks if budget exhausted
            await self._rate_guard.acquire()
            try:
                ticker = await self._ccxt_client.fetch_ticker(pair)
                self._rate_guard.on_success()
                return ticker["last"]
            except Exception as exc:
                exc_str = str(exc).lower()
                if "429" in exc_str or "rate limit" in exc_str or "too many requests" in exc_str:
                    await self._rate_guard.on_rate_limited()
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
        interval = int(os.getenv("HEARTBEAT_INTERVAL_S", "10"))
        while self._running:
            await asyncio.sleep(interval)

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
                "pair_count":       len(self.pairs),   # count only — full list sent at registration
                "machine":          self.machine,
                "status":           "paused" if self._paused else self._status.value,
                "condition":        self._condition.value,
                "ticks_last_60s":   self._ticks_this_minute,
                "latency_ms":       round(avg_latency, 2),
                "error_count":      self._error_count,
                "last_error":       self._last_error,
                "cpu_pct":          0.0,
                "memory_mb":        round(mem_mb, 1),
                "is_replacement":   self.is_replacement,
                "replaced_worker":  self.replaced_worker,
                "rate_limit":       self._rate_guard.status(),   # v6.4
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

    # ─── Candle Loop (v4) ────────────────────────────────────────────────────

    async def _candle_loop(self) -> None:
        """
        Fetch OHLCV candles from exchange every CANDLE_INTERVAL_S seconds.
        Publishes to STREAM_CANDLES so the CR plugin and analysis engine
        receive real candle data instead of empty arrays.

        CCXT timeframe mapping: 1m, 5m, 15m, 1h, 4h, 1d
        Fetches last 200 candles per timeframe per pair on startup,
        then incrementally every interval.
        """
        if not self._ccxt_client:
            logger.info(f"No CCXT client for {self.exchange} — candle fetching disabled (simulation mode).")
            return

        # Initial fetch on startup — get history
        await asyncio.sleep(5)  # let tick loop establish first
        for pair in self.pairs:
            for tf in self._candle_timeframes:
                await self._fetch_and_publish_candles(pair, tf, limit=200)
        logger.info(f"[CANDLES] Initial fetch complete for {self.exchange}")

        while self._running:
            await asyncio.sleep(self._candle_interval)
            for pair in self.pairs:
                for tf in self._candle_timeframes:
                    await self._fetch_and_publish_candles(pair, tf, limit=10)

    async def _fetch_and_publish_candles(
        self, pair: str, timeframe: str, limit: int = 10
    ) -> None:
        """Fetch OHLCV and publish each candle to the bus."""
        try:
            # CCXT timeframe → internal label
            tf_map = {"1m": "1M", "5m": "5M", "15m": "15M", "1h": "1H", "4h": "4H", "1d": "1D"}
            tf_label = tf_map.get(timeframe, timeframe.upper())

            ohlcv = await self._ccxt_client.fetch_ohlcv(pair, timeframe, limit=limit)
            for bar in ohlcv:
                ts, o, h, l, c, v = bar
                await self._bus.publish_candle({
                    "worker_id": self.worker_id,
                    "exchange":  self.exchange,
                    "pair":      pair,
                    "timeframe": tf_label,
                    "time":      ts,
                    "open":      o,
                    "high":      h,
                    "low":       l,
                    "close":     c,
                    "volume":    v,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            logger.debug(
                f"[CANDLES] {self.exchange} {pair} {timeframe}: "
                f"published {len(ohlcv)} candles"
            )
        except Exception as exc:
            logger.warning(f"[CANDLES] Fetch error {self.exchange} {pair} {timeframe}: {exc}")

    # ─── Order Sync Loop (v3.3) ──────────────────────────────────────────────

    async def _order_sync_loop(self) -> None:
        """
        Fetch open orders per-pair (avoids broad rate limit warnings on Binance).
        fetch_orders() is skipped for exchanges that don't support it (e.g. Kraken).
        """
        if not self._ccxt_client:
            return

        # Suppress Binance's broad-fetch warning by always passing a symbol
        # Suppress it at the CCXT level too
        try:
            self._ccxt_client.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
        except Exception:
            pass

        # Exchanges that don't support fetch_orders() — use fetch_open_orders() only
        no_fetch_orders = {"kraken", "kucoin", "okx", "huobi", "gate"}

        while self._running:
            await asyncio.sleep(self._sync_interval)
            try:
                # Fetch per-pair to stay within rate limits
                for pair in self.pairs:
                    try:
                        open_orders = await self._ccxt_client.fetch_open_orders(pair)
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
                    except Exception as pair_exc:
                        logger.debug(f"[SYNC] open_orders {pair}: {pair_exc}")

                # Fetch closed orders per-pair (skip unsupported exchanges)
                if self.exchange.lower() not in no_fetch_orders:
                    for pair in self.pairs:
                        try:
                            closed = await self._ccxt_client.fetch_orders(pair, limit=10)
                            for o in closed:
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
                        except Exception as pair_exc:
                            logger.debug(f"[SYNC] closed_orders {pair}: {pair_exc}")

                logger.debug(f"[SYNC] {self.exchange}: sync complete for {len(self.pairs)} pairs")

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

            elif cmd == "reload_config":
                self._reload_config()
                logger.info(f"Worker config reloaded.")

            elif cmd == "pause":
                self._paused = True
                logger.info(f"Worker {self.worker_id} paused — ticks suspended.")

            elif cmd == "resume":
                self._paused = False
                logger.info(f"Worker {self.worker_id} resumed.")

            elif cmd == "reassign_pairs":
                new_pairs = msg.get("pairs", self.pairs)
                logger.info(f"Pair reassignment: {self.pairs} → {new_pairs}")
                self.pairs = new_pairs

            elif cmd == "set_tick_interval":
                # v6.4: Brain-side throttle command — adjusts poll rate for this exchange
                new_ms = int(msg.get("interval_ms", self.interval_ms))
                old_ms = self.interval_ms
                self.interval_ms = max(500, new_ms)   # floor at 500ms
                self._rate_guard.update_tick_interval(self.interval_ms)
                logger.warning(
                    f"[RateLimit] Tick interval changed by brain: "
                    f"{old_ms}ms → {self.interval_ms}ms"
                )

            elif cmd == "execute_order" and self.role == "collector_and_executor":
                await self._execute_order(msg.get("order", {}))

        await self._bus.subscribe(
            streams=[STREAM_WORKER_CMD, STREAM_ORDERS],
            consumer_id=self.worker_id,
            handler=handler,
        )



    # ─── Config Reload ───────────────────────────────────────────────────────

    def _reload_config(self) -> None:
        """Re-read environment variables and apply updated config at runtime."""
        import importlib
        import config.loader as loader_mod
        loader_mod.reload_config()

        # Re-apply tunable worker settings from env
        self.interval_ms       = int(os.getenv("TICK_INTERVAL_MS",      str(self.interval_ms)))
        self._balance_interval = int(os.getenv("BALANCE_INTERVAL_S",    str(self._balance_interval)))
        self._sync_interval    = int(os.getenv("ORDER_SYNC_INTERVAL_S", str(self._sync_interval)))

        # v6.4: Keep rate guard in sync with new tick interval
        self._rate_guard.update_tick_interval(self.interval_ms)

        new_pairs_raw = os.getenv("PAIRS", "").strip()
        if new_pairs_raw:
            if new_pairs_raw.upper() == "ALL":
                # Schedule async resolution — can't await here, log and skip
                logger.info("[reload] PAIRS=ALL detected — pairs unchanged until next restart")
            else:
                self.pairs = [p.strip() for p in new_pairs_raw.split(",") if p.strip()]
        logger.info(
            f"Worker config reloaded | "
            f"tick={self.interval_ms}ms pairs={self.pairs}"
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

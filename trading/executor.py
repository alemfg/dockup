"""
Order Execution Engine (v6.1)
Consumes STREAM_ORDERS from Redis and sends orders to exchanges via CCXT.

Flow:
  DecisionEngine → bus.publish_order_command() → STREAM_ORDERS
  → OrderExecutor.run() → CCXT create_order()
  → bus.publish_order_result() → STREAM_ORDER_RESULTS
  → StreamSubscriber._on_order_result() → PositionTracker.open_position()

Modes:
  SIMULATE  — logs the order, publishes a synthetic fill result (no CCXT call)
  LIVE      — calls CCXT, publishes the real fill result

API key source (priority order):
  1. arbx_api_keys DB table (via ConfigStore)
  2. {EXCHANGE}_API_KEY / {EXCHANGE}_API_SECRET env vars (legacy .env.local)
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import uuid4

from messaging.bus import MessageBus, STREAM_ORDERS, STREAM_ORDER_RESULTS
from messaging.logging import get_logger

logger = get_logger("trading.executor")


class OrderExecutor:
    """
    Async loop that drains STREAM_ORDERS and executes each command.
    Runs in the brain's event loop as a background task.
    """

    def __init__(self, bus: MessageBus, config, persistence=None):
        self._bus         = bus
        self._cfg         = config
        self._persistence = persistence
        self._ccxt_cache: Dict[str, object] = {}   # exchange_id → ccxt instance
        self._running     = False
        self._group       = "order_executor"
        self._consumer    = "executor_1"

    async def start(self) -> None:
        self._running = True
        await self._ensure_group()
        logger.info("Order executor started — consuming STREAM_ORDERS")
        await self._run_loop()

    async def stop(self) -> None:
        self._running = False
        for ex in self._ccxt_cache.values():
            try:
                await ex.close()
            except Exception:
                pass

    async def _ensure_group(self) -> None:
        for _ in range(20):
            if self._bus._redis:
                break
            await asyncio.sleep(0.5)
        try:
            await self._bus._redis.xgroup_create(
                STREAM_ORDERS, self._group, id="$", mkstream=True
            )
        except Exception:
            pass  # group already exists

    async def _run_loop(self) -> None:
        while self._running:
            try:
                r = self._bus._redis
                if not r:
                    await asyncio.sleep(1)
                    continue

                results = await r.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer,
                    streams={STREAM_ORDERS: ">"},
                    count=10,
                    block=2000,
                )
                if not results:
                    continue

                for _stream, messages in results:
                    for msg_id, fields in messages:
                        try:
                            cmd = json.loads(fields.get("data", "{}"))
                            await self._execute(cmd)
                            await r.xack(STREAM_ORDERS, self._group, msg_id)
                        except Exception as exc:
                            logger.error(f"Executor error processing order: {exc}")
                            try:
                                await r.xack(STREAM_ORDERS, self._group, msg_id)
                            except Exception:
                                pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Executor loop error: {exc}")
                await asyncio.sleep(2)

    async def _execute(self, cmd: dict) -> None:
        order_id = cmd.get("id", str(uuid4()))
        exchange = cmd.get("exchange", "")
        pair     = cmd.get("pair", "")
        side     = cmd.get("side", "buy")
        otype    = cmd.get("order_type", "market")
        price    = cmd.get("price", 0.0)
        volume   = cmd.get("volume", 0.0)
        mode     = cmd.get("trading_mode", "simulate")
        dry_run  = cmd.get("dry_run", True)

        logger.info(
            f"[EXECUTOR] {mode.upper()} {side.upper()} {pair} on {exchange} "
            f"qty={volume} price={price} id={order_id}"
        )

        if mode == "simulate" or dry_run:
            await self._simulate_fill(cmd, order_id, exchange, pair, side, price, volume)
            return

        # LIVE execution
        try:
            result = await self._ccxt_execute(cmd, order_id, exchange, pair, side, otype, price, volume)
            await self._publish_result(result)
        except Exception as exc:
            logger.error(f"[EXECUTOR] LIVE order failed: {exc}")
            await self._publish_result({
                "order_id":    order_id,
                "exchange":    exchange,
                "pair":        pair,
                "status":      "failed",
                "error":       str(exc)[:200],
                "trading_mode": mode,
                "timestamp":   datetime.now(timezone.utc).isoformat(),
            })

    async def _simulate_fill(self, cmd: dict, order_id: str, exchange: str,
                              pair: str, side: str, price: float, volume: float) -> None:
        """Publish a synthetic fill so PositionTracker opens the position."""
        # Use current market price if available, fall back to order price
        fill_price = price

        result = {
            "order_id":          order_id,
            "exchange_order_id": f"sim-{order_id[:8]}",
            "exchange":          exchange,
            "pair":              pair,
            "side":              side,
            "status":            "filled",
            "filled_price":      fill_price,
            "filled_volume":     volume,
            "fees_paid":         round(fill_price * volume * 0.001, 6),  # 0.1% simulated fee
            "trading_mode":      "simulate",
            "simulated":         True,
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            f"[SIMULATE] Fill: {side.upper()} {volume} {pair} @ {fill_price} "
            f"fee={result['fees_paid']:.4f}"
        )
        await self._publish_result(result)

    async def _ccxt_execute(self, cmd: dict, order_id: str, exchange: str,
                             pair: str, side: str, otype: str,
                             price: float, volume: float) -> dict:
        """Execute via CCXT. Gets credentials from DB or env vars."""
        ex = await self._get_exchange(exchange)

        ccxt_type  = "limit" if otype == "limit" else "market"
        ccxt_price = price if ccxt_type == "limit" else None

        params = {}
        # Attach client order ID for tracking
        params["clientOrderId"] = order_id

        logger.warning(
            f"[LIVE ORDER] Placing {ccxt_type} {side} {volume} {pair} "
            f"on {exchange} @ {ccxt_price or 'market'}"
        )

        order = await ex.create_order(pair, ccxt_type, side, volume, ccxt_price, params)

        fill_price  = float(order.get("average") or order.get("price") or price)
        fill_volume = float(order.get("filled") or order.get("amount") or volume)
        fee_cost    = 0.0
        if order.get("fee"):
            fee_cost = float(order["fee"].get("cost", 0))

        # Place stop-loss if specified
        sl_order_id = ""
        sl = cmd.get("stop_loss", 0.0)
        if sl and sl > 0:
            try:
                sl_side = "sell" if side == "buy" else "buy"
                sl_order = await ex.create_order(
                    pair, "stop_market", sl_side, fill_volume,
                    params={"stopPrice": sl, "reduceOnly": True}
                )
                sl_order_id = sl_order.get("id", "")
                logger.info(f"[LIVE] Stop-loss placed @ {sl} | id={sl_order_id}")
            except Exception as exc:
                logger.warning(f"[LIVE] Stop-loss placement failed: {exc}")

        return {
            "order_id":          order_id,
            "exchange_order_id": str(order.get("id", "")),
            "exchange":          exchange,
            "pair":              pair,
            "side":              side,
            "status":            order.get("status", "filled"),
            "filled_price":      fill_price,
            "filled_volume":     fill_volume,
            "fees_paid":         fee_cost,
            "stop_loss_order_id": sl_order_id,
            "trading_mode":      "live",
            "raw_order":         {k: v for k, v in order.items()
                                   if k not in ("info",)},  # strip exchange raw
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        }

    async def _get_exchange(self, exchange_id: str):
        """Get or create a CCXT exchange instance with credentials."""
        if exchange_id in self._ccxt_cache:
            return self._ccxt_cache[exchange_id]

        import ccxt.async_support as ccxt_async
        cls = getattr(ccxt_async, exchange_id, None)
        if not cls:
            raise ValueError(f"Exchange '{exchange_id}' not found in CCXT")

        creds = await self._load_credentials(exchange_id)
        params = {
            "apiKey":   creds.get("api_key", ""),
            "secret":   creds.get("api_secret", ""),
            "password": creds.get("passphrase", ""),
        }
        if creds.get("sandbox"):
            params["sandbox"] = True

        ex = cls(params)
        ex.enableRateLimit = True
        self._ccxt_cache[exchange_id] = ex
        logger.info(f"[EXECUTOR] CCXT instance created for {exchange_id} "
                    f"({'sandbox' if creds.get('sandbox') else 'live'})")
        return ex

    async def _load_credentials(self, exchange: str) -> dict:
        """Load from DB first, fall back to env vars."""
        # Try DB
        if self._persistence and self._persistence.config_store:
            creds = await self._persistence.config_store.get_api_key(exchange)
            if creds:
                return creds

        # Fallback: env vars
        key    = os.getenv(f"{exchange.upper()}_API_KEY", "")
        secret = os.getenv(f"{exchange.upper()}_API_SECRET", "")
        if key:
            logger.info(f"[EXECUTOR] Using env var credentials for {exchange}")
            return {"api_key": key, "api_secret": secret, "passphrase": ""}

        logger.warning(f"[EXECUTOR] No credentials found for {exchange} — order will likely fail")
        return {}

    async def _publish_result(self, result: dict) -> None:
        await self._bus.publish(STREAM_ORDER_RESULTS, result, maxlen=10000)

"""
Order Sync Loop (v6.1)
Periodically polls exchanges for the status of open orders.
Reconciles our internal state with the exchange's truth.

Only runs for LIVE orders — simulate orders are tracked internally.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List

from messaging.bus import MessageBus, STREAM_ORDER_RESULTS
from messaging.logging import get_logger

logger = get_logger("trading.order_sync")


class OrderSyncLoop:
    """
    Background task that polls exchange APIs to reconcile order status.
    Polls every ORDER_SYNC_INTERVAL_S seconds (default 30).
    """

    def __init__(self, bus: MessageBus, order_log, config, persistence=None):
        self._bus         = bus
        self._order_log   = order_log
        self._cfg         = config
        self._persistence = persistence
        self._interval    = int(__import__("os").getenv("ORDER_SYNC_INTERVAL_S", "30"))

    async def run(self) -> None:
        logger.info(f"Order sync loop started (interval={self._interval}s)")
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self._sync_open_orders()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Order sync error: {exc}")

    async def _sync_open_orders(self) -> None:
        if not self._order_log:
            return

        open_orders = [
            o for o in self._order_log.get_open_orders()
            if o.get("trading_mode") == "live" and o.get("exchange_order_id")
        ]

        if not open_orders:
            return

        # Group by exchange to minimise API calls
        by_exchange: Dict[str, List[dict]] = {}
        for o in open_orders:
            by_exchange.setdefault(o["exchange"], []).append(o)

        for exchange, orders in by_exchange.items():
            await self._sync_exchange(exchange, orders)

    async def _sync_exchange(self, exchange: str, orders: List[dict]) -> None:
        try:
            ex = await self._get_exchange(exchange)
            for order in orders:
                try:
                    ext = await ex.fetch_order(order["exchange_order_id"], order["pair"])
                    status = ext.get("status", "")
                    if status != order.get("status"):
                        result = {
                            "order_id":    order["id"],
                            "exchange":    exchange,
                            "status":      status,
                            "filled_price": float(ext.get("average") or ext.get("price") or 0),
                            "filled_volume": float(ext.get("filled") or 0),
                            "source":      "exchange_sync",
                            "timestamp":   datetime.now(timezone.utc).isoformat(),
                        }
                        await self._bus.publish(STREAM_ORDER_RESULTS, result, maxlen=10000)
                        logger.info(f"[SYNC] Order {order['id']} status: {order.get('status')} → {status}")
                except Exception as exc:
                    logger.debug(f"[SYNC] Could not fetch order {order.get('id')}: {exc}")
        except Exception as exc:
            logger.warning(f"[SYNC] Exchange {exchange} sync failed: {exc}")

    async def _get_exchange(self, exchange_id: str):
        """Borrow executor's cache if available, else create new instance."""
        import ccxt.async_support as ccxt_async
        import os
        cls = getattr(ccxt_async, exchange_id, None)
        if not cls:
            raise ValueError(f"Unknown exchange: {exchange_id}")

        creds: dict = {}
        if self._persistence and self._persistence.config_store:
            c = await self._persistence.config_store.get_api_key(exchange_id)
            if c:
                creds = c

        if not creds:
            key    = os.getenv(f"{exchange_id.upper()}_API_KEY", "")
            secret = os.getenv(f"{exchange_id.upper()}_API_SECRET", "")
            creds  = {"api_key": key, "api_secret": secret}

        ex = cls({"apiKey": creds.get("api_key",""), "secret": creds.get("api_secret","")})
        ex.enableRateLimit = True
        return ex

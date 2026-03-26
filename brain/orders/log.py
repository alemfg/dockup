"""
Order Log (v3.3)
In-memory store for full order lifecycle with PostgreSQL persistence.
Tracks every order from creation through execution to close.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, date
from typing import Dict, List, Optional

from messaging.logging import get_logger

logger = get_logger("brain.orders.log")


class OrderLog:
    """
    Full-lifecycle order store.
    In v3.3 this is in-memory with optional Postgres sync.
    Each entry tracks the complete journey of one OrderCommand.
    """

    def __init__(self):
        self._orders: Dict[str, dict] = {}          # order_id → full record
        self._by_exchange: Dict[str, List[str]] = defaultdict(list)
        self._by_pair:     Dict[str, List[str]] = defaultdict(list)

    # ─── Write ───────────────────────────────────────────────────────────────

    def record_command(self, cmd_dict: dict) -> None:
        """Record a new OrderCommand."""
        oid = cmd_dict.get("id")
        if not oid:
            return
        record = dict(cmd_dict)
        record["lifecycle"] = [
            {"event": "created", "ts": datetime.now(timezone.utc).isoformat()}
        ]
        self._orders[oid] = record
        self._by_exchange[cmd_dict.get("exchange", "")].append(oid)
        self._by_pair[cmd_dict.get("pair", "")].append(oid)

    def record_result(self, result_dict: dict) -> None:
        """Update an order with its execution result."""
        oid = result_dict.get("order_id")
        if not oid or oid not in self._orders:
            return
        order = self._orders[oid]
        order["result"]              = result_dict
        order["status"]              = result_dict.get("status", "unknown")
        order["filled_price"]        = result_dict.get("filled_price", 0.0)
        order["filled_volume"]       = result_dict.get("filled_volume", 0.0)
        order["fees_paid"]           = result_dict.get("fees_paid", 0.0)
        order["exchange_order_id"]   = result_dict.get("exchange_order_id", "")
        order["stop_loss_order_id"]  = result_dict.get("stop_loss_order_id", "")
        order["lifecycle"].append({
            "event": result_dict.get("status", "result"),
            "ts":    datetime.now(timezone.utc).isoformat(),
        })

    def record_close(self, order_id: str, close_reason: str, pnl_usd: float, close_price: float) -> None:
        """Record that a position closed (SL/TP/manual)."""
        if order_id not in self._orders:
            return
        order = self._orders[order_id]
        order["close_reason"]  = close_reason
        order["pnl_usd"]       = round(pnl_usd, 2)
        order["close_price"]   = close_price
        order["closed_at"]     = datetime.now(timezone.utc).isoformat()
        order["status"]        = "closed"
        order["lifecycle"].append({
            "event":  f"closed_{close_reason}",
            "pnl":    round(pnl_usd, 2),
            "ts":     datetime.now(timezone.utc).isoformat(),
        })

    def sync_exchange_order(self, order_id: str, exchange_status: dict) -> None:
        """
        Called by the exchange sync loop to reconcile external status.
        Updates status if the exchange reports something different from our record.
        """
        if order_id not in self._orders:
            return
        order  = self._orders[order_id]
        ext_st = exchange_status.get("status", "")
        if ext_st and ext_st != order.get("status"):
            logger.info(f"[ORDER SYNC] {order_id}: internal={order.get('status')} → exchange={ext_st}")
            order["status"] = ext_st
            order["lifecycle"].append({
                "event": f"synced_{ext_st}",
                "ts":    datetime.now(timezone.utc).isoformat(),
            })

    # ─── Read ────────────────────────────────────────────────────────────────

    def get(self, order_id: str) -> Optional[dict]:
        return self._orders.get(order_id)

    def get_all(
        self,
        limit:    int            = 100,
        exchange: Optional[str]  = None,
        pair:     Optional[str]  = None,
        status:   Optional[str]  = None,
        source:   Optional[str]  = None,
    ) -> List[dict]:
        orders = list(self._orders.values())

        if exchange:
            orders = [o for o in orders if o.get("exchange") == exchange]
        if pair:
            orders = [o for o in orders if o.get("pair") == pair]
        if status:
            orders = [o for o in orders if o.get("status") == status]
        if source:
            orders = [o for o in orders if o.get("source") == source]

        orders.sort(key=lambda o: o.get("created_at", ""), reverse=True)
        return orders[:limit]

    def get_open_orders(self) -> List[dict]:
        return [o for o in self._orders.values() if o.get("status") in ("pending", "sent", "partial")]

    def financial_summary(self) -> dict:
        closed = [o for o in self._orders.values() if o.get("status") == "closed"]
        if not closed:
            return {
                "total_orders": len(self._orders),
                "closed": 0, "open": len(self.get_open_orders()),
                "total_pnl_usd": 0.0, "win_rate": 0.0,
                "wins": 0, "losses": 0,
                "avg_pnl_usd": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
                "total_fees_usd": 0.0,
            }

        pnls  = [o.get("pnl_usd", 0.0) for o in closed]
        fees  = sum(o.get("fees_paid", 0.0) for o in closed)
        wins  = sum(1 for p in pnls if p > 0)
        total = sum(pnls)

        return {
            "total_orders":  len(self._orders),
            "closed":        len(closed),
            "open":          len(self.get_open_orders()),
            "simulated":     sum(1 for o in self._orders.values() if o.get("trading_mode") == "simulate"),
            "live":          sum(1 for o in self._orders.values() if o.get("trading_mode") == "live"),
            "total_pnl_usd": round(total, 2),
            "win_rate":      round(wins / max(len(closed), 1) * 100, 1),
            "wins":          wins,
            "losses":        len(closed) - wins,
            "avg_pnl_usd":   round(total / max(len(closed), 1), 2),
            "best_trade":    round(max(pnls), 2) if pnls else 0.0,
            "worst_trade":   round(min(pnls), 2) if pnls else 0.0,
            "total_fees_usd": round(fees, 4),
        }

    def daily_pnl(self, days: int = 30) -> List[dict]:
        daily: Dict[str, float] = defaultdict(float)
        for o in self._orders.values():
            if o.get("status") == "closed" and o.get("closed_at"):
                try:
                    day = o["closed_at"][:10]
                    daily[day] += o.get("pnl_usd", 0.0)
                except Exception:
                    pass
        return [{"date": d, "pnl_usd": round(v, 2)} for d, v in sorted(daily.items())]

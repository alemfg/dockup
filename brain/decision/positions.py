"""
Position Tracker (v3.3)
Maintains all open positions, updates P&L on every price tick,
detects SL/TP hits, and emits close orders.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from messaging.bus import MessageBus
from messaging.logging import get_logger
from messaging.models import OrderCommand, OrderSide, OrderType, SignalSource, Position
from storage.market_state import MarketState

logger = get_logger("brain.decision.positions")


class PositionTracker:

    def __init__(self, bus: MessageBus, market_state: MarketState, config=None):
        self._bus     = bus
        self._market  = market_state
        self._config  = config   # for LIVE auto-close
        self._positions: Dict[str, Position] = {}   # id → Position
        self._closed:    List[Position]       = []   # history

    # ─── Public ──────────────────────────────────────────────────────────────

    def open_position(self, cmd: OrderCommand, fill_price: float) -> Position:
        pos = Position(
            order_id      = cmd.id,
            exchange      = cmd.exchange,
            pair          = cmd.pair,
            side          = cmd.side.value,
            entry_price   = fill_price,
            current_price = fill_price,
            volume        = cmd.volume,
            capital_usd   = cmd.capital_usd,
            stop_loss     = cmd.stop_loss,
            take_profit_1 = cmd.take_profit_1,
            take_profit_2 = cmd.take_profit_2,
            source        = cmd.source.value,
        )
        self._positions[pos.id] = pos
        logger.info(f"[POSITION] Opened {pos.side.upper()} {pos.pair} @ {fill_price} | ID={pos.id}")
        return pos

    def on_price_tick(self, exchange: str, pair: str, price: float) -> List[dict]:
        """
        Called on every price update. Returns list of close actions triggered.
        """
        actions = []
        for pos in list(self._positions.values()):
            if pos.exchange != exchange or pos.pair != pair:
                continue

            pos.update_price(price)

            if pos.sl_hit(price):
                action = self._close_position(pos, price, "sl_hit")
                actions.append(action)

            elif pos.tp2_hit(price):
                action = self._close_position(pos, price, "tp2_hit")
                actions.append(action)

            elif pos.tp1_hit(price) and pos.status == "open":
                # Mark TP1 hit — partial close handled by worker's OCO/SL order
                pos.status = "tp1_hit"
                logger.info(f"[POSITION] TP1 hit for {pos.pair} @ {price} | PnL={pos.pnl_pct:.2f}%")
                actions.append({"event": "tp1_hit", "position": pos.to_dict()})

        return actions

    def close_position(self, position_id: str, price: float, reason: str = "manual") -> Optional[dict]:
        pos = self._positions.get(position_id)
        if not pos:
            return None
        return self._close_position(pos, price, reason)

    def get_open_positions(self) -> List[dict]:
        return [p.to_dict() for p in self._positions.values()]

    def get_closed_positions(self, limit: int = 100) -> List[dict]:
        return [p.to_dict() for p in reversed(self._closed[-limit:])]

    def get_open_usd(self, exchange: str, pair: str) -> float:
        return sum(
            p.capital_usd for p in self._positions.values()
            if p.exchange == exchange and p.pair == pair
        )

    def get_pnl_summary(self) -> dict:
        closed = self._closed
        if not closed:
            return {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl_usd": 0.0,
                    "win_rate": 0.0, "avg_pnl_usd": 0.0, "best_trade": 0.0, "worst_trade": 0.0}
        pnls     = [p.pnl_usd for p in closed]
        wins     = sum(1 for p in pnls if p > 0)
        total    = sum(pnls)
        return {
            "total_trades":  len(closed),
            "wins":          wins,
            "losses":        len(closed) - wins,
            "total_pnl_usd": round(total, 2),
            "win_rate":      round(wins / len(closed) * 100, 1),
            "avg_pnl_usd":   round(total / len(closed), 2),
            "best_trade":    round(max(pnls), 2),
            "worst_trade":   round(min(pnls), 2),
        }

    def get_daily_pnl(self, days: int = 30) -> List[dict]:
        """Returns daily P&L grouped by date for charting."""
        from collections import defaultdict
        daily: Dict[str, float] = defaultdict(float)
        for p in self._closed:
            if p.closed_at:
                day = p.closed_at.strftime("%Y-%m-%d")
                daily[day] += p.pnl_usd
        # Fill zeros for missing days would require date range — return what we have
        return [{"date": d, "pnl_usd": round(v, 2)} for d, v in sorted(daily.items())]

    # ─── Internal ────────────────────────────────────────────────────────────

    def _close_position(self, pos: Position, price: float, reason: str) -> dict:
        pos.update_price(price)
        pos.status       = "closed"
        pos.closed_at    = datetime.now(timezone.utc)
        pos.close_reason = reason

        del self._positions[pos.id]
        self._closed.append(pos)
        if len(self._closed) > 10000:
            self._closed = self._closed[-8000:]

        logger.info(
            f"[POSITION] Closed {pos.pair} @ {price} | "
            f"reason={reason} | PnL={pos.pnl_usd:+.2f} USD ({pos.pnl_pct:+.2f}%)"
        )

        # For LIVE positions: fire a closing market order via the execution bus
        if hasattr(self, "_config") and self._config and            self._config.trading.mode.value == "live" and            getattr(pos, "order_id", None):
            asyncio.create_task(
                self._send_close_order(pos, price, reason),
                name=f"close_{pos.id[:8]}"
            )

        return {"event": reason, "position": pos.to_dict()}

    async def _send_close_order(self, pos: Position, price: float, reason: str) -> None:
        """Send a market close order to the execution stream for LIVE positions."""
        from uuid import uuid4
        close_cmd = {
            "id":           str(uuid4()),
            "exchange":     pos.exchange,
            "pair":         pos.pair,
            "side":         "sell" if pos.side == "buy" else "buy",
            "order_type":   "market",
            "price":        price,
            "volume":       pos.volume,
            "capital_usd":  pos.capital_usd,
            "source":       "position_tracker",
            "trading_mode": "live",
            "dry_run":      False,
            "notes":        f"Auto-close: {reason}",
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "expires_at":   (datetime.now(timezone.utc) +
                             __import__("datetime").timedelta(seconds=60)).isoformat(),
        }
        try:
            from messaging.bus import STREAM_ORDERS
            await self._bus.publish(STREAM_ORDERS, close_cmd, maxlen=10000)
            logger.info(f"[POSITION] Close order sent for {pos.pair} {pos.side} {pos.volume} @ market")
        except Exception as exc:
            logger.error(f"[POSITION] Failed to send close order: {exc}")

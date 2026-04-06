"""
PostgreSQL Persistence (v4)
Write-through cache: in-memory store (OrderLog, PositionTracker) remains
the primary read path for speed. This module persists to PostgreSQL
asynchronously so data survives restarts.

Tables created automatically on first run (CREATE TABLE IF NOT EXISTS).
Uses asyncpg directly (no ORM overhead).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional

from messaging.logging import get_logger

logger = get_logger("storage.db")


CREATE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS arbx_orders (
    id               TEXT PRIMARY KEY,
    exchange         TEXT,
    pair             TEXT,
    side             TEXT,
    order_type       TEXT,
    price            DOUBLE PRECISION,
    volume           DOUBLE PRECISION,
    capital_usd      DOUBLE PRECISION,
    stop_loss        DOUBLE PRECISION,
    take_profit_1    DOUBLE PRECISION,
    take_profit_2    DOUBLE PRECISION,
    source           TEXT,
    signal_score     DOUBLE PRECISION,
    confidence       TEXT,
    trading_mode     TEXT,
    status           TEXT,
    filled_price     DOUBLE PRECISION,
    fees_paid        DOUBLE PRECISION,
    pnl_usd          DOUBLE PRECISION,
    close_reason     TEXT,
    created_at       TIMESTAMPTZ,
    closed_at        TIMESTAMPTZ,
    raw_data         JSONB
);
"""

CREATE_POSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS arbx_positions (
    id               TEXT PRIMARY KEY,
    order_id         TEXT,
    exchange         TEXT,
    pair             TEXT,
    side             TEXT,
    entry_price      DOUBLE PRECISION,
    volume           DOUBLE PRECISION,
    capital_usd      DOUBLE PRECISION,
    stop_loss        DOUBLE PRECISION,
    take_profit_1    DOUBLE PRECISION,
    take_profit_2    DOUBLE PRECISION,
    source           TEXT,
    status           TEXT,
    pnl_usd          DOUBLE PRECISION,
    pnl_pct          DOUBLE PRECISION,
    close_reason     TEXT,
    opened_at        TIMESTAMPTZ,
    closed_at        TIMESTAMPTZ
);
"""

CREATE_PNL_TABLE = """
CREATE TABLE IF NOT EXISTS arbx_daily_pnl (
    date         DATE PRIMARY KEY,
    realized_usd DOUBLE PRECISION DEFAULT 0.0,
    trades       INTEGER DEFAULT 0,
    wins         INTEGER DEFAULT 0,
    fees_usd     DOUBLE PRECISION DEFAULT 0.0,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
"""

CREATE_PRICE_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS arbx_price_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    exchange         TEXT,
    pair             TEXT,
    price            DOUBLE PRECISION,
    recorded_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_snapshots_pair ON arbx_price_snapshots (exchange, pair, recorded_at DESC);
"""


class PersistenceLayer:
    """
    Async PostgreSQL persistence.
    All writes are fire-and-forget via a queue to avoid blocking the main loop.
    """

    def __init__(self, dsn: str):
        self._dsn   = dsn
        self._pool  = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._ready = False
        self.config_store = None  # set in start()

    async def start(self) -> None:
        try:
            import asyncpg
            self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=8)
            await self._create_tables()
            # Initialise config store with same pool
            from storage.db.config_store import ConfigStore
            self.config_store = ConfigStore(self._pool)
            await self.config_store.init()
            self._ready = True
            asyncio.create_task(self._write_loop(), name="db_writer")
            logger.info("PostgreSQL persistence layer started")
        except Exception as exc:
            logger.warning(f"PostgreSQL unavailable — running without persistence: {exc}")
            self._ready = False
            # Provide a null config store so code doesn't have to check
            from storage.db.config_store import ConfigStore
            self.config_store = ConfigStore(None)

    async def _create_tables(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_ORDERS_TABLE)
            await conn.execute(CREATE_POSITIONS_TABLE)
            await conn.execute(CREATE_PRICE_SNAPSHOTS_TABLE)
            await conn.execute(CREATE_PNL_TABLE)
        logger.info("Database tables verified")

    async def _write_loop(self) -> None:
        while True:
            try:
                op, data = await asyncio.wait_for(self._queue.get(), timeout=10.0)
                await self._execute(op, data)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"DB write error: {exc}")

    async def _execute(self, op: str, data: dict) -> None:
        if not self._pool:
            return
        try:
            async with self._pool.acquire() as conn:
                if op == "upsert_order":
                    await conn.execute("""
                        INSERT INTO arbx_orders
                            (id, exchange, pair, side, order_type, price, volume, capital_usd,
                             stop_loss, take_profit_1, take_profit_2, source, signal_score,
                             confidence, trading_mode, status, filled_price, fees_paid,
                             pnl_usd, close_reason, created_at, closed_at, raw_data)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)
                        ON CONFLICT (id) DO UPDATE SET
                            status=EXCLUDED.status, filled_price=EXCLUDED.filled_price,
                            fees_paid=EXCLUDED.fees_paid, pnl_usd=EXCLUDED.pnl_usd,
                            close_reason=EXCLUDED.close_reason, closed_at=EXCLUDED.closed_at,
                            raw_data=EXCLUDED.raw_data
                    """,
                    data["id"], data.get("exchange"), data.get("pair"), data.get("side"),
                    data.get("order_type"), data.get("price"), data.get("volume"),
                    data.get("capital_usd"), data.get("stop_loss"), data.get("take_profit_1"),
                    data.get("take_profit_2"), data.get("source"), data.get("signal_score"),
                    data.get("confidence"), data.get("trading_mode"), data.get("status"),
                    data.get("filled_price"), data.get("fees_paid"), data.get("pnl_usd"),
                    data.get("close_reason"),
                    _parse_dt(data.get("created_at")), _parse_dt(data.get("closed_at")),
                    json.dumps(data))

                elif op == "upsert_daily_pnl":
                    await conn.execute("""
                        INSERT INTO arbx_daily_pnl(date,realized_usd,trades,wins,fees_usd,updated_at)
                        VALUES($1,$2,$3,$4,$5,NOW())
                        ON CONFLICT(date) DO UPDATE SET
                            realized_usd=EXCLUDED.realized_usd,
                            trades=EXCLUDED.trades, wins=EXCLUDED.wins,
                            fees_usd=EXCLUDED.fees_usd, updated_at=NOW()
                    """, data["date"], data["realized_usd"], data["trades"],
                         data["wins"], data["fees_usd"])

                elif op == "upsert_position":
                    await conn.execute("""
                        INSERT INTO arbx_positions
                            (id, order_id, exchange, pair, side, entry_price, volume,
                             capital_usd, stop_loss, take_profit_1, take_profit_2,
                             source, status, pnl_usd, pnl_pct, close_reason, opened_at, closed_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
                        ON CONFLICT (id) DO UPDATE SET
                            status=EXCLUDED.status, pnl_usd=EXCLUDED.pnl_usd,
                            pnl_pct=EXCLUDED.pnl_pct, close_reason=EXCLUDED.close_reason,
                            closed_at=EXCLUDED.closed_at
                    """,
                    data["id"], data.get("order_id"), data.get("exchange"), data.get("pair"),
                    data.get("side"), data.get("entry_price"), data.get("volume"),
                    data.get("capital_usd"), data.get("stop_loss"), data.get("take_profit_1"),
                    data.get("take_profit_2"), data.get("source"), data.get("status"),
                    data.get("pnl_usd"), data.get("pnl_pct"), data.get("close_reason"),
                    _parse_dt(data.get("opened_at")), _parse_dt(data.get("closed_at")))

        except Exception as exc:
            logger.error(f"DB execute error [{op}]: {exc}")

    def _enqueue(self, op: str, data: dict) -> None:
        if not self._ready:
            return
        try:
            self._queue.put_nowait((op, data))
        except asyncio.QueueFull:
            logger.warning("DB write queue full — skipping persistence write")

    # ─── Public write API ────────────────────────────────────────────────────

    def persist_order(self, order_dict: dict) -> None:
        self._enqueue("upsert_order", order_dict)

    def persist_position(self, position_dict: dict) -> None:
        self._enqueue("upsert_position", position_dict)

    def persist_daily_pnl(self, date_str: str, realized: float,
                           trades: int, wins: int, fees: float) -> None:
        self._enqueue("upsert_daily_pnl", {
            "date": date_str, "realized_usd": realized,
            "trades": trades, "wins": wins, "fees_usd": fees,
        })

    async def load_recent_orders(self, limit: int = 500) -> List[dict]:
        """Load recent orders from DB on startup to restore order log."""
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT raw_data FROM arbx_orders ORDER BY created_at DESC LIMIT $1", limit
                )
                return [json.loads(r["raw_data"]) for r in rows]
        except Exception as exc:
            logger.error(f"DB load error: {exc}")
            return []


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        dt = datetime.fromisoformat(val)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

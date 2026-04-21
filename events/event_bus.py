"""
Financial & System Event Bus (v4.5)
====================================
Typed events written to an in-memory ring buffer, served via REST.

Categories
----------
  ARBIT   — graph arbitrage cycle detected / executed
  CR9AM   — 9AM CR session started / signal / missed / stopped
  SYSTEM  — brain startup, worker connect/disconnect, config reload
  RISK    — circuit breaker / daily loss limit / drawdown
  TRADE   — simulated or live order placed / filled / rejected

Usage
-----
    from events.event_bus import emit, Category, Level

    await emit(Category.ARBIT, "Cycle detected",
               detail="BTC→USDT→ETH→BTC | +0.35% net | $35.20",
               level=Level.SUCCESS,
               data={"path": "...", "net_pct": 0.35})

    # Sync wrapper (from non-async code):
    emit_sync(Category.SYSTEM, "Brain started")
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

MAX_EVENTS = 1000


# ── Enums ────────────────────────────────────────────────────────────────────

class Category(str, Enum):
    ARBIT  = "ARBIT"
    CR9AM  = "CR9AM"
    SYSTEM = "SYSTEM"
    RISK   = "RISK"
    TRADE  = "TRADE"


class Level(str, Enum):
    INFO    = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR   = "ERROR"


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class FinancialEvent:
    id:       int
    ts:       float
    category: str
    level:    str
    title:    str
    detail:   str
    data:     Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id":       self.id,
            "ts":       self.ts,
            "category": self.category,
            "level":    self.level,
            "title":    self.title,
            "detail":   self.detail,
            "data":     self.data,
        }


# ── Singleton ring buffer ─────────────────────────────────────────────────────

_buffer:  Deque[FinancialEvent] = deque(maxlen=MAX_EVENTS)
_counter: int = 0
_lock:    asyncio.Lock = asyncio.Lock()


async def emit(
    category: Category,
    title:    str,
    detail:   str = "",
    level:    Level = Level.INFO,
    data:     Optional[Dict[str, Any]] = None,
) -> None:
    """Append an event to the ring buffer (async)."""
    global _counter
    async with _lock:
        _counter += 1
        _buffer.appendleft(FinancialEvent(
            id       = _counter,
            ts       = time.time(),
            category = category.value,
            level    = level.value,
            title    = title,
            detail   = detail,
            data     = data or {},
        ))


def emit_sync(
    category: Category,
    title:    str,
    detail:   str = "",
    level:    Level = Level.INFO,
    data:     Optional[Dict[str, Any]] = None,
) -> None:
    """Fire-and-forget from synchronous or partially-async code."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(emit(category, title, detail, level, data))
    except RuntimeError:
        pass  # no running loop — skip silently


def get_events(
    limit:    int = 200,
    category: Optional[str] = None,
    level:    Optional[str] = None,
) -> List[dict]:
    """Return recent events, newest first."""
    events: List[FinancialEvent] = list(_buffer)
    if category and category != "ALL":
        events = [e for e in events if e.category == category]
    if level and level != "ALL":
        events = [e for e in events if e.level == level]
    return [e.to_dict() for e in events[:limit]]


def get_stats() -> dict:
    """Count per category for the badge display."""
    counts: Dict[str, int] = {c.value: 0 for c in Category}
    for e in _buffer:
        counts[e.category] = counts.get(e.category, 0) + 1
    return counts

"""
Log Viewer API (v3.3)
In-memory ring buffer capturing log records from all brain loggers.
Served via REST (last N lines) and WebSocket (live tail).
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["Logs"])

# ─── Ring Buffer Handler ─────────────────────────────────────────────────────

_MAX_LINES = 2000

class _RingBufferHandler(logging.Handler):
    def __init__(self, maxlen: int = _MAX_LINES):
        super().__init__()
        self._buffer: Deque[dict] = deque(maxlen=maxlen)
        self._clients: list = []

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts":      datetime.now(timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "message": self.format(record),
        }
        self._buffer.append(entry)
        # Broadcast to all live WebSocket clients
        dead = []
        for q in self._clients:
            try:
                q.put_nowait(entry)
            except Exception:
                dead.append(q)
        for q in dead:
            self._clients.remove(q)

    def get_recent(self, limit: int = 200, level: str = "") -> list:
        lines = list(self._buffer)
        if level:
            lines = [l for l in lines if l["level"] == level.upper()]
        return lines[-limit:]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._clients.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._clients:
            self._clients.remove(q)


# Install handler once at module load
_handler = _RingBufferHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
                                         datefmt="%H:%M:%S"))
logging.getLogger().addHandler(_handler)


# ─── REST endpoint ───────────────────────────────────────────────────────────

@router.get("/logs")
async def get_logs(limit: int = 200, level: str = ""):
    """Return last N log lines, optionally filtered by level."""
    return {"logs": _handler.get_recent(limit=limit, level=level)}


# ─── WebSocket live tail ─────────────────────────────────────────────────────

@router.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    """
    Live log tail via WebSocket.
    Registered WITHOUT /api prefix so it matches the /ws/ nginx block
    which has WebSocket Upgrade headers.
    Frontend connects to: /ws/logs  (same as /ws/fleet, /ws/market)
    """
    q = _handler.subscribe()
    # Send recent history first
    for entry in _handler.get_recent(limit=100):
        await ws.send_json(entry)
    try:
        while True:
            try:
                entry = await asyncio.wait_for(q.get(), timeout=30)
                await ws.send_json(entry)
            except asyncio.TimeoutError:
                await ws.send_json({"ping": True})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _handler.unsubscribe(q)

"""WebSocket routes — live streaming of prices, signals, fleet events."""
from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from messaging.logging import get_logger

router = APIRouter(tags=["WebSocket"])
logger = get_logger("api.websocket")


@router.websocket("/ws/market")
async def ws_market(websocket: WebSocket):
    """Streams live price updates and market spreads."""
    await websocket.accept()
    brain = websocket.app.state.brain
    logger.info("WebSocket /ws/market connected")
    try:
        while True:
            await asyncio.sleep(2)
            ms = brain.market_state
            await websocket.send_text(json.dumps({
                "type":    "market_update",
                "prices":  ms.get_all_prices(),
                "summary": ms.summary(),
            }))
    except WebSocketDisconnect:
        logger.info("WebSocket /ws/market disconnected")


@router.websocket("/ws/fleet")
async def ws_fleet(websocket: WebSocket):
    """Streams live fleet health updates."""
    await websocket.accept()
    brain = websocket.app.state.brain
    logger.info("WebSocket /ws/fleet connected")
    try:
        while True:
            await asyncio.sleep(3)
            fleet = brain.fleet_monitor
            await websocket.send_text(json.dumps({
                "type":    "fleet_update",
                "workers": fleet.get_all_workers(),
                "events":  fleet.get_event_log(limit=10),
            }))
    except WebSocketDisconnect:
        logger.info("WebSocket /ws/fleet disconnected")


@router.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    """Streams live analysis signals and CR setups."""
    await websocket.accept()
    brain = websocket.app.state.brain
    logger.info("WebSocket /ws/signals connected")
    try:
        while True:
            await asyncio.sleep(5)
            engine  = brain.context_engine
            signals = [s.to_dict() for s in engine.get_all_signals()]

            from analysis.plugins.registry import get_plugin
            cr_plugin = get_plugin("cr_9am")
            cr_signals = cr_plugin.get_active_signals() if cr_plugin else []

            await websocket.send_text(json.dumps({
                "type":       "signal_update",
                "signals":    signals,
                "cr_signals": cr_signals,
            }))
    except WebSocketDisconnect:
        logger.info("WebSocket /ws/signals disconnected")


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    """
    Live log tail — registered here (no prefix) so nginx /ws/ block
    correctly passes WebSocket Upgrade headers.
    The log_viewer router registers /ws/logs under /api prefix which
    breaks WebSocket upgrade — this version at /ws/logs is correct.
    """
    from api.routes.log_viewer import _handler
    await websocket.accept()
    logger.info("WebSocket /ws/logs connected")
    q = _handler.subscribe()
    # Send recent history first so client sees context immediately
    for entry in _handler.get_recent(limit=200):
        await websocket.send_json(entry)
    try:
        while True:
            try:
                entry = await asyncio.wait_for(q.get(), timeout=30)
                await websocket.send_json(entry)
            except asyncio.TimeoutError:
                await websocket.send_json({"ping": True})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _handler.unsubscribe(q)
        logger.info("WebSocket /ws/logs disconnected")

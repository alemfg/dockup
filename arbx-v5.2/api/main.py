"""FastAPI v2 application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from messaging.logging import get_logger
from config.loader import _read_version
# Install the ring-buffer log handler BEFORE anything calls setup_logging()
# so that handler is preserved (setup_logging now keeps non-StreamHandlers).
import api.routes.log_viewer as _log_viewer_module  # noqa: F401  side-effect import

if TYPE_CHECKING:
    from brain.brain import Brain

logger = get_logger("api")


def create_app(brain: "Brain") -> FastAPI:
    cfg = brain.config.brain

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("API server started.")
        yield
        logger.info("API server stopped.")

    app = FastAPI(
        title="ArbitrageEngine v2 API",
        version=_read_version(),
        description="Distributed crypto arbitrage platform with 9AM CR model.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Attach brain reference so routes can access it
    app.state.brain = brain

    # Register all route modules
    from api.routes import (
        system, fleet, workers, analysis, market,
        balances, security, cr_signals, websocket, graph, inject, trading,
        orders, positions, risk, financials, log_viewer, config_reload, events,
    )
    app.include_router(system.router,      prefix="/api")
    app.include_router(fleet.router,       prefix="/api")
    app.include_router(workers.router,     prefix="/api")
    app.include_router(analysis.router,    prefix="/api")
    app.include_router(market.router,      prefix="/api")
    app.include_router(balances.router,    prefix="/api")
    app.include_router(security.router,    prefix="/api")
    app.include_router(cr_signals.router,  prefix="/api")
    app.include_router(graph.router,       prefix="/api")
    app.include_router(inject.router,      prefix="/api")
    app.include_router(trading.router,     prefix="/api")
    app.include_router(orders.router,      prefix="/api")
    app.include_router(positions.router,   prefix="/api")
    app.include_router(risk.router,        prefix="/api")
    app.include_router(financials.router,  prefix="/api")
    app.include_router(log_viewer.router,    prefix="/api")
    app.include_router(config_reload.router, prefix="/api")
    app.include_router(events.router,        prefix="/api")
    app.include_router(websocket.router)

    return app

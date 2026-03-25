"""
Brain — central analysis and orchestration node.
Subscribes to worker streams, runs analysis, produces trade signals,
monitors fleet health, and serves the API.
"""
from __future__ import annotations

import asyncio
import signal
from typing import Optional

from analysis.context_engine import ContextEngine
from arbitrage.graph.currency_graph import CurrencyGraph
from arbitrage.graph.graph_arbitrage import GraphArbitrage
from brain.fleet.monitor import FleetMonitor
from brain.security.auth_manager import AuthManager
from brain.stream.subscriber import StreamSubscriber
from config.loader import load_config, AppConfig
from messaging.bus import MessageBus
from messaging.logging import get_logger, setup_logging
from storage.market_state import MarketState

logger = get_logger("brain.main")


class Brain:
    """
    Central brain — pure computation and orchestration.
    Never connects to exchanges directly.
    All market data arrives via the message bus from workers.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config: AppConfig = load_config(config_path)
        setup_logging(self.config.brain.log_level)

        # Core infrastructure
        self.bus            = MessageBus(
            host=self.config.redis.host,
            port=self.config.redis.port,
        )
        self.market_state   = MarketState()
        self.auth_manager   = AuthManager(
            nonce_ttl=self.config.security.nonce_ttl_seconds,
        )
        self.fleet_monitor  = FleetMonitor(
            bus=self.bus,
            heartbeat_ttl=self.config.security.heartbeat_ttl,
        )
        self.context_engine = ContextEngine(
            analysis_config=self.config.analysis.model_dump(),
        )

        # Graph arbitrage — live currency graph fed by every price tick
        self.currency_graph   = CurrencyGraph(stale_threshold_seconds=30)
        self.graph_arbitrage  = GraphArbitrage(
            config=self.config,
            graph=self.currency_graph,
        )
        # Cache of latest graph paths for the API / dashboard
        self._graph_paths: list = []

        self.stream_sub     = StreamSubscriber(
            bus=self.bus,
            market_state=self.market_state,
            context_engine=self.context_engine,
            auth_manager=self.auth_manager,
            config=self.config,
            currency_graph=self.currency_graph,
        )

        self._shutdown_event = asyncio.Event()

    def _setup_signals(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: self._shutdown_event.set())

    def _print_banner(self) -> None:
        cfg = self.config.brain
        logger.info("=" * 60)
        logger.info(f"  ARBX Brain v{cfg.version}")
        logger.info(f"  Dry-run        : {'ON' if cfg.dry_run else 'OFF ⚠️'}")
        logger.info(f"  API            : {cfg.api_host}:{cfg.api_port}")
        logger.info(f"  Security       : {'mTLS + HMAC' if self.config.security.require_mtls else 'HMAC only'}")
        logger.info(f"  CR 9AM         : {'enabled' if self.config.analysis.cr_9am.enabled else 'disabled'}")
        logger.info(f"  Graph Arbitrage: enabled (Bellman-Ford + Floyd-Warshall)")
        logger.info("=" * 60)

    async def _graph_scan_loop(self) -> None:
        """Run graph arbitrage scan every 5 seconds."""
        while True:
            await asyncio.sleep(5)
            try:
                paths = await self.graph_arbitrage.scan()
                if paths:
                    self._graph_paths = [p.to_dict() for p in paths]
                    for p in paths[:3]:    # log top 3
                        logger.info(
                            f"[GRAPH] {p.path_string} | "
                            f"{p.hops} hops | "
                            f"net {p.net_profit_pct():.3f}%"
                        )
            except Exception as exc:
                logger.error(f"Graph scan error: {exc}")

    async def start(self) -> None:
        self._setup_signals()
        self._print_banner()

        # Connect to message bus
        await self.bus.connect()
        logger.info("Brain connected to message bus.")

        # Start all async tasks
        tasks = [
            asyncio.create_task(self.stream_sub.run(),        name="stream_subscriber"),
            asyncio.create_task(self.fleet_monitor.start(),   name="fleet_monitor"),
            asyncio.create_task(self._graph_scan_loop(),      name="graph_arbitrage"),
            asyncio.create_task(self._start_api(),            name="api_server"),
        ]

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        logger.info("Brain shutting down...")
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self.bus.disconnect()
        logger.info("Brain stopped cleanly.")

    async def _start_api(self) -> None:
        import uvicorn
        from api.main import create_app
        app = create_app(self)
        cfg = self.config.brain
        server = uvicorn.Server(uvicorn.Config(
            app=app, host=cfg.api_host, port=cfg.api_port,
            log_level="warning",
        ))
        await server.serve()


def run(config_path: Optional[str] = None) -> None:
    brain = Brain(config_path)
    asyncio.run(brain.start())

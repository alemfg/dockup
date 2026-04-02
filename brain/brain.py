"""
Brain — central analysis and orchestration node.
v3.3: Decision engine, risk manager, position tracker, order log added.
"""
from __future__ import annotations

import asyncio
import signal
from typing import Optional

from analysis.context_engine import ContextEngine
from arbitrage.graph.currency_graph import CurrencyGraph
from arbitrage.graph.graph_arbitrage import GraphArbitrage
from brain.decision.engine import DecisionEngine
from brain.decision.positions import PositionTracker
from brain.decision.risk_manager import RiskManager
from brain.fleet.monitor import FleetMonitor
from brain.orders.log import OrderLog
from brain.security.auth_manager import AuthManager
from brain.stream.subscriber import StreamSubscriber
from brain.auto_spawner import AutoSpawner
from config.loader import load_config, AppConfig
from alerts.sender import AlertSender
from storage.db.persistence import PersistenceLayer
from messaging.bus import MessageBus
from messaging.logging import get_logger, setup_logging
from storage.market_state import MarketState

logger = get_logger("brain.main")


class Brain:
    def __init__(self, config_path: Optional[str] = None):
        self.config: AppConfig = load_config(config_path)
        setup_logging(self.config.brain.log_level)

        self.bus           = MessageBus(host=self.config.redis.host, port=self.config.redis.port)
        self.market_state  = MarketState()
        self.auth_manager  = AuthManager(nonce_ttl=self.config.security.nonce_ttl_seconds)
        self.fleet_monitor = FleetMonitor(bus=self.bus, heartbeat_ttl=self.config.security.heartbeat_ttl)
        self.context_engine = ContextEngine(analysis_config=self.config.analysis.model_dump())

        self.currency_graph  = CurrencyGraph(
            stale_threshold_seconds=self.config.graph.stale_edge_s,
            graph_config=self.config.graph,
        )
        self.graph_arbitrage = GraphArbitrage(config=self.config, graph=self.currency_graph)
        self._graph_paths: list = []

        # v4.6 — Auto-spawner: creates worker containers from EXCHANGES config
        self.auto_spawner = AutoSpawner(
            config       = self.config,
            bus          = self.bus,
            fleet_monitor= self.fleet_monitor,
        )

        # v3.3 — Decision pipeline
        self.order_log        = OrderLog()
        self.alert_sender     = AlertSender(self.config)
        self.persistence      = PersistenceLayer(self.config.postgres.dsn)
        self.risk_manager     = RiskManager(self.config, self.market_state)
        self.position_tracker = PositionTracker(self.bus, self.market_state)
        self.decision_engine  = DecisionEngine(
            config=self.config, bus=self.bus,
            market_state=self.market_state, risk_manager=self.risk_manager,
            alert_sender=self.alert_sender,
        )

        self.stream_sub = StreamSubscriber(
            bus=self.bus, market_state=self.market_state,
            context_engine=self.context_engine, auth_manager=self.auth_manager,
            config=self.config, currency_graph=self.currency_graph,
            decision_engine=self.decision_engine, position_tracker=self.position_tracker,
            order_log=self.order_log, risk_manager=self.risk_manager,
            alert_sender=self.alert_sender,
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
        logger.info(f"  Trading Mode   : {self.config.trading.mode.value.upper()}")
        logger.info(f"  Decision Engine: {'enabled' if self.config.decision.enabled else 'disabled'}")
        logger.info(f"  Risk Manager   : {'enabled' if self.config.risk.enabled else 'disabled'} "
                    f"(max loss ${self.config.risk.max_daily_loss_usd}/day)")
        logger.info(f"  API            : {cfg.api_host}:{cfg.api_port}")
        logger.info(f"  Metrics        : :{self.config.brain.metrics_port}/metrics")
        logger.info(f"  CR 9AM         : {'enabled' if self.config.analysis.cr_9am.enabled else 'disabled'}")
        logger.info(f"  Graph Arbitrage: enabled | algo={self.config.graph.algorithm} | "
                    f"max_hops={self.config.graph.max_hops} | "
                    f"min_profit={self.config.graph.min_profit_pct}%")
        logger.info("=" * 60)

    async def _graph_scan_loop(self) -> None:
        scan_interval = 5   # seconds between BF scans
        while True:
            await asyncio.sleep(scan_interval)
            try:
                paths = await self.graph_arbitrage.scan()
                if paths:
                    self._graph_paths = [p.to_dict() for p in paths]
                    for p in paths[:3]:
                        logger.info(
                            f"[GRAPH/{self.config.graph.algorithm.upper()[:2]}] "
                            f"{p.path_string} | {p.hops} hops | "
                            f"net {p.net_profit_pct(self.config.graph.capital_usd):.3f}%"
                        )
                        await self.decision_engine.on_graph_path(p.to_dict())
            except Exception as exc:
                logger.error(f"Graph scan error: {exc}")

    async def start(self) -> None:
        self._setup_signals()
        self._print_banner()
        await self.bus.connect()
        await self.alert_sender.start()
        await self.persistence.start()
        logger.info("Brain connected to message bus.")

        # Emit startup event
        try:
            from events.event_bus import emit, Category, Level
            await emit(
                category = Category.SYSTEM,
                title    = f"Brain started — ARBX v{self.config.brain.version}",
                detail   = (
                    f"Mode={self.config.trading.mode.value.upper()} · "
                    f"Algo={self.config.graph.algorithm} · "
                    f"API={self.config.brain.api_host}:{self.config.brain.api_port}"
                ),
                level    = Level.INFO,
            )
        except Exception:
            pass

        tasks = [
            asyncio.create_task(self.stream_sub.run(),          name="stream_subscriber"),
            asyncio.create_task(self.fleet_monitor.start(),     name="fleet_monitor"),
            asyncio.create_task(self._graph_scan_loop(),        name="graph_arbitrage"),
            asyncio.create_task(self._start_api(),              name="api_server"),
            asyncio.create_task(self._start_metrics(),          name="metrics_server"),
            asyncio.create_task(self.auto_spawner.start(),      name="auto_spawner"),
        ]

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

    async def _start_metrics(self) -> None:
        from monitoring.metrics import start_metrics_server
        await start_metrics_server(self, self.config.brain.metrics_port)

    async def _start_api(self) -> None:
        import uvicorn
        from api.main import create_app
        app = create_app(self)
        cfg = self.config.brain
        server = uvicorn.Server(uvicorn.Config(
            app=app, host=cfg.api_host, port=cfg.api_port, log_level="warning",
        ))
        await server.serve()


def run(config_path: Optional[str] = None) -> None:
    brain = Brain(config_path)
    asyncio.run(brain.start())

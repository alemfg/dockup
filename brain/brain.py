"""
Brain — central analysis and orchestration node.
v3.3: Decision engine, risk manager, position tracker, order log added.
"""
from __future__ import annotations
import os

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
from trading.executor  import OrderExecutor
from trading.order_sync import OrderSyncLoop
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

        # v3.3 — Decision pipeline (must come before auto_spawner so persistence exists)
        self.persistence      = PersistenceLayer(self.config.postgres.dsn)
        self.alert_sender     = AlertSender(self.config)
        self.order_log        = OrderLog()
        self.order_executor   = OrderExecutor(self.bus, self.config, self.persistence)
        self.order_sync       = OrderSyncLoop(self.bus, self.order_log, self.config, self.persistence)
        self.risk_manager     = RiskManager(self.config, self.market_state)
        self.position_tracker = PositionTracker(self.bus, self.market_state, config=self.config)
        self.decision_engine  = DecisionEngine(
            config=self.config, bus=self.bus,
            market_state=self.market_state, risk_manager=self.risk_manager,
            alert_sender=self.alert_sender,
        )

        # v4.6 — Auto-spawner: creates worker containers from EXCHANGES config
        self.auto_spawner = AutoSpawner(
            config       = self.config,
            bus          = self.bus,
            fleet_monitor= self.fleet_monitor,
            persistence  = self.persistence,
        )
        self.stream_sub = StreamSubscriber(
            bus=self.bus, market_state=self.market_state,
            context_engine=self.context_engine, auth_manager=self.auth_manager,
            config=self.config, currency_graph=self.currency_graph,
            decision_engine=self.decision_engine, position_tracker=self.position_tracker,
            order_log=self.order_log, risk_manager=self.risk_manager,
            alert_sender=self.alert_sender,
        )
        # Inject persistence so subscriber can DB-persist order results
        self.stream_sub._persistence = self.persistence

        self._shutdown_event = asyncio.Event()

    def _setup_signals(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: self._shutdown_event.set())

    def _print_banner(self) -> None:
        cfg = self.config.brain
        build_ver = os.getenv("ARBX_BUILD_VERSION", "dev")
        build_date = os.getenv("ARBX_BUILD_DATE", "unknown")
        logger.info("=" * 60)
        logger.info(f"  ARBX Brain v{cfg.version}  [image build: {build_ver} / {build_date}]")
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

    async def _spatial_scan_loop(self) -> None:
        """Scan spatial (cross-exchange) spreads every 10s and route to decision engine."""
        while True:
            await asyncio.sleep(10)
            try:
                pairs = self.market_state.get_all_pairs()
                for pair in pairs:
                    prices = self.market_state.get_prices_for_pair(pair)
                    if len(prices) < 2:
                        continue
                    entries  = sorted(prices.items(), key=lambda x: x[1])
                    buy_ex,  buy_price  = entries[0]
                    sell_ex, sell_price = entries[-1]
                    if buy_price <= 0:
                        continue
                    gross_pct = ((sell_price - buy_price) / buy_price) * 100
                    fee_pct   = (self.config.graph.fee_for(buy_ex) +
                                 self.config.graph.fee_for(sell_ex)) * 100
                    net_pct   = gross_pct - fee_pct
                    if net_pct > 0:
                        await self.decision_engine.on_spatial_spread({
                            "pair":       pair,
                            "buy_ex":     buy_ex,
                            "sell_ex":    sell_ex,
                            "buy_price":  buy_price,
                            "sell_price": sell_price,
                            "gross_pct":  round(gross_pct, 4),
                            "net_pct":    round(net_pct, 4),
                            "fee_pct":    round(fee_pct, 4),
                        })
            except Exception as exc:
                logger.error(f"Spatial scan error: {exc}")

    async def start(self) -> None:
        self._setup_signals()
        self._print_banner()
        await self.bus.connect()
        await self.alert_sender.start()
        await self.persistence.start()
        logger.info("Brain connected to message bus.")

        # Apply DB config overrides (config_store wins over .env for non-secret settings)
        try:
            cs = self.persistence.config_store
            if cs and cs._pool:
                items = await cs.get_all()
                applied = 0
                for item in items:
                    key = item["key"]
                    val = await cs.get(key)
                    if val is None:
                        continue
                    # Map known keys to config fields
                    try:
                        if key == "trading.mode" and val in ("disabled","simulate","live"):
                            from config.loader import TradingMode
                            self.config.trading.mode = TradingMode(val)
                            applied += 1
                        elif key.startswith("risk."):
                            field = key[5:]
                            if hasattr(self.config.risk, field):
                                setattr(self.config.risk, field, val)
                                applied += 1
                        elif key.startswith("decision."):
                            field = key[9:]
                            if hasattr(self.config.decision, field):
                                setattr(self.config.decision, field, val)
                                applied += 1
                        elif key.startswith("graph."):
                            field = key[6:]
                            if hasattr(self.config.graph, field):
                                setattr(self.config.graph, field, val)
                                applied += 1
                    except Exception:
                        pass
                if applied:
                    logger.info(f"Applied {applied} config overrides from DB")
        except Exception as exc:
            logger.warning(f"Could not load DB config overrides: {exc}")

        # Restore order history from DB (so P&L survives restarts)
        try:
            recent = await self.persistence.load_recent_orders(limit=2000)
            for o in reversed(recent):          # oldest first so log order is correct
                if o.get("id") and o.get("id") not in self.order_log._orders:
                    self.order_log.record_command(o)
                    if o.get("status") == "closed":
                        self.order_log._orders[o["id"]]["status"]     = "closed"
                        self.order_log._orders[o["id"]]["pnl_usd"]    = o.get("pnl_usd", 0)
                        self.order_log._orders[o["id"]]["closed_at"]  = o.get("closed_at", "")
                        self.order_log._orders[o["id"]]["close_reason"] = o.get("close_reason", "")
            if recent:
                logger.info(f"Restored {len(recent)} orders from DB")
        except Exception as exc:
            logger.warning(f"Could not restore orders from DB: {exc}")

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
            asyncio.create_task(self._spatial_scan_loop(),      name="spatial_arb"),
            asyncio.create_task(self._start_api(),              name="api_server"),
            asyncio.create_task(self._start_metrics(),          name="metrics_server"),
            asyncio.create_task(self.auto_spawner.start(),      name="auto_spawner"),
            asyncio.create_task(self.order_executor.start(),   name="order_executor"),
            asyncio.create_task(self.order_sync.run(),         name="order_sync"),
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
        """
        Run the FastAPI/uvicorn server in a dedicated thread with its own
        event loop so Redis stream processing never blocks API responses.
        """
        import threading
        import uvicorn
        from api.main import create_app

        app = create_app(self)
        cfg = self.config.brain
        config = uvicorn.Config(
            app=app,
            host=cfg.api_host,
            port=cfg.api_port,
            log_level="warning",
            loop="asyncio",
        )
        server = uvicorn.Server(config)

        # Run uvicorn in its own thread with its own event loop.
        # This isolates it completely from the brain's Redis stream loop.
        def _run_server():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve())
            loop.close()

        thread = threading.Thread(target=_run_server, name="api-server", daemon=True)
        thread.start()
        logger.info(f"API server started in background thread on :{cfg.api_port}")

        # Keep this coroutine alive so cancellation during shutdown propagates
        while not server.should_exit:
            await asyncio.sleep(1)
        server.should_exit = True


def run(config_path: Optional[str] = None) -> None:
    brain = Brain(config_path)
    asyncio.run(brain.start())

"""dockup main entrypoint — starts all components."""
from __future__ import annotations

import asyncio
import signal
import sys

import uvicorn

from dockup.api.app import create_app
from dockup.backup.engine import BackupEngine
from dockup.config import get_settings
from dockup.discovery.manager import DiscoveryManager
from dockup.logging_config import get_logger, setup_logging
from dockup.metrics.collector import MetricsCollector
from dockup.notifications.manager import NotificationManager
from dockup.scheduler.scheduler import BackupScheduler
from dockup.storage.backend import create_backend


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log.level, settings.log.format)
    log = get_logger()
    log.info("dockup starting", version=settings.version)

    # Ensure output directory exists
    settings.backup.output_dir.mkdir(parents=True, exist_ok=True)

    # Initialise components
    storage = create_backend(settings.storage)
    metrics = MetricsCollector()
    notifier = NotificationManager(settings.notifications)

    discovery = DiscoveryManager(
        cfg=settings.discovery,
        env_targets=[],  # populated from config file / env
    )

    engine = BackupEngine(
        cfg=settings.backup,
        storage=storage,
        metrics=metrics,
        notifier=notifier,
    )

    scheduler = BackupScheduler(
        cfg=settings.schedule,
        engine=engine,
        discovery=discovery,
    )

    app = create_app(settings, engine, discovery, metrics)

    # Configure uvicorn
    uv_config = uvicorn.Config(
        app=app,
        host=settings.api.host,
        port=settings.api.port,
        log_level=settings.log.level,
        access_log=False,  # handled by our middleware
        ssl_certfile=settings.api.cert_file or None,
        ssl_keyfile=settings.api.key_file or None,
    )
    server = uvicorn.Server(uv_config)

    # Graceful shutdown handler
    loop = asyncio.get_event_loop()
    stop = asyncio.Event()

    def _handle_signal():
        log.info("Shutdown signal received")
        stop.set()
        server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log.info("Starting all services", host=settings.api.host, port=settings.api.port)

    await asyncio.gather(
        discovery.run(),
        scheduler.start(),
        server.serve(),
        return_exceptions=True,
    )

    log.info("dockup stopped")


if __name__ == "__main__":
    asyncio.run(main())

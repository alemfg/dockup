"""
Backup engine — manages the async worker pool, job lifecycle,
retention enforcement, metrics emission, and alert dispatch.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import structlog

from dockup.config import BackupSettings
from dockup.drivers.drivers import get_driver
from dockup.metrics.collector import MetricsCollector
from dockup.models import BackupJob, BackupStatus, DatabaseTarget
from dockup.notifications.manager import NotificationManager
from dockup.models import Alert, AlertLevel
from dockup.storage.backend import StorageBackend

log = structlog.get_logger(__name__)


class BackupEngine:
    """Orchestrates backup jobs via an async worker pool."""

    def __init__(
        self,
        cfg: BackupSettings,
        storage: StorageBackend,
        metrics: MetricsCollector,
        notifier: NotificationManager,
    ) -> None:
        self._cfg = cfg
        self._storage = storage
        self._metrics = metrics
        self._notifier = notifier
        self._queue: asyncio.Queue[tuple[DatabaseTarget, asyncio.Future[BackupJob]]] = asyncio.Queue(maxsize=200)
        self._history: deque[BackupJob] = deque(maxlen=500)
        self._workers: list[asyncio.Task[None]] = []
        self._start_time = time.time()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self._cfg.worker_count)
        ]
        self._metrics.set_worker_count(self._cfg.worker_count)
        log.info("Backup worker pool started", workers=self._cfg.worker_count)

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        log.info("Backup worker pool stopped")

    # ── Public API ────────────────────────────────────────────────────────

    async def trigger(self, target: DatabaseTarget) -> BackupJob:
        """Enqueue a backup and wait for the result."""
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[BackupJob] = loop.create_future()
        await self._queue.put((target, fut))
        self._metrics.set_queue_depth(self._queue.qsize())
        return await fut

    async def trigger_async(self, target: DatabaseTarget) -> None:
        """Fire-and-forget backup trigger."""
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[BackupJob] = loop.create_future()
        await self._queue.put((target, fut))
        self._metrics.set_queue_depth(self._queue.qsize())

    def get_history(self, target_id: str = "", limit: int = 100) -> list[BackupJob]:
        jobs = list(self._history)
        if target_id:
            jobs = [j for j in jobs if j.target_id == target_id]
        return list(reversed(jobs))[:limit]

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    # ── Worker ────────────────────────────────────────────────────────────

    async def _worker(self, worker_id: int) -> None:
        wlog = log.bind(worker=worker_id)
        wlog.debug("Worker started")
        while True:
            try:
                target, fut = await self._queue.get()
                self._metrics.set_queue_depth(self._queue.qsize())
                job = await self._execute(target)
                if not fut.done():
                    fut.set_result(job)
                self._queue.task_done()
            except asyncio.CancelledError:
                wlog.debug("Worker stopped")
                return
            except Exception as exc:
                wlog.error("Worker error", error=str(exc))

    # ── Execution ─────────────────────────────────────────────────────────

    async def _execute(self, target: DatabaseTarget) -> BackupJob:
        job = BackupJob(
            target_id=target.id,
            target_name=target.name,
            db_type=target.db_type,
            status=BackupStatus.RUNNING,
        )
        self._history.append(job)
        jlog = log.bind(job_id=job.id, target=target.name, db_type=target.db_type)
        jlog.info("Backup job started")

        try:
            driver = get_driver(target.db_type)
        except ValueError as exc:
            return self._fail(job, str(exc), jlog)

        # Build output path
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"{target.name}_{ts}.{driver.extension}"
        output_path = self._cfg.output_dir / target.db_type / target.name / filename

        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                driver.backup(target, output_path, self._cfg.timeout_seconds),
                timeout=self._cfg.timeout_seconds + 30,
            )
        except Exception as exc:
            self._metrics.record_failure(target.db_type, target.name)
            await self._notifier.send(Alert(
                level=AlertLevel.ERROR,
                title=f"Backup failed: {target.name}",
                message=str(exc),
                target=target.name,
            ))
            return self._fail(job, str(exc), jlog)

        # Success
        duration = time.monotonic() - t0
        job.status = BackupStatus.SUCCESS
        job.finished_at = datetime.utcnow()
        job.duration_seconds = round(duration, 2)
        job.output_path = str(result.path)
        job.size_bytes = result.size_bytes

        self._metrics.record_success(target.db_type, target.name, duration, result.size_bytes)

        jlog.info(
            "Backup completed",
            duration=job.duration_seconds,
            size_bytes=job.size_bytes,
            path=job.output_path,
        )

        await self._notifier.send(Alert(
            level=AlertLevel.INFO,
            title=f"Backup succeeded: {target.name}",
            message=f"Size: {result.size_bytes:,} bytes · Duration: {duration:.1f}s",
            target=target.name,
        ))

        # Apply retention asynchronously
        asyncio.create_task(self._apply_retention(target, output_path.parent))
        return job

    def _fail(self, job: BackupJob, error: str, jlog: structlog.BoundLogger) -> BackupJob:
        job.status = BackupStatus.FAILED
        job.finished_at = datetime.utcnow()
        job.error = error
        jlog.error("Backup job failed", error=error)
        return job

    async def _apply_retention(self, target: DatabaseTarget, directory: Path) -> None:
        try:
            await asyncio.to_thread(
                self._storage.apply_retention,
                directory,
                self._cfg.retention.max_count,
                self._cfg.retention.max_age_hours,
            )
        except Exception as exc:
            log.warning("Retention cleanup failed", target=target.name, error=str(exc))

"""Cron-based backup scheduler using APScheduler."""
from __future__ import annotations

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from dockup.backup.engine import BackupEngine
from dockup.config import ScheduleSettings
from dockup.discovery.manager import DiscoveryManager
from dockup.models import DatabaseTarget

log = structlog.get_logger(__name__)

_SHORTHAND: dict[str, str] = {
    "@hourly":   "0 * * * *",
    "@daily":    "0 2 * * *",
    "@midnight": "0 0 * * *",
    "@weekly":   "0 2 * * 0",
    "@monthly":  "0 2 1 * *",
}


class BackupScheduler:
    """Manages per-target cron schedules and re-evaluates on discovery updates."""

    def __init__(
        self,
        cfg: ScheduleSettings,
        engine: BackupEngine,
        discovery: DiscoveryManager,
    ) -> None:
        self._cfg = cfg
        self._engine = engine
        self._discovery = discovery
        self._scheduler = AsyncIOScheduler()
        self._scheduled_ids: set[str] = set()

    async def start(self) -> None:
        self._scheduler.start()
        # Sync schedules periodically
        self._scheduler.add_job(
            self._sync_schedules,
            trigger=IntervalTrigger(seconds=self._cfg.check_interval_seconds),
            id="__sync__",
            replace_existing=True,
        )
        await self._sync_schedules()
        log.info("Backup scheduler started")

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        log.info("Backup scheduler stopped")

    async def _sync_schedules(self) -> None:
        targets = {t.id: t for t in self._discovery.get_targets() if t.enabled}

        # Remove stale jobs
        for tid in list(self._scheduled_ids):
            if tid not in targets:
                try:
                    self._scheduler.remove_job(tid)
                except Exception:
                    pass
                self._scheduled_ids.discard(tid)

        # Add new jobs
        for tid, target in targets.items():
            if tid not in self._scheduled_ids:
                self._add_job(target)

    def _add_job(self, target: DatabaseTarget) -> None:
        cron_expr = _SHORTHAND.get(target.schedule, target.schedule or self._cfg.default_cron)
        parts = cron_expr.split()
        if len(parts) != 5:
            log.warning("Invalid cron expression", target=target.name, cron=cron_expr)
            cron_expr = self._cfg.default_cron
            parts = cron_expr.split()

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        self._scheduler.add_job(
            self._run_backup,
            trigger=trigger,
            args=[target],
            id=target.id,
            name=f"backup-{target.name}",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
        )
        self._scheduled_ids.add(target.id)
        log.debug("Scheduled backup", target=target.name, cron=cron_expr)

    async def _run_backup(self, target: DatabaseTarget) -> None:
        log.info("Scheduled backup triggered", target=target.name)
        try:
            await self._engine.trigger_async(target)
        except Exception as exc:
            log.error("Failed to enqueue scheduled backup", target=target.name, error=str(exc))

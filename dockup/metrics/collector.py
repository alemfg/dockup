"""Prometheus metrics for dockup."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, REGISTRY


class MetricsCollector:
    def __init__(self) -> None:
        self.jobs_total = Counter(
            "dockup_jobs_total",
            "Total number of backup jobs executed",
            ["db_type", "target", "status"],
        )
        self.jobs_failed = Counter(
            "dockup_jobs_failed_total",
            "Total number of failed backup jobs",
            ["db_type", "target"],
        )
        self.job_duration = Histogram(
            "dockup_job_duration_seconds",
            "Duration of backup jobs in seconds",
            ["db_type", "target"],
            buckets=(1, 2, 5, 10, 30, 60, 120, 300, 600, 1800, 3600),
        )
        self.backup_size = Gauge(
            "dockup_backup_size_bytes",
            "Size of the last successful backup in bytes",
            ["db_type", "target"],
        )
        self.last_success = Gauge(
            "dockup_last_success_timestamp",
            "Unix timestamp of the last successful backup",
            ["db_type", "target"],
        )
        self.discovered_databases = Gauge(
            "dockup_discovered_databases",
            "Number of discovered database targets",
        )
        self.active_workers = Gauge(
            "dockup_active_workers",
            "Number of active backup workers",
        )
        self.queue_depth = Gauge(
            "dockup_queue_depth",
            "Number of jobs currently in the backup queue",
        )

    def record_success(self, db_type: str, target: str, duration: float, size: int) -> None:
        self.jobs_total.labels(db_type=db_type, target=target, status="success").inc()
        self.job_duration.labels(db_type=db_type, target=target).observe(duration)
        self.backup_size.labels(db_type=db_type, target=target).set(size)
        self.last_success.labels(db_type=db_type, target=target).set_to_current_time()

    def record_failure(self, db_type: str, target: str) -> None:
        self.jobs_total.labels(db_type=db_type, target=target, status="failed").inc()
        self.jobs_failed.labels(db_type=db_type, target=target).inc()

    def set_discovered_count(self, n: int) -> None:
        self.discovered_databases.set(n)

    def set_worker_count(self, n: int) -> None:
        self.active_workers.set(n)

    def set_queue_depth(self, n: int) -> None:
        self.queue_depth.set(n)

    def zabbix_data(self) -> dict[str, float]:
        """Returns key metrics as a flat dict for Zabbix HTTP agent."""
        return {
            "dockup.discovered_databases": self.discovered_databases._value.get(),
            "dockup.active_workers": self.active_workers._value.get(),
            "dockup.queue_depth": self.queue_depth._value.get(),
        }

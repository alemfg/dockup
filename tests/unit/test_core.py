"""Unit tests for dockup core modules."""
from __future__ import annotations

import pytest
from dockup.models import BackupJob, BackupStatus, DatabaseTarget, DatabaseType


class TestModels:
    def test_database_target_defaults(self):
        t = DatabaseTarget(name="test-pg", db_type=DatabaseType.POSTGRES, host="localhost", port=5432)
        assert t.enabled is True
        assert t.retention_days == 7
        assert t.id != ""

    def test_backup_job_defaults(self):
        job = BackupJob(target_id="abc", target_name="pg", db_type="postgres")
        assert job.status == BackupStatus.PENDING
        assert job.size_bytes == 0

    def test_credentials_password_excluded(self):
        from dockup.models import Credentials
        c = Credentials(username="admin", password="secret")
        data = c.model_dump()
        assert "password" not in data


class TestConfig:
    def test_defaults(self):
        from dockup.config import Settings
        s = Settings()
        assert s.api.port == 8080
        assert s.backup.worker_count == 4
        assert s.storage.type == "local"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("DOCKUP_API_PORT", "9090")
        from dockup.config import Settings
        s = Settings()
        assert s.api.port == 9090


class TestDriverRegistry:
    def test_all_types_registered(self):
        from dockup.drivers.drivers import list_supported_types
        types = list_supported_types()
        assert DatabaseType.POSTGRES in types
        assert DatabaseType.MYSQL in types
        assert DatabaseType.MONGODB in types
        assert DatabaseType.REDIS in types

    def test_get_driver(self):
        from dockup.drivers.drivers import get_driver
        drv = get_driver(DatabaseType.POSTGRES)
        assert drv.db_type == DatabaseType.POSTGRES
        assert drv.extension == "dump"

    def test_unknown_type_raises(self):
        from dockup.drivers.drivers import get_driver
        with pytest.raises(ValueError):
            get_driver(DatabaseType.UNKNOWN)


class TestDiscoveryManager:
    def test_env_targets_loaded(self):
        from dockup.config import DiscoverySettings
        from dockup.discovery.manager import DiscoveryManager

        cfg = DiscoverySettings(docker_socket="unix:///nonexistent.sock")
        env_targets = [{
            "name": "my-pg",
            "type": "postgres",
            "host": "10.0.0.1",
            "port": "5432",
            "credentials": {"username": "user", "password": "pass"},
            "schedule": "@daily",
        }]
        mgr = DiscoveryManager(cfg, env_targets=env_targets)
        targets = mgr.get_targets()
        assert len(targets) == 1
        assert targets[0].name == "my-pg"
        assert targets[0].source == "env"

    def test_get_target_by_id(self):
        from dockup.config import DiscoverySettings
        from dockup.discovery.manager import DiscoveryManager

        cfg = DiscoverySettings(docker_socket="unix:///nonexistent.sock")
        env_targets = [{"name": "redis", "type": "redis", "host": "localhost", "port": "6379"}]
        mgr = DiscoveryManager(cfg, env_targets=env_targets)
        targets = mgr.get_targets()
        found = mgr.get_target(targets[0].id)
        assert found is not None
        assert found.name == "redis"


class TestMetrics:
    def test_record_success(self):
        from dockup.metrics.collector import MetricsCollector
        m = MetricsCollector()
        m.record_success("postgres", "my-pg", 12.5, 1024 * 1024)
        # No error = pass

    def test_record_failure(self):
        from dockup.metrics.collector import MetricsCollector
        m = MetricsCollector()
        m.record_failure("mysql", "my-mysql")

    def test_set_counts(self):
        from dockup.metrics.collector import MetricsCollector
        m = MetricsCollector()
        m.set_discovered_count(5)
        m.set_worker_count(4)
        m.set_queue_depth(2)

"""Integration tests for the FastAPI application."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dockup.api.app import create_app
from dockup.backup.engine import BackupEngine
from dockup.config import get_settings
from dockup.discovery.manager import DiscoveryManager
from dockup.metrics.collector import MetricsCollector
from dockup.notifications.manager import NotificationManager
from dockup.storage.backend import create_backend


@pytest.fixture
def client():
    settings = get_settings()
    storage = create_backend(settings.storage)
    metrics = MetricsCollector()
    notifier = NotificationManager(settings.notifications)
    discovery = DiscoveryManager(settings.discovery)
    engine = BackupEngine(settings.backup, storage, metrics, notifier)
    app = create_app(settings, engine, discovery, metrics)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def auth_token(client):
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "dockup"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ready(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True

    def test_metrics(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "dockup_discovered_databases" in resp.text


class TestAuth:
    def test_login_success(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "dockup"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["role"] == "admin"

    def test_login_failure(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    def test_protected_without_token(self, client):
        resp = client.get("/api/v1/databases")
        assert resp.status_code == 403

    def test_viewer_role(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "view"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "viewer"


class TestDatabases:
    def test_list_databases(self, client, auth_token):
        resp = client.get("/api/v1/databases", headers={"Authorization": auth_token})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_nonexistent(self, client, auth_token):
        resp = client.get("/api/v1/databases/does-not-exist", headers={"Authorization": auth_token})
        assert resp.status_code == 404


class TestRetention:
    def test_get_retention(self, client, auth_token):
        resp = client.get("/api/v1/retention", headers={"Authorization": auth_token})
        assert resp.status_code == 200
        data = resp.json()
        assert "max_count" in data
        assert "max_age_hours" in data

    def test_update_retention_admin(self, client, auth_token):
        resp = client.put(
            "/api/v1/retention",
            json={"max_count": 14, "max_age_hours": 336},
            headers={"Authorization": auth_token},
        )
        assert resp.status_code == 200

    def test_update_retention_viewer_denied(self, client):
        resp_login = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "view"})
        viewer_token = resp_login.json()["access_token"]
        resp = client.put(
            "/api/v1/retention",
            json={"max_count": 14, "max_age_hours": 336},
            headers={"Authorization": viewer_token},
        )
        assert resp.status_code == 403

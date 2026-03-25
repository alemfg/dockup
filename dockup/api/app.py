"""
FastAPI application — REST API, WebUI, Prometheus metrics, Zabbix endpoint.
JWT authentication with RBAC (admin / operator / viewer).
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from dockup.backup.engine import BackupEngine
from dockup.config import APISettings, Settings
from dockup.discovery.manager import DiscoveryManager
from dockup.metrics.collector import MetricsCollector
from dockup.models import (
    BackupJob,
    DatabaseTarget,
    LoginRequest,
    RetentionPolicy,
    SystemStatus,
    TokenResponse,
    TriggerBackupResponse,
    UpdateRetentionRequest,
)
from dockup.web.ui import WEB_UI_HTML

log = structlog.get_logger(__name__)
_START_TIME = time.time()

bearer_scheme = HTTPBearer(auto_error=False)


def create_app(
    settings: Settings,
    engine: BackupEngine,
    discovery: DiscoveryManager,
    metrics: MetricsCollector,
) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await engine.start()
        yield
        await engine.stop()

    app = FastAPI(
        title="dockup API",
        description="Automated database backup manager with Docker auto-discovery",
        version=settings.version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Auth helpers ──────────────────────────────────────────────────────

    def create_token(username: str, role: str) -> str:
        payload = {
            "sub": username,
            "role": role,
            "exp": datetime.utcnow() + timedelta(minutes=settings.api.jwt_expire_minutes),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.api.jwt_secret, algorithm=settings.api.jwt_algorithm)

    def decode_token(token: str) -> dict[str, Any]:
        try:
            return jwt.decode(token, settings.api.jwt_secret, algorithms=[settings.api.jwt_algorithm])
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    def get_current_user(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
    ) -> dict[str, Any]:
        if not credentials:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return decode_token(credentials.credentials)

    def require_role(*roles: str):
        def dep(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
            if user.get("role") not in roles:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
            return user
        return dep

    # ── Public endpoints ──────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_ui():
        return HTMLResponse(content=WEB_UI_HTML)

    @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    async def serve_ui_alias():
        return HTMLResponse(content=WEB_UI_HTML)

    @app.get("/health", tags=["Observability"])
    async def health():
        return {"status": "ok", "time": datetime.utcnow().isoformat()}

    @app.get("/ready", tags=["Observability"])
    async def ready():
        return {"ready": True}

    @app.get("/metrics", response_class=PlainTextResponse, tags=["Observability"])
    async def prometheus_metrics():
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/zabbix", tags=["Observability"])
    async def zabbix_metrics():
        return metrics.zabbix_data()

    # ── Auth ──────────────────────────────────────────────────────────────

    @app.post("/api/v1/auth/login", response_model=TokenResponse, tags=["Auth"])
    async def login(req: LoginRequest):
        # Demo credentials — replace with proper user store
        _USERS = {"admin": ("dockup", "admin"), "operator": ("operate", "operator"), "viewer": ("view", "viewer")}
        if req.username in _USERS:
            pwd, role = _USERS[req.username]
            if req.password == pwd:
                token = create_token(req.username, role)
                return TokenResponse(access_token=token, role=role)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # ── Databases ─────────────────────────────────────────────────────────

    @app.get("/api/v1/databases", response_model=list[DatabaseTarget], tags=["Databases"])
    async def list_databases(user: dict = Depends(get_current_user)):
        targets = discovery.get_targets()
        metrics.set_discovered_count(len(targets))
        return targets

    @app.get("/api/v1/databases/{target_id}", response_model=DatabaseTarget, tags=["Databases"])
    async def get_database(target_id: str, user: dict = Depends(get_current_user)):
        target = discovery.get_target(target_id)
        if not target:
            raise HTTPException(status_code=404, detail="Database target not found")
        return target

    # ── Backups ───────────────────────────────────────────────────────────

    @app.post("/api/v1/backup/{target_id}", response_model=TriggerBackupResponse, tags=["Backups"])
    async def trigger_backup(
        target_id: str,
        user: dict = Depends(require_role("admin", "operator"))
    ):
        target = discovery.get_target(target_id)
        if not target:
            raise HTTPException(status_code=404, detail="Database target not found")
        job = await engine.trigger(target)
        return TriggerBackupResponse(
            job_id=job.id,
            target_id=target.id,
            target_name=target.name,
            status=job.status,
            message=job.error or f"Backup completed in {job.duration_seconds:.1f}s" if job.duration_seconds else "Backup queued",
        )

    @app.get("/api/v1/history", response_model=list[BackupJob], tags=["Backups"])
    async def list_history(limit: int = 100, user: dict = Depends(get_current_user)):
        return engine.get_history(limit=limit)

    @app.get("/api/v1/history/{target_id}", response_model=list[BackupJob], tags=["Backups"])
    async def get_target_history(target_id: str, limit: int = 50, user: dict = Depends(get_current_user)):
        return engine.get_history(target_id=target_id, limit=limit)

    # ── Retention ─────────────────────────────────────────────────────────

    _retention: RetentionPolicy = RetentionPolicy(
        max_count=settings.backup.retention.max_count,
        max_age_hours=settings.backup.retention.max_age_hours,
    )

    @app.get("/api/v1/retention", response_model=RetentionPolicy, tags=["Retention"])
    async def get_retention(user: dict = Depends(get_current_user)):
        return _retention

    @app.put("/api/v1/retention", tags=["Retention"])
    async def update_retention(
        body: UpdateRetentionRequest,
        user: dict = Depends(require_role("admin"))
    ):
        _retention.max_count = body.max_count
        _retention.max_age_hours = body.max_age_hours
        return {"message": "Retention policy updated"}

    # ── Status ────────────────────────────────────────────────────────────

    @app.get("/api/v1/status", response_model=SystemStatus, tags=["Observability"])
    async def system_status(user: dict = Depends(get_current_user)):
        targets = discovery.get_targets()
        return SystemStatus(
            version=settings.version,
            uptime_seconds=round(time.time() - _START_TIME, 1),
            discovered_databases=len(targets),
            active_workers=settings.backup.worker_count,
            queue_depth=engine.queue_depth,
            recent_jobs=engine.get_history(limit=10),
        )

    return app

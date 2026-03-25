"""
Shared Pydantic models used across the dockup application.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DatabaseType(str, Enum):
    POSTGRES = "postgres"
    MYSQL = "mysql"
    MARIADB = "mariadb"
    MONGODB = "mongodb"
    REDIS = "redis"
    INFLUXDB = "influxdb"
    CLICKHOUSE = "clickhouse"
    ELASTICSEARCH = "elasticsearch"
    MSSQL = "mssql"
    UNKNOWN = "unknown"


class BackupStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Credentials(BaseModel):
    username: str = ""
    password: str = Field(default="", exclude=True)  # never serialise password
    database: str = ""
    auth_db: str = ""   # MongoDB authSource
    tls: bool = False


class DatabaseTarget(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    name: str
    db_type: DatabaseType
    host: str
    port: int
    credentials: Credentials = Field(default_factory=Credentials)
    schedule: str = "@daily"
    enabled: bool = True
    source: str = "docker"        # docker-local | docker-ssh | env
    container_id: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    retention_days: int = 7
    discovered_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class BackupJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_id: str
    target_name: str
    db_type: str
    status: BackupStatus = BackupStatus.PENDING
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    output_path: str = ""
    size_bytes: int = 0
    error: str = ""

    class Config:
        use_enum_values = True


class Alert(BaseModel):
    level: AlertLevel
    title: str
    message: str
    target: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetentionPolicy(BaseModel):
    max_count: int = 7
    max_age_hours: int = 168


class SystemStatus(BaseModel):
    version: str
    uptime_seconds: float
    discovered_databases: int
    active_workers: int
    queue_depth: int
    recent_jobs: list[BackupJob]


# ── API Request / Response Models ─────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class TriggerBackupResponse(BaseModel):
    job_id: str
    target_id: str
    target_name: str
    status: str
    message: str


class UpdateRetentionRequest(BaseModel):
    max_count: int = Field(ge=1, le=365)
    max_age_hours: int = Field(ge=1, le=8760)  # max 1 year

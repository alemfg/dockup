"""
dockup configuration — loaded from env vars, config file, or defaults.
All settings can be overridden via DOCKUP_ prefixed environment variables.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_LOG_")
    level: Literal["debug", "info", "warning", "error"] = "info"
    format: Literal["json", "console"] = "json"


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_API_")
    host: str = "0.0.0.0"
    port: int = 8080
    tls_enabled: bool = False
    cert_file: str = ""
    key_file: str = ""
    jwt_secret: str = "change-me-in-production-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480


class RetentionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_BACKUP_RETENTION_")
    max_count: int = 7
    max_age_hours: int = 168  # 7 days


class BackupSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_BACKUP_")
    output_dir: Path = Path("/backups")
    worker_count: int = 4
    timeout_seconds: int = 1800  # 30 min
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    compress: bool = True

    @field_validator("output_dir", mode="before")
    @classmethod
    def validate_output_dir(cls, v: str | Path) -> Path:
        return Path(v)


class DiscoverySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_DISCOVERY_")
    docker_socket: str = "unix:///var/run/docker.sock"
    label_prefix: str = "dockup"
    scan_interval_seconds: int = 60
    exclude_images: list[str] = Field(default_factory=lambda: ["dockup", "prometheus", "grafana"])


class LocalStorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_STORAGE_LOCAL_")
    path: Path = Path("/backups")


class S3Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_STORAGE_S3_")
    bucket: str = ""
    region: str = "us-east-1"
    endpoint_url: str = ""
    access_key: str = ""
    secret_key: str = ""
    prefix: str = "dockup/"


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_STORAGE_")
    type: Literal["local", "s3", "minio"] = "local"
    local: LocalStorageSettings = Field(default_factory=LocalStorageSettings)
    s3: S3Settings = Field(default_factory=S3Settings)


class NtfySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_NOTIFY_NTFY_")
    enabled: bool = False
    url: str = "https://ntfy.sh"
    topic: str = "dockup-alerts"
    token: str = ""
    min_level: str = "warning"


class SlackSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_NOTIFY_SLACK_")
    enabled: bool = False
    webhook_url: str = ""
    channel: str = "#ops-alerts"
    min_level: str = "warning"


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_NOTIFY_EMAIL_")
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to_addrs: list[str] = Field(default_factory=list)
    min_level: str = "error"


class WebhookSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_NOTIFY_WEBHOOK_")
    enabled: bool = False
    url: str = ""
    secret: str = ""
    min_level: str = "info"


class PagerDutySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_NOTIFY_PAGERDUTY_")
    enabled: bool = False
    integration_key: str = ""
    min_level: str = "critical"


class TeamsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_NOTIFY_TEAMS_")
    enabled: bool = False
    webhook_url: str = ""
    min_level: str = "error"


class NotificationSettings(BaseSettings):
    ntfy: NtfySettings = Field(default_factory=NtfySettings)
    slack: SlackSettings = Field(default_factory=SlackSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    webhook: WebhookSettings = Field(default_factory=WebhookSettings)
    pagerduty: PagerDutySettings = Field(default_factory=PagerDutySettings)
    teams: TeamsSettings = Field(default_factory=TeamsSettings)


class ScheduleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKUP_SCHEDULE_")
    default_cron: str = "0 2 * * *"  # 02:00 daily
    check_interval_seconds: int = 30


class Settings(BaseSettings):
    """Root application settings."""
    model_config = SettingsConfigDict(
        env_prefix="DOCKUP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    log: LogSettings = Field(default_factory=LogSettings)
    api: APISettings = Field(default_factory=APISettings)
    backup: BackupSettings = Field(default_factory=BackupSettings)
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)

    version: str = "1.0.0"


# Singleton settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

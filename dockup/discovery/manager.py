"""
Auto-discovery of database containers via Docker socket, SSH tunnels, and
manual environment-variable targets.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import docker
import structlog

from dockup.config import DiscoverySettings
from dockup.models import Credentials, DatabaseTarget, DatabaseType

log = structlog.get_logger(__name__)

# Image-name patterns → database type
_IMAGE_PATTERNS: list[tuple[re.Pattern[str], DatabaseType]] = [
    (re.compile(r"postgres|postgresql"), DatabaseType.POSTGRES),
    (re.compile(r"mysql"), DatabaseType.MYSQL),
    (re.compile(r"mariadb"), DatabaseType.MARIADB),
    (re.compile(r"mongo"), DatabaseType.MONGODB),
    (re.compile(r"redis"), DatabaseType.REDIS),
    (re.compile(r"influx"), DatabaseType.INFLUXDB),
    (re.compile(r"clickhouse"), DatabaseType.CLICKHOUSE),
    (re.compile(r"elastic|elasticsearch"), DatabaseType.ELASTICSEARCH),
    (re.compile(r"mssql|sqlserver"), DatabaseType.MSSQL),
]

# Port → database type
_PORT_MAP: dict[int, DatabaseType] = {
    5432: DatabaseType.POSTGRES,
    3306: DatabaseType.MYSQL,
    27017: DatabaseType.MONGODB,
    6379: DatabaseType.REDIS,
    9042: DatabaseType.ELASTICSEARCH,
    9200: DatabaseType.ELASTICSEARCH,
    8086: DatabaseType.INFLUXDB,
    8123: DatabaseType.CLICKHOUSE,
    9000: DatabaseType.CLICKHOUSE,
    1433: DatabaseType.MSSQL,
}

_DEFAULT_PORTS: dict[DatabaseType, int] = {
    DatabaseType.POSTGRES: 5432,
    DatabaseType.MYSQL: 3306,
    DatabaseType.MARIADB: 3306,
    DatabaseType.MONGODB: 27017,
    DatabaseType.REDIS: 6379,
    DatabaseType.INFLUXDB: 8086,
    DatabaseType.CLICKHOUSE: 8123,
    DatabaseType.ELASTICSEARCH: 9200,
    DatabaseType.MSSQL: 1433,
}

_DEFAULT_USERS: dict[DatabaseType, str] = {
    DatabaseType.POSTGRES: "postgres",
    DatabaseType.MYSQL: "root",
    DatabaseType.MARIADB: "root",
    DatabaseType.MONGODB: "admin",
    DatabaseType.MSSQL: "sa",
}


class DiscoveryManager:
    """Manages auto-discovery of database targets from all configured sources."""

    def __init__(self, cfg: DiscoverySettings, env_targets: list[dict[str, Any]] | None = None) -> None:
        self._cfg = cfg
        self._targets: dict[str, DatabaseTarget] = {}
        self._lock = asyncio.Lock()
        self._docker_clients: dict[str, Any] = {}
        self._running = False

        # Load env-defined manual targets immediately
        for et in (env_targets or []):
            t = self._env_target_to_model(et)
            self._targets[t.id] = t

        # Connect to local Docker socket
        try:
            client = docker.DockerClient(base_url=cfg.docker_socket)
            client.ping()
            self._docker_clients["local"] = client
            log.info("Connected to Docker socket", socket=cfg.docker_socket)
        except Exception as exc:
            log.warning("Could not connect to Docker socket", error=str(exc))

    # ── Public API ────────────────────────────────────────────────────────

    def get_targets(self) -> list[DatabaseTarget]:
        return list(self._targets.values())

    def get_target(self, target_id: str) -> DatabaseTarget | None:
        return self._targets.get(target_id)

    async def run(self) -> None:
        """Continuous discovery loop."""
        self._running = True
        log.info("Discovery manager started", interval=self._cfg.scan_interval_seconds)
        while self._running:
            await self._scan()
            await asyncio.sleep(self._cfg.scan_interval_seconds)

    def stop(self) -> None:
        self._running = False

    # ── Internal ─────────────────────────────────────────────────────────

    async def _scan(self) -> None:
        discovered: dict[str, DatabaseTarget] = {}

        # Preserve manually-configured env targets
        async with self._lock:
            for tid, t in self._targets.items():
                if t.source == "env":
                    discovered[tid] = t

        # Scan each Docker client
        for src_name, client in self._docker_clients.items():
            try:
                targets = await asyncio.to_thread(self._scan_docker, client, src_name)
                for t in targets:
                    discovered[t.id] = t
            except Exception as exc:
                log.warning("Docker scan failed", source=src_name, error=str(exc))

        async with self._lock:
            self._targets = discovered

        log.debug("Discovery scan complete", count=len(discovered))

    def _scan_docker(self, client: Any, source: str) -> list[DatabaseTarget]:
        containers = client.containers.list(filters={"status": "running"})
        targets = []
        for container in containers:
            t = self._container_to_target(container, source)
            if t:
                targets.append(t)
        return targets

    def _container_to_target(self, container: Any, source: str) -> DatabaseTarget | None:
        labels: dict[str, str] = container.labels or {}
        prefix = self._cfg.label_prefix + "."

        # Opt-out label
        if labels.get(prefix + "enable", "true").lower() == "false":
            return None

        # Detect DB type
        db_type = self._detect_type(container, labels, prefix)
        if db_type == DatabaseType.UNKNOWN:
            return None

        name = (container.name or "").lstrip("/")

        # Skip excluded images
        image_name = (container.image.tags[0] if container.image.tags else "").lower()
        if any(exc in image_name for exc in self._cfg.exclude_images):
            return None

        host = labels.get(prefix + "host", "127.0.0.1")
        port = int(labels.get(prefix + "port", _DEFAULT_PORTS.get(db_type, 0)))
        schedule = labels.get(prefix + "schedule", "@daily")
        retention_days = int(labels.get(prefix + "retention.days", "7"))

        creds = Credentials(
            username=labels.get(prefix + "username", _DEFAULT_USERS.get(db_type, "")),
            password=labels.get(prefix + "password", ""),
            database=labels.get(prefix + "database", ""),
            auth_db=labels.get(prefix + "auth_db", ""),
        )

        return DatabaseTarget(
            id=f"{source}-{container.short_id}",
            name=name,
            db_type=db_type,
            host=host,
            port=port,
            credentials=creds,
            schedule=schedule,
            enabled=True,
            source=f"docker-{source}",
            container_id=container.id,
            labels=labels,
            tags=[source, db_type.value],
            retention_days=retention_days,
        )

    def _detect_type(self, container: Any, labels: dict[str, str], prefix: str) -> DatabaseType:
        # 1. Explicit label
        if explicit := labels.get(prefix + "type"):
            return self._norm_type(explicit)

        # 2. Image name
        image_name = ""
        if container.image.tags:
            image_name = container.image.tags[0].lower()

        for pattern, db_type in _IMAGE_PATTERNS:
            if pattern.search(image_name):
                return db_type

        # 3. Exposed ports
        for port_binding in (container.ports or {}).values():
            if port_binding:
                for binding in port_binding:
                    try:
                        p = int(binding.get("HostPort", 0))
                        if p in _PORT_MAP:
                            return _PORT_MAP[p]
                    except (ValueError, TypeError):
                        pass

        return DatabaseType.UNKNOWN

    @staticmethod
    def _norm_type(s: str) -> DatabaseType:
        mapping = {
            "postgres": DatabaseType.POSTGRES,
            "postgresql": DatabaseType.POSTGRES,
            "mysql": DatabaseType.MYSQL,
            "mariadb": DatabaseType.MARIADB,
            "mongodb": DatabaseType.MONGODB,
            "mongo": DatabaseType.MONGODB,
            "redis": DatabaseType.REDIS,
            "influxdb": DatabaseType.INFLUXDB,
            "influx": DatabaseType.INFLUXDB,
            "clickhouse": DatabaseType.CLICKHOUSE,
            "elasticsearch": DatabaseType.ELASTICSEARCH,
            "elastic": DatabaseType.ELASTICSEARCH,
            "mssql": DatabaseType.MSSQL,
            "sqlserver": DatabaseType.MSSQL,
        }
        return mapping.get(s.lower(), DatabaseType.UNKNOWN)

    @staticmethod
    def _env_target_to_model(et: dict[str, Any]) -> DatabaseTarget:
        return DatabaseTarget(
            id="env-" + et["name"].lower().replace(" ", "-"),
            name=et["name"],
            db_type=DatabaseType(et["type"]),
            host=et["host"],
            port=int(et["port"]),
            credentials=Credentials(**et.get("credentials", {})),
            schedule=et.get("schedule", "@daily"),
            enabled=True,
            source="env",
            tags=["manual", et["type"]],
            retention_days=int(et.get("retention_days", 7)),
        )

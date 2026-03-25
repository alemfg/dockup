"""
Database backup drivers — each implements the BaseDriver interface
and shells out to the native CLI tool for maximum compatibility.
"""
from __future__ import annotations

import asyncio
import gzip
import os
import shutil
import subprocess
import tarfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

import structlog

from dockup.models import BackupJob, DatabaseTarget, DatabaseType

log = structlog.get_logger(__name__)


class BackupResult:
    __slots__ = ("path", "size_bytes")

    def __init__(self, path: Path, size_bytes: int) -> None:
        self.path = path
        self.size_bytes = size_bytes


class BaseDriver(ABC):
    """All drivers implement this interface."""

    db_type: ClassVar[DatabaseType]
    extension: ClassVar[str]

    @abstractmethod
    async def backup(
        self, target: DatabaseTarget, output_path: Path, timeout: int
    ) -> BackupResult:
        """Execute the backup and return the result."""

    @abstractmethod
    def validate(self, target: DatabaseTarget) -> None:
        """Raise ValueError if target configuration is invalid."""

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _run(
        self,
        cmd: list[str],
        env: dict[str, str] | None = None,
        timeout: int = 1800,
        output_file: Path | None = None,
        pipe_to_gzip: bool = False,
    ) -> bytes:
        """Run a subprocess, optionally piping stdout to a gzip file."""
        merged_env = {**os.environ, **(env or {})}
        log.debug("Running command", cmd=cmd[0], args=cmd[1:])

        if pipe_to_gzip and output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            proc_dump = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            with gzip.open(output_file, "wb", compresslevel=9) as gz:
                assert proc_dump.stdout is not None
                while chunk := await proc_dump.stdout.read(65536):
                    gz.write(chunk)
            await asyncio.wait_for(proc_dump.wait(), timeout=timeout)
            _, stderr = await proc_dump.communicate()
            if proc_dump.returncode != 0:
                raise RuntimeError(f"{cmd[0]} failed (rc={proc_dump.returncode}): {stderr.decode()[:500]}")
            return b""

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command {cmd[0]} timed out after {timeout}s")

        if proc.returncode != 0:
            raise RuntimeError(f"{cmd[0]} failed (rc={proc.returncode}): {stderr.decode()[:500]}")
        return stdout

    @staticmethod
    def _file_result(path: Path) -> BackupResult:
        return BackupResult(path=path, size_bytes=path.stat().st_size)


# ── PostgreSQL ─────────────────────────────────────────────────────────────────

class PostgresDriver(BaseDriver):
    db_type = DatabaseType.POSTGRES
    extension = "dump"  # pg_dump custom format (already compressed)

    def validate(self, target: DatabaseTarget) -> None:
        if not target.host:
            raise ValueError("PostgreSQL: host is required")

    async def backup(self, target: DatabaseTarget, output_path: Path, timeout: int) -> BackupResult:
        self.validate(target)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        db = target.credentials.database or "postgres"

        cmd = [
            "pg_dump",
            "--host", target.host,
            "--port", str(target.port),
            "--username", target.credentials.username,
            "--dbname", db,
            "--format", "custom",
            "--compress", "9",
            "--file", str(output_path),
            "--no-password",
        ]
        await self._run(cmd, env={"PGPASSWORD": target.credentials.password}, timeout=timeout)
        return self._file_result(output_path)


# ── MySQL ──────────────────────────────────────────────────────────────────────

class MySQLDriver(BaseDriver):
    db_type = DatabaseType.MYSQL
    extension = "sql.gz"

    def validate(self, target: DatabaseTarget) -> None:
        if not target.host:
            raise ValueError("MySQL: host is required")

    async def backup(self, target: DatabaseTarget, output_path: Path, timeout: int) -> BackupResult:
        self.validate(target)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "mysqldump",
            f"--host={target.host}",
            f"--port={target.port}",
            f"--user={target.credentials.username}",
            f"--password={target.credentials.password}",
            "--single-transaction",
            "--quick",
            "--routines",
            "--triggers",
            "--events",
            "--set-gtid-purged=OFF",
        ]
        if target.credentials.database:
            cmd.append(target.credentials.database)
        else:
            cmd.append("--all-databases")

        await self._run(cmd, output_file=output_path, pipe_to_gzip=True, timeout=timeout)
        return self._file_result(output_path)


# ── MariaDB (inherits MySQL) ────────────────────────────────────────────────────

class MariaDBDriver(MySQLDriver):
    db_type = DatabaseType.MARIADB


# ── MongoDB ────────────────────────────────────────────────────────────────────

class MongoDBDriver(BaseDriver):
    db_type = DatabaseType.MONGODB
    extension = "archive.gz"

    def validate(self, target: DatabaseTarget) -> None:
        pass

    async def backup(self, target: DatabaseTarget, output_path: Path, timeout: int) -> BackupResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        uri = f"mongodb://{target.credentials.username}:{target.credentials.password}@{target.host}:{target.port}"
        if target.credentials.auth_db:
            uri += f"/?authSource={target.credentials.auth_db}"

        cmd = [
            "mongodump",
            f"--uri={uri}",
            f"--archive={output_path}",
            "--gzip",
        ]
        if target.credentials.database:
            cmd.append(f"--db={target.credentials.database}")

        await self._run(cmd, timeout=timeout)
        return self._file_result(output_path)


# ── Redis ──────────────────────────────────────────────────────────────────────

class RedisDriver(BaseDriver):
    db_type = DatabaseType.REDIS
    extension = "rdb.gz"

    def validate(self, target: DatabaseTarget) -> None:
        pass

    async def backup(self, target: DatabaseTarget, output_path: Path, timeout: int) -> BackupResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        base_cmd = ["redis-cli", "-h", target.host, "-p", str(target.port)]
        if target.credentials.password:
            base_cmd += ["-a", target.credentials.password, "--no-auth-warning"]

        # Trigger background save
        await self._run(base_cmd + ["BGSAVE"], timeout=30)

        # Get RDB file location
        config_output = await self._run(base_cmd + ["CONFIG", "GET", "dir"], timeout=10)
        lines = config_output.decode().strip().splitlines()
        rdb_dir = lines[1].strip() if len(lines) >= 2 else "/data"
        rdb_path = Path(rdb_dir) / "dump.rdb"

        # Wait for save to complete
        for _ in range(60):
            result = await self._run(base_cmd + ["LASTSAVE"], timeout=10)
            await asyncio.sleep(1)
            if rdb_path.exists():
                break

        # Compress
        with open(rdb_path, "rb") as f_in, gzip.open(output_path, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out)

        return self._file_result(output_path)


# ── InfluxDB ───────────────────────────────────────────────────────────────────

class InfluxDBDriver(BaseDriver):
    db_type = DatabaseType.INFLUXDB
    extension = "tar.gz"

    def validate(self, target: DatabaseTarget) -> None:
        pass

    async def backup(self, target: DatabaseTarget, output_path: Path, timeout: int) -> BackupResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        backup_dir = output_path.parent / (output_path.stem + "_influx_backup")
        backup_dir.mkdir(parents=True, exist_ok=True)

        try:
            cmd = [
                "influx", "backup",
                "--host", f"http://{target.host}:{target.port}",
                "--token", target.credentials.password,
                str(backup_dir),
            ]
            await self._run(cmd, timeout=timeout)

            # Tar the directory
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(backup_dir, arcname=backup_dir.name)
        finally:
            shutil.rmtree(backup_dir, ignore_errors=True)

        return self._file_result(output_path)


# ── ClickHouse ─────────────────────────────────────────────────────────────────

class ClickHouseDriver(BaseDriver):
    db_type = DatabaseType.CLICKHOUSE
    extension = "sql.gz"

    def validate(self, target: DatabaseTarget) -> None:
        pass

    async def backup(self, target: DatabaseTarget, output_path: Path, timeout: int) -> BackupResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        db = target.credentials.database or "default"

        cmd = [
            "clickhouse-client",
            "--host", target.host,
            "--port", str(target.port),
            "--user", target.credentials.username,
            "--password", target.credentials.password,
            "--database", db,
            "--query", "SHOW CREATE TABLE system.tables FORMAT TabSeparated",
        ]
        await self._run(cmd, output_file=output_path, pipe_to_gzip=True, timeout=timeout)
        return self._file_result(output_path)


# ── Elasticsearch ──────────────────────────────────────────────────────────────

class ElasticsearchDriver(BaseDriver):
    db_type = DatabaseType.ELASTICSEARCH
    extension = "json.gz"

    def validate(self, target: DatabaseTarget) -> None:
        pass

    async def backup(self, target: DatabaseTarget, output_path: Path, timeout: int) -> BackupResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        url = f"http://{target.host}:{target.port}"
        if target.credentials.username:
            url = f"http://{target.credentials.username}:{target.credentials.password}@{target.host}:{target.port}"

        cmd = [
            "elasticdump",
            f"--input={url}",
            f"--output=$",
            "--type=data",
        ]
        await self._run(cmd, output_file=output_path, pipe_to_gzip=True, timeout=timeout)
        return self._file_result(output_path)


# ── Driver Registry ────────────────────────────────────────────────────────────

_REGISTRY: dict[DatabaseType, BaseDriver] = {}


def _register(driver: BaseDriver) -> None:
    _REGISTRY[driver.db_type] = driver


def get_driver(db_type: DatabaseType) -> BaseDriver:
    try:
        return _REGISTRY[db_type]
    except KeyError:
        raise ValueError(f"No backup driver registered for database type '{db_type}'")


def list_supported_types() -> list[DatabaseType]:
    return list(_REGISTRY.keys())


# Register all built-in drivers
for _drv in [
    PostgresDriver(),
    MySQLDriver(),
    MariaDBDriver(),
    MongoDBDriver(),
    RedisDriver(),
    InfluxDBDriver(),
    ClickHouseDriver(),
    ElasticsearchDriver(),
]:
    _register(_drv)

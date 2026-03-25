"""Storage backends for backup file management."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

import structlog

from dockup.config import StorageSettings

log = structlog.get_logger(__name__)


class StorageBackend(ABC):
    @abstractmethod
    def store(self, local_path: Path, remote_path: str) -> None:
        """Upload/copy file to the storage backend."""

    @abstractmethod
    def delete(self, remote_path: str) -> None:
        """Delete a file from the backend."""

    @abstractmethod
    def list_files(self, prefix: str) -> list[tuple[Path, float, int]]:
        """List (path, mtime, size) tuples under prefix."""

    def apply_retention(self, directory: Path, max_count: int, max_age_hours: int) -> None:
        """Delete old backups according to retention policy."""
        import time
        files = self.list_files(str(directory))
        if not files:
            return

        # Sort oldest first
        files.sort(key=lambda x: x[1])
        cutoff = time.time() - (max_age_hours * 3600)
        to_delete: list[Path] = []

        for path, mtime, _ in files:
            if max_age_hours > 0 and mtime < cutoff:
                to_delete.append(path)

        remaining = [f for f in files if f[0] not in to_delete]
        if max_count > 0 and len(remaining) > max_count:
            excess = len(remaining) - max_count
            to_delete.extend(f[0] for f in remaining[:excess])

        for path in to_delete:
            log.debug("Retention: deleting old backup", path=str(path))
            try:
                self.delete(str(path))
            except Exception as exc:
                log.warning("Failed to delete old backup", path=str(path), error=str(exc))


class LocalBackend(StorageBackend):
    """Local filesystem storage — files written directly by drivers."""

    def store(self, local_path: Path, remote_path: str) -> None:
        pass  # Files already written to the correct location by drivers

    def delete(self, remote_path: str) -> None:
        try:
            Path(remote_path).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Failed to delete file", path=remote_path, error=str(exc))

    def list_files(self, prefix: str) -> list[tuple[Path, float, int]]:
        base = Path(prefix)
        if not base.exists():
            return []
        result = []
        for f in base.rglob("*"):
            if f.is_file():
                stat = f.stat()
                result.append((f, stat.st_mtime, stat.st_size))
        return result


class S3Backend(StorageBackend):
    """AWS S3 / MinIO storage backend."""

    def __init__(self, cfg: StorageSettings) -> None:
        import boto3
        s3_cfg = cfg.s3
        kwargs: dict = {
            "aws_access_key_id": s3_cfg.access_key or None,
            "aws_secret_access_key": s3_cfg.secret_key or None,
            "region_name": s3_cfg.region,
        }
        if s3_cfg.endpoint_url:
            kwargs["endpoint_url"] = s3_cfg.endpoint_url
        self._s3 = boto3.client("s3", **kwargs)
        self._bucket = s3_cfg.bucket
        self._prefix = s3_cfg.prefix

    def store(self, local_path: Path, remote_path: str) -> None:
        key = self._prefix + remote_path.lstrip("/")
        log.info("Uploading to S3", bucket=self._bucket, key=key)
        self._s3.upload_file(str(local_path), self._bucket, key)

    def delete(self, remote_path: str) -> None:
        key = self._prefix + remote_path.lstrip("/")
        self._s3.delete_object(Bucket=self._bucket, Key=key)

    def list_files(self, prefix: str) -> list[tuple[Path, float, int]]:
        # S3 listing — returns synthetic Path objects
        response = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=self._prefix + prefix)
        result = []
        for obj in response.get("Contents", []):
            result.append((
                Path(obj["Key"]),
                obj["LastModified"].timestamp(),
                obj["Size"],
            ))
        return result


def create_backend(cfg: StorageSettings) -> StorageBackend:
    if cfg.type in ("s3", "minio"):
        return S3Backend(cfg)
    return LocalBackend()

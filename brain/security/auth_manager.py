"""
Auth Manager — handles mTLS verification, HMAC message signing,
nonce tracking, worker registration, and permission enforcement.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from messaging.logging import get_logger

logger = get_logger("brain.security.auth")


# ─── Worker Registry Entry ───────────────────────────────────────────────────

@dataclass
class RegisteredWorker:
    worker_id:           str
    exchange:            str
    allowed_pairs:       List[str]
    secret_key:          str
    cert_fingerprint:    str
    can_execute_orders:  bool = False
    max_order_size_usd:  float = 0.0
    ip_whitelist:        List[str] = field(default_factory=list)
    expires_at:          Optional[datetime] = None
    revoked:             bool = False
    registered_at:       datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True

    def can_cover_pair(self, pair: str) -> bool:
        return not self.allowed_pairs or pair in self.allowed_pairs

    def to_dict(self) -> dict:
        return {
            "worker_id":          self.worker_id,
            "exchange":           self.exchange,
            "allowed_pairs":      self.allowed_pairs,
            "cert_fingerprint":   self.cert_fingerprint,
            "can_execute_orders": self.can_execute_orders,
            "max_order_size_usd": self.max_order_size_usd,
            "expires_at":         self.expires_at.isoformat() if self.expires_at else None,
            "revoked":            self.revoked,
            "registered_at":      self.registered_at.isoformat(),
        }


# ─── Auth Manager ────────────────────────────────────────────────────────────

class AuthManager:
    """
    Central authentication and authorization for the worker fleet.

    Responsibilities:
    - Maintain registry of known workers and their permissions
    - Verify HMAC signatures on all incoming messages
    - Track nonces to prevent replay attacks
    - Enforce permission scopes per worker
    - Log and alert on suspicious activity
    """

    def __init__(self, nonce_ttl: int = 30):
        self._registry: Dict[str, RegisteredWorker] = {}
        self._nonce_ttl = nonce_ttl
        self._seen_nonces: Dict[str, float] = {}   # nonce → expiry_ts
        self._rejected_log: List[dict] = []
        self._active_ips: Dict[str, Set[str]] = {}  # worker_id → set of IPs

    # ─── Registration ────────────────────────────────────────────────────────

    def register_worker(
        self,
        worker_id:           str,
        exchange:            str,
        allowed_pairs:       List[str],
        can_execute_orders:  bool = False,
        max_order_size_usd:  float = 0.0,
        ip_whitelist:        List[str] = None,
        expires_days:        int = 30,
        cert_fingerprint:    str = "",
    ) -> str:
        """Register a new worker. Returns its secret key."""
        secret_key = secrets.token_hex(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

        worker = RegisteredWorker(
            worker_id=worker_id,
            exchange=exchange,
            allowed_pairs=allowed_pairs or [],
            secret_key=secret_key,
            cert_fingerprint=cert_fingerprint,
            can_execute_orders=can_execute_orders,
            max_order_size_usd=max_order_size_usd,
            ip_whitelist=ip_whitelist or [],
            expires_at=expires_at,
        )
        self._registry[worker_id] = worker
        logger.info(f"Worker registered: {worker_id} ({exchange}) expires {expires_at.date()}")
        return secret_key

    def revoke_worker(self, worker_id: str) -> bool:
        if worker_id in self._registry:
            self._registry[worker_id].revoked = True
            logger.warning(f"Worker revoked: {worker_id}")
            return True
        return False

    def get_worker(self, worker_id: str) -> Optional[RegisteredWorker]:
        return self._registry.get(worker_id)

    def list_workers(self) -> List[dict]:
        return [w.to_dict() for w in self._registry.values()]

    # ─── Message Verification ────────────────────────────────────────────────

    def sign_message(self, payload: dict, secret_key: str) -> dict:
        """Sign a message payload. Used by workers."""
        payload = dict(payload)
        payload["timestamp"] = time.time()
        payload["nonce"]     = secrets.token_hex(16)

        body = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            secret_key.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {"payload": payload, "signature": signature}

    def verify_message(
        self,
        message:   dict,
        source_ip: str = "",
    ) -> tuple[bool, str]:
        """
        Verify a signed message from a worker.
        Returns (is_valid, reason).
        """
        payload   = message.get("payload", {})
        signature = message.get("signature", "")
        worker_id = payload.get("worker_id", "")

        # ── Worker must be registered ────────────────────────────────────────
        worker = self._registry.get(worker_id)
        if not worker:
            self._log_rejection(worker_id, source_ip, "Unknown worker")
            return False, "Unknown worker"

        # ── Worker must not be revoked or expired ────────────────────────────
        if not worker.is_valid():
            self._log_rejection(worker_id, source_ip, "Revoked or expired")
            return False, "Worker revoked or expired"

        # ── Timestamp freshness (30 second window) ───────────────────────────
        msg_time = payload.get("timestamp", 0)
        if abs(time.time() - msg_time) > self._nonce_ttl:
            self._log_rejection(worker_id, source_ip, "Message too old (replay?)")
            return False, "Message timestamp too old"

        # ── Nonce uniqueness ─────────────────────────────────────────────────
        nonce = payload.get("nonce", "")
        if not nonce or self._is_nonce_seen(nonce):
            self._log_rejection(worker_id, source_ip, "Duplicate nonce (replay attack)")
            return False, "Duplicate nonce"
        self._mark_nonce(nonce)

        # ── IP whitelist check ───────────────────────────────────────────────
        if worker.ip_whitelist and source_ip and source_ip not in worker.ip_whitelist:
            self._log_rejection(worker_id, source_ip, f"IP not whitelisted: {source_ip}")
            return False, "IP not whitelisted"

        # ── Simultaneous IP detection (credential theft signal) ──────────────
        if source_ip:
            ips = self._active_ips.setdefault(worker_id, set())
            if len(ips) > 0 and source_ip not in ips:
                logger.warning(f"SECURITY: {worker_id} connecting from new IP {source_ip}")
            ips.add(source_ip)
            if len(ips) > 2:
                self._log_rejection(worker_id, source_ip, "Multiple IPs — possible credential theft")
                self.revoke_worker(worker_id)
                return False, "Credential theft suspected — worker revoked"

        # ── HMAC signature ───────────────────────────────────────────────────
        body     = json.dumps(payload, sort_keys=True)
        expected = hmac.new(
            worker.secret_key.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            self._log_rejection(worker_id, source_ip, "Invalid signature")
            return False, "Invalid signature"

        return True, "OK"

    # ─── Permission Checks ───────────────────────────────────────────────────

    def can_stream_pair(self, worker_id: str, pair: str) -> bool:
        worker = self._registry.get(worker_id)
        if not worker or not worker.is_valid():
            return False
        return worker.can_cover_pair(pair)

    def can_execute_order(
        self, worker_id: str, order_size_usd: float = 0.0
    ) -> tuple[bool, str]:
        worker = self._registry.get(worker_id)
        if not worker or not worker.is_valid():
            return False, "Worker not found or invalid"
        if not worker.can_execute_orders:
            return False, "Worker not authorized for order execution"
        if order_size_usd > worker.max_order_size_usd > 0:
            return False, f"Order size ${order_size_usd} exceeds limit ${worker.max_order_size_usd}"
        return True, "OK"

    # ─── Nonce Tracking ──────────────────────────────────────────────────────

    def _is_nonce_seen(self, nonce: str) -> bool:
        self._purge_expired_nonces()
        return nonce in self._seen_nonces

    def _mark_nonce(self, nonce: str) -> None:
        self._seen_nonces[nonce] = time.time() + self._nonce_ttl

    def _purge_expired_nonces(self) -> None:
        now = time.time()
        expired = [n for n, exp in self._seen_nonces.items() if exp < now]
        for n in expired:
            del self._seen_nonces[n]

    # ─── Rejection Log ───────────────────────────────────────────────────────

    def _log_rejection(self, worker_id: str, ip: str, reason: str) -> None:
        entry = {
            "worker_id": worker_id, "ip": ip,
            "reason": reason, "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._rejected_log.append(entry)
        if len(self._rejected_log) > 500:
            self._rejected_log.pop(0)
        logger.warning(f"REJECTED [{worker_id}] from {ip}: {reason}")

    def get_rejection_log(self, limit: int = 50) -> List[dict]:
        return list(reversed(self._rejected_log))[:limit]

    def rejection_count_24h(self) -> int:
        cutoff = time.time() - 86400
        return sum(
            1 for r in self._rejected_log
            if datetime.fromisoformat(r["timestamp"]).timestamp() > cutoff
        )

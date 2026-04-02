"""
Fleet Monitor — tracks all worker heartbeats, monitors data freshness,
detects blocked/overloaded/dead workers, and produces FleetActions.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from messaging.bus import MessageBus, STREAM_HEARTBEATS
from messaging.logging import get_logger
from messaging.models import (
    FleetAction, FleetActionType, WorkerCondition,
    WorkerHeartbeat, WorkerStatus,
)

logger = get_logger("brain.fleet.monitor")

# Error patterns → condition classification
_ERROR_PATTERNS = {
    WorkerCondition.IP_BLOCK:      ["403", "418", "banned", "forbidden", "access denied"],
    WorkerCondition.RATE_LIMIT:    ["429", "rate limit", "too many requests", "frequency"],
    WorkerCondition.EXCHANGE_DOWN: ["502", "503", "maintenance", "connection refused"],
    WorkerCondition.AUTH_ERROR:    ["401", "unauthorized", "invalid api key", "signature"],
}


def _classify_error(error: Optional[str]) -> WorkerCondition:
    if not error:
        return WorkerCondition.NONE
    error_lower = error.lower()
    for condition, patterns in _ERROR_PATTERNS.items():
        if any(p in error_lower for p in patterns):
            return condition
    return WorkerCondition.NONE


@dataclass
class WorkerState:
    worker_id:        str
    exchange:         str
    pairs:            List[str]
    machine:          str
    status:           WorkerStatus     = WorkerStatus.STARTING
    condition:        WorkerCondition  = WorkerCondition.NONE
    last_heartbeat:   float            = field(default_factory=time.time)
    latency_ms:       float            = 0.0
    ticks_per_min:    int              = 0
    cpu_pct:          float            = 0.0
    memory_mb:        float            = 0.0
    error_count:      int              = 0
    last_error:       Optional[str]    = None
    is_replacement:   bool             = False
    replaced_worker:  Optional[str]    = None
    # Data freshness per pair
    pair_last_tick:   Dict[str, float] = field(default_factory=dict)
    action_taken:     Optional[str]    = None   # last action type applied

    def is_dead(self, ttl: int = 15) -> bool:
        return (time.time() - self.last_heartbeat) > ttl

    def staleness(self, pair: str, threshold: int = 30) -> int:
        """Seconds since last tick for a pair."""
        last = self.pair_last_tick.get(pair, self.last_heartbeat)
        return int(time.time() - last)

    def to_dict(self) -> dict:
        return {
            "worker_id":       self.worker_id,
            "exchange":        self.exchange,
            "pairs":           self.pairs,
            "machine":         self.machine,
            "status":          self.status.value,
            "condition":       self.condition.value,
            "latency_ms":      self.latency_ms,
            "ticks_per_min":   self.ticks_per_min,
            "cpu_pct":         self.cpu_pct,
            "memory_mb":       self.memory_mb,
            "error_count":     self.error_count,
            "last_error":      self.last_error,
            "is_replacement":  self.is_replacement,
            "replaced_worker": self.replaced_worker,
            "last_heartbeat":  datetime.fromtimestamp(self.last_heartbeat).isoformat(),
            "action_taken":    self.action_taken,
        }


class FleetMonitor:
    """
    Consumes heartbeats from the message bus.
    Maintains live WorkerState for every connected worker.
    Evaluates health and produces FleetActions.
    """

    def __init__(self, bus: MessageBus, heartbeat_ttl: int = 15):
        self._bus         = bus
        self._ttl         = heartbeat_ttl
        self._workers:    Dict[str, WorkerState] = {}
        self._actions:    List[FleetAction] = []
        self._event_log:  List[dict] = []
        self._running     = False

    # ─── Start / Stop ────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        await asyncio.gather(
            self._consume_heartbeats(),
            self._health_check_loop(),
        )

    async def stop(self) -> None:
        self._running = False

    # ─── Heartbeat Consumer ──────────────────────────────────────────────────

    async def _consume_heartbeats(self) -> None:
        async def handler(stream: str, msg: dict) -> None:
            self._process_heartbeat(msg)

        await self._bus.subscribe(
            streams=[STREAM_HEARTBEATS],
            consumer_id="fleet_monitor",
            handler=handler,
        )

    def _process_heartbeat(self, msg: dict) -> None:
        wid = msg.get("worker_id", "")
        if not wid:
            return

        condition = _classify_error(msg.get("last_error"))

        if wid not in self._workers:
            self._workers[wid] = WorkerState(
                worker_id=wid,
                exchange=msg.get("exchange", ""),
                pairs=msg.get("pairs", []),
                machine=msg.get("machine", ""),
                is_replacement=msg.get("is_replacement", False),
                replaced_worker=msg.get("replaced_worker"),
            )
            self._log_event("INFO", f"New worker registered: {wid} ({msg.get('exchange')})")
            try:
                from events.event_bus import emit_sync, Category, Level
                pairs = msg.get("pairs", [])
                emit_sync(
                    category = Category.SYSTEM,
                    title    = f"Worker connected: {wid}",
                    detail   = f"Exchange={msg.get('exchange','')} · Pairs={len(pairs)} · Machine={msg.get('machine','')}",
                    level    = Level.INFO,
                    data     = {"worker_id": wid, "exchange": msg.get("exchange"), "pairs": pairs},
                )
            except Exception:
                pass

        w = self._workers[wid]
        w.last_heartbeat = time.time()
        w.pairs          = msg.get("pairs", w.pairs)
        w.machine        = msg.get("machine", w.machine)
        w.latency_ms     = msg.get("latency_ms", 0)
        w.ticks_per_min  = msg.get("ticks_last_60s", 0)
        w.cpu_pct        = msg.get("cpu_pct", 0)
        w.memory_mb      = msg.get("memory_mb", 0)
        w.error_count    = msg.get("error_count", 0)
        w.last_error     = msg.get("last_error")
        w.condition      = condition

        raw_status = msg.get("status", "healthy")
        try:
            w.status = WorkerStatus(raw_status)
        except ValueError:
            w.status = WorkerStatus.HEALTHY

        # Update per-pair tick freshness
        if w.ticks_per_min > 0:
            for pair in w.pairs:
                w.pair_last_tick[pair] = time.time()

    # ─── Health Check Loop ───────────────────────────────────────────────────

    async def _health_check_loop(self) -> None:
        while self._running:
            await asyncio.sleep(5)
            for worker in list(self._workers.values()):
                action = self._evaluate(worker)
                if action.action_type != FleetActionType.NONE:
                    self._actions.append(action)
                    worker.action_taken = action.action_type.value
                    self._log_event(
                        "WARNING" if action.urgency in ("HIGH", "CRITICAL") else "INFO",
                        f"Fleet action [{action.action_type.value}] for {worker.worker_id}: {action.reason}",
                    )
                    await self._bus.publish_event(action.to_dict())

    def _evaluate(self, w: WorkerState) -> FleetAction:
        """Evaluate worker health and return the appropriate action."""

        # ── Dead ──────────────────────────────────────────────────────────────
        if w.is_dead(self._ttl):
            w.status = WorkerStatus.DEAD
            return FleetAction(
                action_type=FleetActionType.RESPAWN,
                worker_id=w.worker_id,
                reason="Heartbeat lost — worker presumed dead",
                urgency="CRITICAL",
                same_machine=False,
                kill_original=True,
                avoid_machine=w.machine,
            )

        # ── IP blocked ────────────────────────────────────────────────────────
        if w.condition == WorkerCondition.IP_BLOCK:
            w.status = WorkerStatus.BLOCKED
            return FleetAction(
                action_type=FleetActionType.SPAWN_REPLACEMENT,
                worker_id=w.worker_id,
                reason=f"IP blocked on {w.exchange}",
                urgency="HIGH",
                same_machine=False,
                kill_original=True,
                avoid_machine=w.machine,
            )

        # ── Rate limited ──────────────────────────────────────────────────────
        if w.condition == WorkerCondition.RATE_LIMIT:
            w.status = WorkerStatus.DEGRADED
            return FleetAction(
                action_type=FleetActionType.SPAWN_COMPANION,
                worker_id=w.worker_id,
                reason="Rate limit — splitting request load",
                urgency="MEDIUM",
                same_machine=False,
                kill_original=False,
                split_pairs=True,
            )

        # ── Overloaded ────────────────────────────────────────────────────────
        if w.cpu_pct > 85 or w.memory_mb > 800:
            w.status = WorkerStatus.OVERLOADED
            return FleetAction(
                action_type=FleetActionType.SPAWN_COMPANION,
                worker_id=w.worker_id,
                reason=f"Overloaded (CPU: {w.cpu_pct:.0f}%, MEM: {w.memory_mb:.0f}MB)",
                urgency="MEDIUM",
                same_machine=False,
                kill_original=False,
                split_pairs=True,
            )

        # ── Stale data ────────────────────────────────────────────────────────
        for pair in w.pairs:
            stale_s = w.staleness(pair, threshold=30)
            if stale_s > 30 and w.status != WorkerStatus.BLOCKED:
                w.status = WorkerStatus.DEGRADED
                return FleetAction(
                    action_type=FleetActionType.SPAWN_PARALLEL,
                    worker_id=w.worker_id,
                    reason=f"Data stale for {pair} ({stale_s}s) — probing with parallel worker",
                    urgency="MEDIUM",
                    same_machine=False,
                    kill_original=False,
                    probe_mode=True,
                )

        # ── High latency ──────────────────────────────────────────────────────
        if w.latency_ms > 2000:
            w.status = WorkerStatus.DEGRADED
            return FleetAction(
                action_type=FleetActionType.SUGGEST,
                worker_id=w.worker_id,
                reason=f"High latency ({w.latency_ms:.0f}ms)",
                urgency="WARNING",
                suggestion=f"Consider deploying worker closer to {w.exchange} datacenter",
            )

        w.status = WorkerStatus.HEALTHY
        return FleetAction(
            action_type=FleetActionType.NONE,
            worker_id=w.worker_id,
            reason="",
        )

    # ─── Coverage Tracking ───────────────────────────────────────────────────

    def get_coverage_gaps(self) -> List[dict]:
        """Returns exchange:pair combinations with no active healthy worker."""
        covered = {}
        for w in self._workers.values():
            if w.status in (WorkerStatus.HEALTHY, WorkerStatus.DEGRADED):
                for pair in w.pairs:
                    covered[f"{w.exchange}:{pair}"] = w.worker_id

        # In a full implementation this would compare against
        # configured expected pairs — simplified here
        return []

    # ─── Queries ─────────────────────────────────────────────────────────────

    def get_all_workers(self) -> List[dict]:
        return [w.to_dict() for w in self._workers.values()]

    def get_worker(self, worker_id: str) -> Optional[WorkerState]:
        return self._workers.get(worker_id)

    def get_pending_actions(self) -> List[FleetAction]:
        actions = list(self._actions)
        self._actions.clear()
        return actions

    def get_event_log(self, limit: int = 100) -> List[dict]:
        return list(reversed(self._event_log))[:limit]

    def _log_event(self, level: str, message: str) -> None:
        entry = {"level": level, "message": message, "timestamp": datetime.now(timezone.utc).isoformat()}
        self._event_log.append(entry)
        if len(self._event_log) > 1000:
            self._event_log.pop(0)
        log_fn = logger.warning if level == "WARNING" else logger.info
        log_fn(f"[FLEET] {message}")

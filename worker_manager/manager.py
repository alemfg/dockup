"""
Worker Manager Daemon — runs on each machine.
Listens for spawn requests from the brain and manages local Docker containers.
Only handles requests not explicitly excluding this machine.
"""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import uuid
from datetime import datetime
from typing import Dict, List

from messaging.bus import MessageBus, STREAM_SPAWN
from messaging.logging import get_logger, setup_logging

logger = get_logger("worker_manager")

MY_IP    = os.getenv("MACHINE_IP",   platform.node())
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))

# Track spawned containers: { worker_id → container_id }
_containers: Dict[str, str] = {}


async def handle_spawn_request(stream: str, msg: dict) -> None:
    action = msg.get("action", "")

    if action == "SPAWN":
        avoid = msg.get("avoid_machine", "")
        if avoid and MY_IP in avoid:
            logger.debug(f"Spawn request excluded this machine ({MY_IP}), skipping.")
            return

        if len(_containers) >= MAX_WORKERS:
            logger.warning(f"At capacity ({MAX_WORKERS} workers), cannot spawn.")
            return

        worker_id = f"worker-{msg.get('exchange', 'unknown')}-{uuid.uuid4().hex[:6]}"
        pairs_raw = msg.get("pairs", [])

        # AutoSpawner sends ["ALL"] when PAIRS=ALL is configured
        if pairs_raw == ["ALL"] or pairs_raw == "ALL":
            pairs_str = "ALL"
        else:
            pairs_str = ",".join(pairs_raw)

        env_vars = {
            "WORKER_ID":       worker_id,
            "EXCHANGE":        msg.get("exchange", ""),
            "PAIRS":           pairs_str,
            "MACHINE_ID":      MY_IP,
            "REDIS_HOST":      REDIS_HOST,
            "IS_REPLACEMENT":  str(msg.get("kill_original", False)).lower(),
            "REPLACED_WORKER": msg.get("worker_id", ""),
            **{k.upper(): str(v) for k, v in msg.get("config_override", {}).items()},
        }

        container_id = await _spawn_docker(worker_id, env_vars)
        if container_id:
            _containers[worker_id] = container_id
            logger.info(f"Spawned {worker_id} → container {container_id[:12]}")

    elif action == "KILL":
        target = msg.get("worker_id", "")
        await _kill_worker(target)


async def _spawn_docker(worker_id: str, env_vars: dict) -> str:
    """Spawn a Docker container for a worker."""
    image = os.getenv("WORKER_IMAGE", "arbitrage-worker:v2")
    env_flags = []
    for k, v in env_vars.items():
        if v:
            env_flags += ["-e", f"{k}={v}"]

    cmd = [
        "docker", "run", "-d",
        "--name", worker_id,
        "--network", "arb-net",
        "--restart", "unless-stopped",
        "--memory", "256m",
        "--cpus", "0.5",
        "--read-only",
        "--tmpfs", "/tmp",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
    ] + env_flags + [image]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            logger.error(f"Docker spawn failed: {result.stderr}")
            return ""
    except Exception as exc:
        logger.error(f"Docker spawn error: {exc}")
        return ""


async def _kill_worker(worker_id: str) -> None:
    container_id = _containers.pop(worker_id, None)
    if not container_id:
        return
    try:
        subprocess.run(["docker", "stop", worker_id], timeout=10)
        subprocess.run(["docker", "rm",   worker_id], timeout=10)
        logger.info(f"Worker {worker_id} killed and removed.")
    except Exception as exc:
        logger.error(f"Error killing worker {worker_id}: {exc}")


async def run() -> None:
    setup_logging()
    logger.info(f"WorkerManager starting on {MY_IP} (max_workers={MAX_WORKERS})")

    bus = MessageBus(host=REDIS_HOST)
    await bus.connect()

    await bus.subscribe(
        streams=[STREAM_SPAWN],
        consumer_id=f"worker_manager_{MY_IP}",
        handler=handle_spawn_request,
    )


if __name__ == "__main__":
    asyncio.run(run())

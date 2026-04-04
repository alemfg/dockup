"""
Worker Manager — spawns worker containers from SPAWN stream messages.
v4.7.10: Radically simplified with verbose step-by-step logging.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import uuid
from typing import Dict

import redis.asyncio as aioredis

try:
    import docker as docker_sdk
    _DOCKER_AVAILABLE = True
except ImportError:
    _DOCKER_AVAILABLE = False

from messaging.bus import STREAM_SPAWN
from messaging.logging import get_logger, setup_logging

logger = get_logger("worker_manager")

REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
MY_IP          = os.getenv("MACHINE_IP",     platform.node())
MAX_WORKERS    = int(os.getenv("MAX_WORKERS", "50"))
WORKER_IMAGE   = os.getenv("WORKER_IMAGE",   "arbx-worker:latest")
WORKER_NETWORK = os.getenv("WORKER_NETWORK", "arb-net")
DOCKER_HOST    = os.getenv("DOCKER_HOST",    "unix:///var/run/docker.sock")

_ENV_FILE       = os.getenv("WORKER_ENV_FILE",       "/app/config/.env")
_ENV_LOCAL_FILE = os.getenv("WORKER_ENV_LOCAL_FILE",  "/app/config/.env.local")

# worker_id → container_id
_containers: Dict[str, str] = {}


# ── Env file loader ────────────────────────────────────────────────────────────

def _load_env_file(path: str) -> dict:
    result = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                v = v.split("#")[0].strip()
                result[k.strip()] = v
        logger.debug(f"Loaded {len(result)} vars from {path}")
    except FileNotFoundError:
        logger.debug(f"Env file not found (ok): {path}")
    return result


# ── Docker helpers ─────────────────────────────────────────────────────────────

def _docker_client():
    return docker_sdk.DockerClient(base_url=DOCKER_HOST)


def _sync_spawn(worker_id: str, env_list: list) -> str:
    """Synchronous Docker spawn — runs in executor."""
    client = _docker_client()
    try:
        # Remove any existing stopped container with this name first
        try:
            old = client.containers.get(worker_id)
            logger.info(f"Removing stale container {worker_id} (status={old.status})")
            old.remove(force=True)
        except Exception:
            pass  # doesn't exist — fine

        container = client.containers.run(
            WORKER_IMAGE,
            detach=True,
            name=worker_id,
            network=WORKER_NETWORK,
            environment=env_list,
            restart_policy={"Name": "unless-stopped"},
            mem_limit="256m",
            nano_cpus=int(0.5 * 1e9),
        )
        return container.id
    finally:
        client.close()


async def _spawn(worker_id: str, env_vars: dict) -> str:
    """Build env list and spawn container. Returns container ID or ''."""
    base = _load_env_file(_ENV_FILE)
    base.update(_load_env_file(_ENV_LOCAL_FILE))
    base.update({k: v for k, v in env_vars.items() if v})
    env_list = [f"{k}={v}" for k, v in base.items()]

    logger.info(f"Spawning {worker_id} | image={WORKER_IMAGE} | network={WORKER_NETWORK} | pairs={env_vars.get('PAIRS','?')[:60]}")

    try:
        cid = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _sync_spawn(worker_id, env_list)
        )
        logger.info(f"✓ Spawned {worker_id} → {cid[:12]}")
        return cid
    except Exception as exc:
        logger.error(f"✗ Spawn failed for {worker_id}: {exc}")
        return ""


# ── SPAWN message handler ──────────────────────────────────────────────────────

async def handle_spawn(msg: dict) -> None:
    logger.info(f"SPAWN received: exchange={msg.get('exchange')} worker_id={msg.get('worker_id')} pairs={str(msg.get('pairs',''))[:60]}")

    if len(_containers) >= MAX_WORKERS:
        logger.warning(f"At capacity ({MAX_WORKERS}). Cannot spawn {msg.get('worker_id')}")
        return

    worker_id = msg.get("worker_id") or f"worker-{msg.get('exchange','x')}-{uuid.uuid4().hex[:6]}"

    pairs_raw = msg.get("pairs", [])
    pairs_str = "ALL" if pairs_raw in (["ALL"], "ALL") else ",".join(str(p) for p in pairs_raw)

    env_vars = {
        "WORKER_ID":       worker_id,
        "EXCHANGE":        msg.get("exchange", ""),
        "PAIRS":           pairs_str,
        "MACHINE_ID":      MY_IP,
        "REDIS_HOST":      REDIS_HOST,
        "REDIS_PORT":      str(REDIS_PORT),
        "IS_REPLACEMENT":  "false",
        "REPLACED_WORKER": "",
    }

    cid = await _spawn(worker_id, env_vars)
    if cid:
        _containers[worker_id] = cid


# ── Main ───────────────────────────────────────────────────────────────────────

async def run() -> None:
    setup_logging()
    build_ver  = os.getenv("ARBX_BUILD_VERSION", "dev")
    build_date = os.getenv("ARBX_BUILD_DATE", "unknown")
    logger.info(f"WorkerManager starting — machine={MY_IP} max={MAX_WORKERS} [image build: {build_ver} / {build_date}]")
    logger.info(f"Redis={REDIS_HOST}:{REDIS_PORT}  Docker={DOCKER_HOST}")
    logger.info(f"Image={WORKER_IMAGE}  Network={WORKER_NETWORK}")

    # ── Verify Docker ────────────────────────────────────────────────────────
    if not _DOCKER_AVAILABLE:
        logger.error("FATAL: 'docker' package not installed. Run: pip install docker>=7.0.0")
        return

    try:
        client = _docker_client()
        info = client.info()
        client.close()
        logger.info(f"Docker OK — daemon={info.get('Name')} containers_running={info.get('ContainersRunning')}")
    except Exception as exc:
        logger.error(f"Docker connection FAILED: {exc}")
        logger.error(f"Socket: {DOCKER_HOST} — check /var/run/docker.sock permissions")
        return  # Cannot spawn anything — exit rather than loop silently

    # ── Connect to Redis ─────────────────────────────────────────────────────
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    try:
        await r.ping()
        logger.info("Redis OK")
    except Exception as exc:
        logger.error(f"Redis connection FAILED: {exc}")
        return

    # ── Ensure consumer group exists ─────────────────────────────────────────
    group      = "worker_manager"
    consumer   = f"wm_{MY_IP}"
    try:
        await r.xgroup_create(STREAM_SPAWN, group, id="$", mkstream=True)
        logger.info(f"Created consumer group '{group}' on {STREAM_SPAWN} (from id=$, only new messages)")
    except Exception:
        logger.info(f"Consumer group '{group}' already exists on {STREAM_SPAWN}")

    # Check pending/backlog
    stream_len = await r.xlen(STREAM_SPAWN)
    logger.info(f"Stream {STREAM_SPAWN} has {stream_len} total messages")

    logger.info(f"Listening as consumer '{consumer}' in group '{group}'...")

    # ── Main loop ────────────────────────────────────────────────────────────
    poll_count = 0
    while True:
        try:
            results = await r.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={STREAM_SPAWN: ">"},
                count=20,
                block=2000,
            )
            poll_count += 1

            # Log every 30 polls (~60s) so we know the loop is alive
            if poll_count % 30 == 0:
                logger.info(f"Poll #{poll_count} — tracked workers: {len(_containers)}")

            if not results:
                continue

            for _stream, messages in results:
                logger.info(f"Received {len(messages)} SPAWN message(s)")
                for msg_id, fields in messages:
                    try:
                        data = json.loads(fields.get("data", "{}"))
                        action = data.get("action", "")
                        if action == "SPAWN":
                            await handle_spawn(data)
                        elif action == "KILL":
                            logger.info(f"KILL received for {data.get('worker_id')}")
                        else:
                            logger.warning(f"Unknown action: {action}")
                        await r.xack(STREAM_SPAWN, group, msg_id)
                    except Exception as exc:
                        logger.error(f"Message handling error: {exc}", exc_info=True)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(f"Main loop error: {exc}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(run())

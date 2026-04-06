"""
Run the ArbitrageEngine v2 Worker Manager daemon.
One instance per machine. Listens for spawn/kill requests from the brain.

Environment variables:
    REDIS_HOST      Redis host (default: localhost)
    MACHINE_IP      This machine's IP or hostname
    MAX_WORKERS     Max containers to spawn on this machine (default: 5)
    WORKER_IMAGE    Docker image for workers (default: arbitrage-worker:v2)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from worker_manager.manager import run

if __name__ == "__main__":
    asyncio.run(run())

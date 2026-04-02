"""
AutoSpawner (v4.6)
==================
Reads the EXCHANGES config variable and automatically spawns one worker
per configured exchange via the worker_manager SPAWN stream — no manual
docker-compose worker blocks needed.

How it works
------------
1. On brain startup, iterates config.workers.exchanges.
2. For each exchange, reads {EXCHANGE}_PAIRS from env (or "ALL").
3. Publishes a SPAWN action to stream:spawn_requests.
4. worker_manager (a long-running container with Docker socket access)
   receives the SPAWN and creates the worker container.
5. Every WATCH_INTERVAL seconds, checks the live fleet for each configured
   exchange. If a worker is missing (never registered or went dead), a new
   SPAWN is published — self-healing.

Configuration
-------------
EXCHANGES=binance,kraken,bybit,uniswap   # which workers to auto-spawn
BINANCE_PAIRS=BTC/USDT,ETH/USDT,...      # pairs for that exchange (or ALL)
KRAKEN_PAIRS=ALL                         # fetch full market list
EXCHANGES_WATCH_INTERVAL=60              # how often to check fleet (seconds)
EXCHANGES_SPAWN_DELAY=5                  # seconds between each SPAWN on startup

The spawner will NOT re-spawn a worker if one is already healthy for that
exchange. It only acts when an exchange has zero live workers.
"""

from __future__ import annotations

import asyncio
import os
from typing import Set

from messaging.bus import MessageBus, STREAM_SPAWN
from messaging.logging import get_logger

logger = get_logger("brain.auto_spawner")

_WATCH_INTERVAL = int(os.getenv("EXCHANGES_WATCH_INTERVAL", "60"))
_SPAWN_DELAY    = float(os.getenv("EXCHANGES_SPAWN_DELAY", "5"))


class AutoSpawner:
    """
    Reads config.workers.exchanges and keeps one healthy worker alive
    per exchange by publishing SPAWN commands to the worker_manager stream.
    """

    def __init__(self, config, bus: MessageBus, fleet_monitor):
        self._config  = config
        self._bus     = bus
        self._fleet   = fleet_monitor
        self._spawned: Set[str] = set()   # exchanges we've already spawned once

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Run initial spawn sweep, then enter the watch loop."""
        exchanges = self._config.workers.exchanges
        if not exchanges:
            logger.info("AutoSpawner: no exchanges configured — skipping auto-spawn. "
                        "Set EXCHANGES=binance,kraken,... in .env to enable.")
            return

        logger.info(f"AutoSpawner: configured exchanges = {exchanges}")
        await self._spawn_missing(exchanges, initial=True)

        while True:
            await asyncio.sleep(_WATCH_INTERVAL)
            await self._spawn_missing(exchanges, initial=False)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _pairs_for(self, exchange: str) -> str:
        """Read {EXCHANGE}_PAIRS from env, defaulting to 'BTC/USDT,ETH/USDT'."""
        env_key = f"{exchange.upper()}_PAIRS"
        return os.getenv(env_key, "BTC/USDT,ETH/USDT").strip()

    def _live_exchanges(self) -> Set[str]:
        """Return the set of exchange names that have at least one healthy worker."""
        live: Set[str] = set()
        for w in self._fleet.get_all_workers():
            if not w.get("is_dead", True):
                ex = w.get("exchange", "")
                if ex:
                    live.add(ex.lower())
        return live

    async def _spawn_missing(self, exchanges: list, initial: bool) -> None:
        live = self._live_exchanges()

        for exchange in exchanges:
            ex_lower = exchange.lower()

            if ex_lower in live:
                if ex_lower not in self._spawned:
                    logger.debug(f"AutoSpawner: {exchange} already has a live worker — skipping spawn")
                    self._spawned.add(ex_lower)
                continue

            pairs_str = self._pairs_for(exchange)
            pairs_list = (
                []              # worker resolves ALL itself
                if pairs_str.upper() == "ALL"
                else [p.strip() for p in pairs_str.split(",") if p.strip()]
            )

            action = "initial spawn" if initial else "re-spawn (worker missing)"
            logger.info(
                f"AutoSpawner: {action} for {exchange} — "
                f"pairs={'ALL' if pairs_str.upper() == 'ALL' else len(pairs_list)}"
            )

            await self._bus.publish(STREAM_SPAWN, {
                "action":   "SPAWN",
                "exchange": ex_lower,
                "pairs":    pairs_list if pairs_list else ["ALL"],
                "source":   "auto_spawner",
            })

            self._spawned.add(ex_lower)

            # Brief gap between spawns to avoid overwhelming the manager
            if initial:
                await asyncio.sleep(_SPAWN_DELAY)

        if not initial:
            newly_missing = [e for e in exchanges if e.lower() not in live and e.lower() in self._spawned]
            if newly_missing:
                logger.warning(f"AutoSpawner: re-spawned missing workers for: {newly_missing}")

"""
AutoSpawner (v4.7)
==================
Reads the EXCHANGES config variable, resolves pairs for each exchange,
splits into balanced chunks if the pair count exceeds PAIRS_WORKER_SIZE,
and spawns one worker container per chunk via the worker_manager.

Example
-------
  EXCHANGES=binance,kraken
  BINANCE_PAIRS=ALL          → resolves to 340 pairs
  PAIRS_WORKER_SIZE=200      → spawns 2 workers: 170 pairs each

  KRAKEN_PAIRS=BTC/USDT,...  → 10 pairs → 1 worker (under limit)

Self-healing
------------
Every EXCHANGES_WATCH_INTERVAL seconds the spawner checks the live fleet.
For each exchange it computes the expected worker count (same split logic).
If any slot is missing it re-spawns just that slot with its pair slice.

Configuration
-------------
EXCHANGES=binance,kraken,bybit,uniswap
BINANCE_PAIRS=ALL               # or explicit comma list
PAIRS_WORKER_SIZE=200           # max pairs per single worker (default 200)
PAIRS_ALL_QUOTE_FILTER=USDT,USDC,BTC,ETH   # quote filter when PAIRS=ALL
EXCHANGES_WATCH_INTERVAL=60     # fleet check cadence (seconds)
EXCHANGES_SPAWN_DELAY=3         # gap between individual SPAWN messages
"""

from __future__ import annotations

import asyncio
import math
import os
from typing import Dict, List, Set, Tuple

from messaging.bus import MessageBus, STREAM_SPAWN
from messaging.logging import get_logger

logger = get_logger("brain.auto_spawner")

_WATCH_INTERVAL = int(os.getenv("EXCHANGES_WATCH_INTERVAL", "60"))
_SPAWN_DELAY    = float(os.getenv("EXCHANGES_SPAWN_DELAY",  "3"))

# DEX exchanges have no useful public market list via CCXT.
_DEX_DEFAULT_PAIRS: Dict[str, List[str]] = {
    "uniswap":     ["ETH/USDT", "WBTC/USDT", "ETH/USDC", "LINK/USDT", "UNI/USDT", "MATIC/USDT"],
    "sushiswap":   ["ETH/USDT", "WBTC/USDT", "ETH/USDC", "SUSHI/USDT"],
    "pancakeswap": ["BNB/USDT", "ETH/USDT",  "BTC/USDT", "CAKE/USDT"],
    "curve":       ["USDT/USDC", "USDT/DAI", "USDC/DAI"],
}


def _chunk(items: List, size: int) -> List[List]:
    """Split a list into balanced chunks each no larger than `size`."""
    if not items:
        return [[]]
    n_chunks = math.ceil(len(items) / size)
    chunk_size = math.ceil(len(items) / n_chunks)
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


async def _fetch_all_pairs(exchange: str) -> List[str]:
    """
    Resolve ALL pairs for an exchange.
    Called by the spawner (brain-side) so it knows the full list before
    splitting. DEX exchanges return a curated default; CEX exchanges call
    CCXT load_markets().
    """
    ex_lower = exchange.lower()

    if ex_lower in _DEX_DEFAULT_PAIRS:
        pairs = _DEX_DEFAULT_PAIRS[ex_lower]
        logger.info(f"[AutoSpawner] {exchange}: DEX — using curated default ({len(pairs)} pairs)")
        return pairs

    try:
        import ccxt.async_support as ccxt_async
        ex = getattr(ccxt_async, ex_lower)({"enableRateLimit": True})
        markets = await ex.load_markets()
        await ex.close()

        quote_filter_raw = os.getenv("PAIRS_ALL_QUOTE_FILTER", "USDT,USDC,BTC,ETH")
        allowed_quotes   = {q.strip().upper() for q in quote_filter_raw.split(",") if q.strip()}

        pairs = sorted([
            sym for sym, mkt in markets.items()
            if mkt.get("active", True)
            and mkt.get("type", "spot") == "spot"
            and mkt.get("quote", "").upper() in allowed_quotes
            and "/" in sym
        ])
        logger.info(f"[AutoSpawner] {exchange}: resolved {len(pairs)} pairs from load_markets()")
        return pairs or ["BTC/USDT", "ETH/USDT"]

    except Exception as exc:
        logger.error(f"[AutoSpawner] {exchange}: load_markets() failed — {exc}. Using BTC/USDT,ETH/USDT")
        return ["BTC/USDT", "ETH/USDT"]


class AutoSpawner:
    """
    Keeps the configured fleet alive: spawns workers on startup and
    re-spawns any that disappear, with automatic multi-worker splitting
    when an exchange's pair count exceeds pairs_worker_size.
    """

    def __init__(self, config, bus: MessageBus, fleet_monitor):
        self._config = config
        self._bus    = bus
        self._fleet  = fleet_monitor
        # exchange → list of pair-slices (one per expected worker)
        self._plan:   Dict[str, List[List[str]]] = {}
        self._ready:  Set[str] = set()   # exchanges fully spawned at least once

    # ── Public ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        exchanges = self._config.workers.exchanges
        if not exchanges:
            logger.info(
                "AutoSpawner: EXCHANGES not configured — auto-spawn disabled. "
                "Set EXCHANGES=binance,kraken,... in .env to enable."
            )
            return

        logger.info(f"AutoSpawner: configured exchanges = {exchanges}")

        # Build the full split plan upfront
        await self._build_plan(exchanges)

        # Initial spawn
        await self._reconcile(initial=True)

        # Watch loop
        while True:
            await asyncio.sleep(_WATCH_INTERVAL)
            await self._reconcile(initial=False)

    # ── Plan building ─────────────────────────────────────────────────────────

    async def _build_plan(self, exchanges: List[str]) -> None:
        """
        For every exchange, resolve the full pair list and split into
        balanced chunks. Stores result in self._plan.
        """
        worker_size = self._config.workers.pairs_worker_size
        for exchange in exchanges:
            ex_lower    = exchange.lower()
            pairs_raw   = os.getenv(f"{exchange.upper()}_PAIRS", "BTC/USDT,ETH/USDT").strip()

            if pairs_raw.upper() == "ALL":
                all_pairs = await _fetch_all_pairs(ex_lower)
            else:
                all_pairs = [p.strip() for p in pairs_raw.split(",") if p.strip()]

            chunks = _chunk(all_pairs, worker_size)
            self._plan[ex_lower] = chunks

            if len(chunks) == 1:
                logger.info(
                    f"[AutoSpawner] {exchange}: {len(all_pairs)} pairs → 1 worker"
                )
            else:
                logger.info(
                    f"[AutoSpawner] {exchange}: {len(all_pairs)} pairs → "
                    f"{len(chunks)} workers × ~{len(chunks[0])} pairs each "
                    f"(PAIRS_WORKER_SIZE={worker_size})"
                )

    # ── Reconciliation ────────────────────────────────────────────────────────

    def _live_slots(self) -> Dict[str, Set[int]]:
        """
        Returns {exchange: {slot_indices that have a live worker}}.
        We encode the slot in the worker_id as  worker-{exchange}-slot{N}-*.
        Workers spawned before this version (no slot suffix) are counted as slot 0.
        """
        slots: Dict[str, Set[int]] = {}
        for w in self._fleet.get_all_workers():
            if w.get("is_dead", True):
                continue
            ex  = w.get("exchange", "").lower()
            wid = w.get("worker_id", "")
            if not ex:
                continue
            # Parse slot index from worker_id suffix
            slot = 0
            if f"-slot" in wid:
                try:
                    slot = int(wid.split("-slot")[1].split("-")[0])
                except (ValueError, IndexError):
                    slot = 0
            slots.setdefault(ex, set()).add(slot)
        return slots

    async def _reconcile(self, initial: bool) -> None:
        """Spawn any missing workers according to the current plan."""
        live_slots = self._live_slots()
        verb       = "initial spawn" if initial else "re-spawn"

        for ex_lower, chunks in self._plan.items():
            live = live_slots.get(ex_lower, set())
            for slot_idx, pairs in enumerate(chunks):
                if slot_idx in live:
                    continue   # this slot is healthy — nothing to do

                worker_id = f"worker-{ex_lower}-slot{slot_idx}-auto"
                logger.info(
                    f"[AutoSpawner] {verb}: {ex_lower} slot {slot_idx}/{len(chunks)-1} "
                    f"— {len(pairs)} pairs → worker_id={worker_id}"
                )

                await self._bus.publish(STREAM_SPAWN, {
                    "action":    "SPAWN",
                    "exchange":  ex_lower,
                    "pairs":     pairs,
                    "worker_id": worker_id,
                    "source":    "auto_spawner",
                    "slot":      slot_idx,
                })

                if initial:
                    await asyncio.sleep(_SPAWN_DELAY)

            self._ready.add(ex_lower)

        if not initial:
            missing = [
                f"{ex}[slot {s}]"
                for ex, chunks in self._plan.items()
                for s in range(len(chunks))
                if s not in live_slots.get(ex, set())
            ]
            if missing:
                logger.warning(f"[AutoSpawner] re-spawned missing slots: {missing}")

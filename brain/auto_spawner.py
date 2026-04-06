"""
AutoSpawner (v6.4)
==================
Reads the EXCHANGES config variable, resolves pairs for each exchange,
splits into balanced chunks if the pair count exceeds PAIRS_WORKER_SIZE,
and spawns one worker container per chunk via the worker_manager.

Rate-limit-aware spawning (v6.4)
---------------------------------
Before spawning workers for an exchange the spawner calculates the maximum
safe worker count using the exchange's published request-per-minute limit:

    max_workers = floor(rpm_limit / (pairs_per_worker * ticks_per_min))

If the pair-split would produce more workers than the IP budget allows,
the spawner caps the count and merges pair slices accordingly. This prevents
IP bans *before* they happen — no 429 needed to trigger the cap.

Per-exchange RPM limits are defined in worker/rate_limit.py and can be
overridden via env: BINANCE_RATE_LIMIT_RPM=400

Example
-------
  EXCHANGES=binance,kraken
  BINANCE_PAIRS=ALL          → resolves to 340 pairs
  PAIRS_WORKER_SIZE=200      → naive plan: 2 workers × 170 pairs
  BINANCE rpm budget (600)   → at 2000ms tick: max_workers=3 → 2 ≤ 3 → OK

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
BINANCE_RATE_LIMIT_RPM=600      # override default rpm budget for binance
"""

from __future__ import annotations

import asyncio
import math
import os
from typing import Dict, List, Set, Tuple

from messaging.bus import MessageBus, STREAM_SPAWN
from messaging.logging import get_logger
from worker.rate_limit import max_workers_for_exchange, ccxt_exchange_id

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

    v6.4: exchange name is normalised to CCXT id before the getattr() call
    so user-facing names like "gateio" map correctly to the CCXT "gate" class.
    """
    ex_lower  = exchange.lower()
    ccxt_id   = ccxt_exchange_id(ex_lower)   # e.g. "gateio" → "gate"

    if ex_lower in _DEX_DEFAULT_PAIRS:
        pairs = _DEX_DEFAULT_PAIRS[ex_lower]
        logger.info(f"[AutoSpawner] {exchange}: DEX — using curated default ({len(pairs)} pairs)")
        return pairs

    try:
        import ccxt.async_support as ccxt_async
        if not hasattr(ccxt_async, ccxt_id):
            logger.error(
                f"[AutoSpawner] {exchange}: CCXT has no exchange '{ccxt_id}'. "
                f"Check spelling. Valid names: {sorted(ccxt_async.exchanges)[:10]}…"
            )
            return ["BTC/USDT", "ETH/USDT"]

        ex = getattr(ccxt_async, ccxt_id)({"enableRateLimit": True})
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
        logger.info(f"[AutoSpawner] {exchange} (ccxt={ccxt_id}): resolved {len(pairs)} pairs from load_markets()")
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

    def __init__(self, config, bus: MessageBus, fleet_monitor, persistence=None):
        self._config      = config
        self._bus         = bus
        self._fleet       = fleet_monitor
        self._persistence = persistence
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

        # Give the worker_manager time to connect to Redis and start reading
        # from the SPAWN stream before we publish anything. Without this delay
        # SPAWN messages could be written before worker_manager subscribes.
        startup_wait = float(os.getenv("EXCHANGES_STARTUP_WAIT", "5"))
        logger.info(f"AutoSpawner: waiting {startup_wait}s for worker_manager to be ready...")
        await asyncio.sleep(startup_wait)

        # Build the full split plan upfront (no network calls — ALL is a sentinel)
        await self._build_plan(exchanges)
        logger.info(f"AutoSpawner: plan built — {sum(len(c) for c in self._plan.values())} worker slots across {len(self._plan)} exchanges")

        # Initial spawn
        logger.info("AutoSpawner: publishing initial SPAWN messages...")
        await self._reconcile(initial=True)
        logger.info(f"AutoSpawner: initial spawn complete — watch loop every {_WATCH_INTERVAL}s")

        # Watch loop — re-spawns any missing workers every interval
        while True:
            await asyncio.sleep(_WATCH_INTERVAL)
            await self._reconcile(initial=False)

    # ── Plan building ─────────────────────────────────────────────────────────

    async def _build_plan(self, exchanges: List[str]) -> None:
        """
        Build the spawn plan for each exchange.

        If PAIRS=ALL: resolves the full pair list from CCXT, then splits by
        pairs_worker_size (same as explicit list path — consistent behaviour).

        If PAIRS=explicit list: splits into balanced chunks of pairs_worker_size.

        v6.4 Rate-limit cap: after the pair-split the number of workers is
        additionally capped by max_workers_for_exchange().  If the cap reduces
        the worker count the pair slices are merged so all pairs are still covered
        — just distributed across fewer workers with more pairs each.
        """
        worker_size  = self._config.workers.pairs_worker_size
        tick_ms      = int(os.getenv("TICK_INTERVAL_MS", "2000"))

        for exchange in exchanges:
            ex_lower  = exchange.lower()
            pairs_raw = os.getenv(f"{exchange.upper()}_PAIRS", "BTC/USDT,ETH/USDT").strip()

            if pairs_raw.upper() == "ALL":
                logger.info(f"[AutoSpawner] {exchange}: PAIRS=ALL — resolving market list...")
                all_pairs = await _fetch_all_pairs(exchange)
            else:
                all_pairs = [p.strip() for p in pairs_raw.split(",") if p.strip()]

            # Step 1 — naive pair-split by pairs_worker_size
            chunks = _chunk(all_pairs, worker_size)

            # Step 2 — rate-limit cap: how many workers can this IP sustain?
            pairs_per_worker = len(chunks[0]) if chunks else worker_size
            max_w = max_workers_for_exchange(
                exchange=ex_lower,
                pairs_per_worker=pairs_per_worker,
                tick_interval_ms=tick_ms,
            )

            if len(chunks) > max_w:
                # Merge slices down to max_w chunks so we stay within the budget.
                # Re-chunk the full pair list into exactly max_w balanced slices.
                flat   = [p for chunk in chunks for p in chunk]
                chunks = _chunk(flat, math.ceil(len(flat) / max_w))
                logger.warning(
                    f"[AutoSpawner] {exchange}: rate-limit cap applied — "
                    f"reduced from {len(_chunk(all_pairs, worker_size))} workers → {len(chunks)} "
                    f"(rpm_budget={max_w}, tick={tick_ms}ms). "
                    f"Override with {exchange.upper()}_RATE_LIMIT_RPM env var."
                )
            else:
                if len(chunks) == 1:
                    logger.info(f"[AutoSpawner] {exchange}: {len(all_pairs)} pairs → 1 worker")
                else:
                    logger.info(
                        f"[AutoSpawner] {exchange}: {len(all_pairs)} pairs → "
                        f"{len(chunks)} workers × ~{len(chunks[0])} pairs each "
                        f"(rate budget: max {max_w} workers)"
                    )

            self._plan[ex_lower] = chunks

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

                # ["ALL"] is a sentinel meaning the worker resolves its own pairs
                is_all = pairs == ["ALL"]
                pairs_to_send = ["ALL"] if is_all else pairs

                logger.info(
                    f"[AutoSpawner] {verb}: {ex_lower} slot {slot_idx}/{len(chunks)-1} "
                    f"— {'ALL pairs' if is_all else f'{len(pairs)} pairs'} → {worker_id}"
                )

                # Fetch API credentials from Vault DB if available
                api_key = api_secret = passphrase = ""
                if self._persistence and self._persistence.config_store:
                    try:
                        creds = await self._persistence.config_store.get_api_key(ex_lower)
                        if creds:
                            api_key    = creds.get("api_key", "")
                            api_secret = creds.get("api_secret", "")
                            passphrase = creds.get("passphrase", "")
                    except Exception:
                        pass

                await self._bus.publish(STREAM_SPAWN, {
                    "action":    "SPAWN",
                    "exchange":  ex_lower,
                    "pairs":     pairs_to_send,
                    "worker_id": worker_id,
                    "source":    "auto_spawner",
                    "slot":      slot_idx,
                    # Vault credentials — worker_manager injects into container env
                    "api_key":    api_key,
                    "api_secret": api_secret,
                    "passphrase": passphrase,
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

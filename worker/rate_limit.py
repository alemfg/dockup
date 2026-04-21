"""
RateLimitGuard (v6.4)
=====================
Per-exchange rate limit enforcement for workers.

Strategy
--------
Three-layer approach applied in order:

  1. Pre-spawn cap (AutoSpawner)
     Brain calculates max_workers_for_exchange = floor(rate_limit / req_per_worker_per_min)
     and never spawns more workers than the budget allows. This is the primary gate.

  2. In-worker token bucket (this module)
     Each worker holds a token bucket seeded from EXCHANGE_RATE_LIMIT_RPM.
     Every fetch_ticker() / fetch_ohlcv() etc. consumes one token.
     When tokens run out the worker sleeps until the next refill window
     instead of issuing a request that will 429.

  3. Reactive back-off (this module)
     When a 429 is received despite the bucket (burst / shared IP), the guard
     enters exponential back-off: initial_sleep → doubles each retry, capped at
     max_backoff_s. The interval is halved on every successful request until
     it returns to 0.

Per-exchange rate limits (requests/minute, conservative safe values)
---------------------------------------------------------------------
Exchange      Official limit     We use (conservative, shared-IP margin)
--------      --------------     ----------------------------------------
binance       1200 weight/min    600   (weight=1 per ticker; leave 50% margin)
kraken        60  req/min        40
bybit         120 req/min        80
coinbase      30  req/min        20
kucoin        1800 req/min       900
okx           300 req/min        200
huobi         100 req/min        60

Users can override any of these via env var, e.g.:
  BINANCE_RATE_LIMIT_RPM=400
  KRAKEN_RATE_LIMIT_RPM=30

If an exchange is not in the table, a safe default of 60 rpm is used.

Usage
-----
  guard = RateLimitGuard(exchange="binance")
  async with guard.request():   # sleeps if budget exhausted or in back-off
      price = await ccxt_client.fetch_ticker(pair)
  # On 429:
  await guard.on_rate_limited()
  # On success:
  guard.on_success()
"""
from __future__ import annotations

import asyncio
import math
import os
import time
from typing import Optional

from messaging.logging import get_logger

logger = get_logger("worker.rate_limit")

# ── CCXT exchange name normalisation ─────────────────────────────────────────
# Some user-facing names differ from the CCXT exchange ID.
# Keys = what users put in EXCHANGES=; values = CCXT internal id.
# Referenced by auto_spawner._ccxt_name() before calling load_markets().
EXCHANGE_CCXT_NAME: dict[str, str] = {
    "gateio":   "gate",    # CCXT id is "gate", not "gateio"
    "huobi":    "htx",     # Huobi rebranded to HTX; CCXT uses "htx"
    "whitebit": "whitebit",# CCXT id matches
}

def ccxt_exchange_id(exchange: str) -> str:
    """Return the canonical CCXT exchange ID for a user-supplied name."""
    return EXCHANGE_CCXT_NAME.get(exchange.lower(), exchange.lower())


# ── Default RPM table ─────────────────────────────────────────────────────────
# Conservative values: ~50% of the published limit to leave room for other
# processes on the same IP (browser, other workers, monitoring).
_DEFAULT_RPM: dict[str, int] = {
    "binance":    600,
    "kraken":     40,
    "bybit":      80,
    "coinbase":   20,
    "kucoin":     900,
    "okx":        200,
    "huobi":      60,
    "htx":        60,     # Huobi rebranded
    "gate":       100,
    "gateio":     100,    # alias — same budget as "gate"
    "bitfinex":   60,
    "bitstamp":   30,
    "gemini":     30,
    "mexc":       120,
    "bitget":     120,
    "phemex":     100,
    "lbank":      60,
    "bitmart":    60,
    "whitebit":   120,    # WhiteBIT: ~300 rpm published, use 120 conservatively
}
_FALLBACK_RPM = 60   # safe default for unknown exchanges


def _rpm_for(exchange: str) -> int:
    """Return the effective RPM limit for this exchange (env override wins).
    Accepts both user-facing names (gateio) and CCXT ids (gate).
    """
    env_key = f"{exchange.upper()}_RATE_LIMIT_RPM"
    env_val = os.getenv(env_key, "")
    if env_val.strip().isdigit():
        return int(env_val.strip())
    ex = exchange.lower()
    return _DEFAULT_RPM.get(ex, _DEFAULT_RPM.get(ccxt_exchange_id(ex), _FALLBACK_RPM))


def max_workers_for_exchange(
    exchange: str,
    pairs_per_worker: int,
    tick_interval_ms: int = 2000,
) -> int:
    """
    Calculate the maximum safe number of workers for an exchange given
    a tick interval and number of pairs per worker.

    Each worker issues `pairs_per_worker` requests every `tick_interval_ms`
    milliseconds.  We must not exceed `rpm` total requests/minute across all
    workers on this IP.

        req_per_worker_per_min = pairs_per_worker * (60_000 / tick_interval_ms)
        max_workers = floor(rpm / req_per_worker_per_min)

    Always returns at least 1.
    """
    rpm = _rpm_for(exchange)
    if pairs_per_worker <= 0 or tick_interval_ms <= 0:
        return 1
    req_per_worker_per_min = pairs_per_worker * (60_000 / tick_interval_ms)
    if req_per_worker_per_min <= 0:
        return 1
    result = math.floor(rpm / req_per_worker_per_min)
    return max(1, result)


class RateLimitGuard:
    """
    Token-bucket + exponential back-off rate limiter for a single worker.

    Thread/coroutine-safe via asyncio.Lock.
    """

    # Back-off parameters
    _INITIAL_BACKOFF_S  = 5.0    # first sleep after a 429
    _MAX_BACKOFF_S      = 120.0  # ceiling on back-off sleep
    _BACKOFF_MULTIPLIER = 2.0    # doubles each consecutive 429
    _RECOVERY_DIVISOR   = 2.0    # halves after each success

    def __init__(self, exchange: str, tick_interval_ms: int = 2000):
        self.exchange         = exchange.lower()
        self._tick_ms         = tick_interval_ms
        self._rpm             = _rpm_for(self.exchange)

        # Token bucket — refilled every minute
        self._tokens          = float(self._rpm)
        self._bucket_start    = time.monotonic()
        self._lock            = asyncio.Lock()

        # Back-off state
        self._backoff_s       = 0.0          # current extra sleep per request
        self._consecutive_429 = 0

        # Diagnostics
        self.total_requests   = 0
        self.total_throttled  = 0
        self.total_429s       = 0
        self._last_429_at: Optional[float] = None

        logger.info(
            f"[RateLimit] {exchange}: {self._rpm} rpm limit initialised "
            f"(env override: {os.getenv(exchange.upper() + '_RATE_LIMIT_RPM', 'none')})"
        )

    def update_tick_interval(self, tick_interval_ms: int) -> None:
        """Called when the brain throttles this worker's tick interval."""
        self._tick_ms = tick_interval_ms

    # ── Public API ─────────────────────────────────────────────────────────────

    async def acquire(self) -> None:
        """
        Block until a request token is available.
        Call this before every exchange API request.
        """
        async with self._lock:
            self._refill()

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self.total_requests += 1
            else:
                # Bucket empty — sleep until refill
                sleep_s = self._seconds_until_refill()
                self.total_throttled += 1
                logger.debug(
                    f"[RateLimit] {self.exchange}: bucket empty "
                    f"(tokens={self._tokens:.1f}, sleeping {sleep_s:.1f}s)"
                )
                await asyncio.sleep(sleep_s)
                self._refill()
                self._tokens = max(0.0, self._tokens - 1.0)
                self.total_requests += 1

            # Apply back-off delay (outside bucket logic)
            if self._backoff_s > 0:
                await asyncio.sleep(self._backoff_s)

    async def on_rate_limited(self) -> None:
        """
        Call this when a 429 / rate-limit error is received.
        Enters/deepens exponential back-off.
        """
        async with self._lock:
            self.total_429s += 1
            self._last_429_at = time.monotonic()
            self._consecutive_429 += 1

            if self._backoff_s == 0.0:
                self._backoff_s = self._INITIAL_BACKOFF_S
            else:
                self._backoff_s = min(
                    self._backoff_s * self._BACKOFF_MULTIPLIER,
                    self._MAX_BACKOFF_S,
                )

            # Also drain the token bucket so we stop making new requests
            self._tokens = 0.0

        logger.warning(
            f"[RateLimit] {self.exchange}: 429 received "
            f"(#{self._consecutive_429}), back-off → {self._backoff_s:.1f}s"
        )

    def on_success(self) -> None:
        """
        Call this after every successful request.
        Gradually recovers the back-off.
        """
        if self._backoff_s > 0:
            old = self._backoff_s
            self._backoff_s = max(0.0, self._backoff_s / self._RECOVERY_DIVISOR)
            self._consecutive_429 = max(0, self._consecutive_429 - 1)
            if self._backoff_s == 0.0:
                logger.info(f"[RateLimit] {self.exchange}: back-off cleared (was {old:.1f}s)")

    # ── Diagnostics ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "exchange":        self.exchange,
            "rpm_limit":       self._rpm,
            "tokens_available": round(self._tokens, 1),
            "backoff_s":       round(self._backoff_s, 1),
            "consecutive_429s": self._consecutive_429,
            "total_requests":  self.total_requests,
            "total_throttled": self.total_throttled,
            "total_429s":      self.total_429s,
            "last_429_at":     self._last_429_at,
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _refill(self) -> None:
        """Top up the token bucket proportionally to elapsed time."""
        now     = time.monotonic()
        elapsed = now - self._bucket_start
        if elapsed >= 60.0:
            # Full minute elapsed — reset
            self._tokens      = float(self._rpm)
            self._bucket_start = now
        else:
            # Partial refill proportional to elapsed time
            added          = elapsed / 60.0 * self._rpm
            self._tokens   = min(float(self._rpm), self._tokens + added)
            self._bucket_start = now

    def _seconds_until_refill(self) -> float:
        """Estimate seconds until at least 1 token is available."""
        if self._rpm <= 0:
            return 1.0
        # Time for 1 token to accumulate = 60 / rpm
        return max(0.1, 60.0 / self._rpm)

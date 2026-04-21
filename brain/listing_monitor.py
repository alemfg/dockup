"""
Listing Monitor (v6.8)
======================
Tracks upcoming and recent exchange listings to detect arbitrage opportunities.

Two data sources:
  1. CoinGecko "recently added" API  — free, no key needed
  2. Manual watchlist              — user adds tokens they're tracking

For each tracked token the monitor:
  - Checks current price on all exchanges where workers are running
  - Computes cross-exchange spread vs the "reference" exchange
  - Alerts when spread exceeds alert_threshold_pct
  - Logs opportunity to DB for history

Listing premiums are typically largest in the first 24–72 hours after
a major exchange listing (Binance, Coinbase, etc.).

Architecture:
  - Runs as an async loop inside the brain (no separate process)
  - Reads price data from MarketState (no extra exchange calls)
  - Publishes alerts via AlertSender
  - Exposes data via /api/listings routes
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import aiohttp

from messaging.logging import get_logger

logger = get_logger("brain.listing_monitor")

# ── Constants ──────────────────────────────────────────────────────────────────

_COINGECKO_NEW_URL = "https://api.coingecko.com/api/v3/coins/list/new"
_POLL_INTERVAL_S   = int(os.getenv("LISTING_POLL_INTERVAL_S", "300"))   # 5 min
_ALERT_THRESHOLD   = float(os.getenv("LISTING_ALERT_THRESHOLD_PCT", "5.0"))
_MAX_HISTORY       = 200


class ListingOpportunity:
    """A detected cross-exchange premium on a newly listed or watched token."""
    def __init__(
        self,
        symbol:      str,
        name:        str,
        base_ex:     str,    # exchange with lower price (buy here)
        premium_ex:  str,    # exchange with higher price (sell here)
        base_price:  float,
        premium_price: float,
        spread_pct:  float,
        detected_at: str,
        listing_age_hours: Optional[float] = None,
    ):
        self.symbol           = symbol
        self.name             = name
        self.base_ex          = base_ex
        self.premium_ex       = premium_ex
        self.base_price       = base_price
        self.premium_price    = premium_price
        self.spread_pct       = spread_pct
        self.detected_at      = detected_at
        self.listing_age_hours = listing_age_hours

    def to_dict(self) -> dict:
        return {
            "symbol":            self.symbol,
            "name":              self.name,
            "base_ex":           self.base_ex,
            "premium_ex":        self.premium_ex,
            "base_price":        self.base_price,
            "premium_price":     self.premium_price,
            "spread_pct":        round(self.spread_pct, 2),
            "detected_at":       self.detected_at,
            "listing_age_hours": round(self.listing_age_hours, 1) if self.listing_age_hours else None,
        }


class ListingMonitor:
    """
    Monitors exchange listings for cross-exchange premium opportunities.
    Runs inside the brain process as an asyncio task.
    """

    def __init__(self, market_state, config, alert_sender=None):
        self._ms           = market_state
        self._cfg          = config
        self._alert        = alert_sender

        # Watchlist: symbol → {name, added_at, source, reference_exchange, notes}
        self._watchlist: Dict[str, dict] = {}

        # Recently detected opportunities (ring buffer)
        self._opportunities: List[dict] = []

        # CoinGecko new listings cache
        self._cg_listings:  List[dict] = []
        self._cg_fetched_at: float = 0

        # Stats
        self._total_scans      = 0
        self._total_alerts_sent = 0
        self._last_scan_at: Optional[float] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_to_watchlist(
        self,
        symbol:             str,
        name:               str = "",
        source:             str = "manual",
        reference_exchange: str = "",
        notes:              str = "",
        listing_date:       Optional[str] = None,
    ) -> None:
        """Add a token to the watchlist."""
        self._watchlist[symbol.upper()] = {
            "symbol":             symbol.upper(),
            "name":               name or symbol,
            "source":             source,
            "reference_exchange": reference_exchange or "binance",
            "notes":              notes,
            "listing_date":       listing_date,
            "added_at":           datetime.now(timezone.utc).isoformat(),
        }
        logger.info(f"[Listings] Added {symbol} to watchlist (source={source})")

    def remove_from_watchlist(self, symbol: str) -> bool:
        return self._watchlist.pop(symbol.upper(), None) is not None

    def get_watchlist(self) -> List[dict]:
        return list(self._watchlist.values())

    def get_opportunities(self, limit: int = 50) -> List[dict]:
        return list(reversed(self._opportunities))[:limit]

    def get_cg_listings(self, limit: int = 30) -> List[dict]:
        return self._cg_listings[:limit]

    def status(self) -> dict:
        return {
            "watchlist_count":    len(self._watchlist),
            "opportunities_seen": len(self._opportunities),
            "total_scans":        self._total_scans,
            "alerts_sent":        self._total_alerts_sent,
            "last_scan_at":       self._last_scan_at,
            "poll_interval_s":    _POLL_INTERVAL_S,
            "alert_threshold_pct": _ALERT_THRESHOLD,
            "cg_listings_count":  len(self._cg_listings),
            "cg_fetched_at":      self._cg_fetched_at or None,
        }

    # ── Main loop ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info(f"[Listings] Monitor started — poll={_POLL_INTERVAL_S}s threshold={_ALERT_THRESHOLD}%")
        while True:
            try:
                await self._scan_cycle()
            except Exception as exc:
                logger.error(f"[Listings] Scan error: {exc}")
            await asyncio.sleep(_POLL_INTERVAL_S)

    # ── Scan cycle ─────────────────────────────────────────────────────────────

    async def _scan_cycle(self) -> None:
        self._total_scans += 1
        self._last_scan_at = time.time()

        # Refresh CoinGecko new listings every 30 minutes
        if time.time() - self._cg_fetched_at > 1800:
            await self._fetch_cg_listings()

        # Auto-add CoinGecko new listings to watchlist
        self._sync_cg_to_watchlist()

        # Scan all watched symbols against live MarketState prices
        await self._scan_watchlist()

    async def _fetch_cg_listings(self) -> None:
        """Fetch recently added coins from CoinGecko (free tier, no key)."""
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.get(_COINGECKO_NEW_URL) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._cg_listings = data[:50] if isinstance(data, list) else []
                        self._cg_fetched_at = time.time()
                        logger.info(f"[Listings] CoinGecko: {len(self._cg_listings)} new listings fetched")
                    else:
                        logger.warning(f"[Listings] CoinGecko returned {resp.status}")
        except Exception as exc:
            logger.warning(f"[Listings] CoinGecko fetch failed: {exc}")

    def _sync_cg_to_watchlist(self) -> None:
        """Auto-add CoinGecko new listings that are on tracked exchanges."""
        if not self._cg_listings:
            return
        active_pairs = {p.split("/")[0].upper() for p in self._ms.get_all_pairs()}
        for coin in self._cg_listings:
            sym = coin.get("symbol", "").upper()
            if not sym:
                continue
            # Only auto-add if we're already seeing this on at least one exchange
            if sym in active_pairs and sym not in self._watchlist:
                self.add_to_watchlist(
                    symbol=sym,
                    name=coin.get("name", sym),
                    source="coingecko_auto",
                    notes=f"Auto-detected on CoinGecko new listings. ID: {coin.get('id','')}",
                    listing_date=coin.get("activated_at"),
                )

    async def _scan_watchlist(self) -> None:
        """Check each watched symbol for cross-exchange price premiums."""
        if not self._watchlist:
            return

        now = datetime.now(timezone.utc).isoformat()

        for sym, info in list(self._watchlist.items()):
            pair = f"{sym}/USDT"
            prices = self._ms.get_prices_for_pair(pair)

            # Need prices on at least 2 exchanges to compute a spread
            if len(prices) < 2:
                continue

            entries  = sorted(prices.items(), key=lambda x: x[1])
            base_ex, base_price    = entries[0]   # lowest price (buy here)
            prem_ex, prem_price    = entries[-1]  # highest price (sell here)

            if base_price <= 0:
                continue

            spread_pct = (prem_price - base_price) / base_price * 100

            if spread_pct < _ALERT_THRESHOLD:
                continue

            # Compute listing age if we have a date
            age_hours = None
            ld = info.get("listing_date")
            if ld:
                try:
                    listed = datetime.fromisoformat(ld.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - listed).total_seconds() / 3600
                except Exception:
                    pass

            opp = ListingOpportunity(
                symbol=sym, name=info.get("name", sym),
                base_ex=base_ex, premium_ex=prem_ex,
                base_price=base_price, premium_price=prem_price,
                spread_pct=spread_pct, detected_at=now,
                listing_age_hours=age_hours,
            ).to_dict()
            opp["all_prices"]    = prices
            opp["source"]        = info.get("source", "manual")
            opp["listing_date"]  = info.get("listing_date")
            opp["notes"]         = info.get("notes", "")
            opp["capital_for_100_profit"] = (
                round(100 / (spread_pct / 100)) if spread_pct > 0.01 else None
            )

            self._opportunities.append(opp)
            if len(self._opportunities) > _MAX_HISTORY:
                self._opportunities.pop(0)

            logger.info(
                f"[Listings] 💰 {sym}: {spread_pct:.1f}% spread "
                f"BUY {base_ex}@{base_price:.6g} SELL {prem_ex}@{prem_price:.6g}"
                + (f" (listed {age_hours:.0f}h ago)" if age_hours else "")
            )

            # Fire alert
            if self._alert:
                try:
                    await self._alert.send(
                        event_type="opportunity",
                        title=f"Listing Premium — {sym}/USDT {spread_pct:.1f}%",
                        message=(
                            f"BUY on {base_ex} @ {base_price:.6g}\n"
                            f"SELL on {prem_ex} @ {prem_price:.6g}\n"
                            f"Spread: {spread_pct:.2f}%"
                            + (f"\nListed {age_hours:.0f}h ago" if age_hours else "")
                        ),
                        priority="high",
                        tags=["listing", "opportunity", sym.lower()],
                    )
                    self._total_alerts_sent += 1
                except Exception as exc:
                    logger.warning(f"[Listings] Alert send failed: {exc}")

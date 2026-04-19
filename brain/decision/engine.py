"""
Decision Engine (v3.3)
Reads analysis signals and graph arbitrage paths, applies configurable
rules, checks the risk manager, and emits OrderCommands to the bus.

Priority order per signal:
  1. TradingMode gate     — DISABLED → drop
  2. Exchange enabled     — per-exchange toggle
  3. Risk manager         — circuit breakers
  4. Strategy rules       — min score, min RR, cooldown, etc.
  5. Emit OrderCommand    — SIMULATE logs it, LIVE sends it
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from uuid import uuid4

from config.loader import AppConfig, TradingMode
from messaging.bus import MessageBus
from messaging.logging import get_logger
from messaging.models import (
    OrderCommand, OrderSide, OrderType, SignalSource,
    CRSignal, MarketSignal,
)
from storage.market_state import MarketState

logger = get_logger("brain.decision.engine")


class DecisionEngine:
    """
    Central decision engine — the bridge between signals and orders.
    Runs as an async loop, reading from context engine and graph arbitrage.
    """

    def __init__(
        self,
        config:       AppConfig,
        bus:          MessageBus,
        market_state: MarketState,
        risk_manager: "RiskManager",   # type: ignore — imported at runtime
        alert_sender=None,             # optional — injected by brain
    ):
        self._cfg          = config
        self._bus          = bus
        self._market       = market_state
        self._risk         = risk_manager
        self._alert        = alert_sender
        self._dcfg         = config.decision
        self._running      = False

        # Cooldown tracker: {exchange:pair → last_order_time}
        self._last_order:  Dict[str, datetime] = {}
        # Simulated order log (cleared on restart, persisted to DB in production)
        self._order_log:   List[dict] = []

    # ─── Public API ──────────────────────────────────────────────────────────

    async def on_cr_signal(self, signal_dict: dict) -> Optional[OrderCommand]:
        """Called by subscriber when a CR 9AM setup signal arrives."""
        if not self._dcfg.enabled:
            return None

        mode = self._cfg.trading.mode
        if mode == TradingMode.DISABLED:
            return None

        exchange = signal_dict.get("exchange", "")
        pair     = signal_dict.get("pair", "")

        if not self._exchange_enabled(exchange):
            logger.debug(f"[DECISION] {exchange} not enabled for trading — skipping CR signal")
            return None

        # Apply CR-specific rules
        score = signal_dict.get("quality", {}).get("score", 0.0)
        if score < self._dcfg.cr_min_score:
            logger.debug(f"[DECISION] CR signal for {pair} score {score:.2f} < min {self._dcfg.cr_min_score}")
            return None

        targets   = signal_dict.get("targets", {})
        entry     = signal_dict.get("entry", {}).get("price", 0.0)
        sl        = targets.get("stop_loss", 0.0)
        tp1       = targets.get("tp1", 0.0)
        tp2       = targets.get("tp2", 0.0)
        rr        = targets.get("rr_tp1", 0.0)
        direction = signal_dict.get("direction", "long")
        bos       = signal_dict.get("quality", {}).get("bos_confirmed", False)
        fvg       = signal_dict.get("entry", {}).get("fvg") is not None

        if rr < self._dcfg.cr_min_rr:
            logger.debug(f"[DECISION] CR {pair} RR {rr:.2f} < min {self._dcfg.cr_min_rr}")
            return None

        if self._dcfg.cr_require_bos and not bos:
            logger.debug(f"[DECISION] CR {pair} BOS not confirmed — skipping")
            return None

        if self._dcfg.cr_require_fvg and not fvg:
            logger.debug(f"[DECISION] CR {pair} FVG not present — skipping")
            return None

        if not self._check_cooldown(exchange, pair):
            return None

        volume    = self._dcfg.max_capital_per_trade / max(entry, 1)
        confidence = signal_dict.get("quality", {}).get("confidence", "LOW")

        cmd = OrderCommand(
            id             = str(uuid4()),
            exchange       = exchange,
            pair           = pair,
            side           = OrderSide.BUY if direction == "long" else OrderSide.SELL,
            order_type     = OrderType.LIMIT,
            price          = entry,
            volume         = round(volume, 6),
            capital_usd    = self._dcfg.max_capital_per_trade,
            stop_loss      = sl,
            take_profit_1  = tp1,
            take_profit_2  = tp2,
            tp1_pct        = self._dcfg.cr_tp1_close_pct,
            source         = SignalSource.CR_9AM,
            signal_score   = score,
            confidence     = confidence,
            trading_mode   = mode.value,
            dry_run        = (mode != TradingMode.LIVE),
            expires_at     = datetime.now(timezone.utc) + timedelta(seconds=self._dcfg.order_ttl_seconds),
            notes          = f"CR 9AM setup | score={score:.2f} | RR={rr:.2f}",
        )

        return await self._process_order(cmd)

    async def on_graph_path(self, path_dict: dict) -> Optional[OrderCommand]:
        """Called when a profitable graph arbitrage path is found."""
        if not self._dcfg.enabled:
            return None

        mode = self._cfg.trading.mode
        if mode == TradingMode.DISABLED:
            return None

        profit_pct = path_dict.get("net_profit_pct", 0.0)
        if profit_pct < self._dcfg.graph_min_profit_pct:
            return None

        # Check age — graph paths go stale fast
        ts_str = path_dict.get("timestamp")
        if ts_str:
            try:
                ts  = datetime.fromisoformat(ts_str)
                age_ms = (datetime.now(timezone.utc) - ts).total_seconds() * 1000
                if age_ms > self._dcfg.graph_max_age_ms:
                    logger.debug(f"[DECISION] Graph path too old ({age_ms:.0f}ms) — discarding")
                    return None
            except Exception:
                pass

        edges     = path_dict.get("edges", [])
        if not edges:
            return None

        # Use first edge for exchange/pair
        first     = edges[0]
        exchange  = first.get("exchange", "")
        pair      = f"{first.get('from_asset','')}/{first.get('to_asset','')}"

        if not self._exchange_enabled(exchange):
            return None

        if not self._check_cooldown(exchange, pair):
            return None

        capital = self._dcfg.max_capital_per_trade
        volume  = path_dict.get("volume", capital / max(first.get("rate", 1), 1))

        cmd = OrderCommand(
            id           = str(uuid4()),
            exchange     = exchange,
            pair         = pair,
            side         = OrderSide.BUY,
            order_type   = OrderType.MARKET,
            price        = first.get("rate", 0.0),
            volume       = round(volume, 6),
            capital_usd  = capital,
            source       = SignalSource.GRAPH_ARB,
            signal_score = profit_pct / 100,
            confidence   = "HIGH" if profit_pct > 0.5 else "MEDIUM",
            trading_mode = mode.value,
            dry_run      = (mode != TradingMode.LIVE),
            expires_at   = datetime.now(timezone.utc) + timedelta(seconds=self._dcfg.order_ttl_seconds),
            notes        = f"Graph arb | path={path_dict.get('path', path_dict.get('path_string',''))} | net={profit_pct:.3f}%",
        )

        return await self._process_order(cmd)

    async def on_spatial_spread(self, spread: dict) -> Optional[OrderCommand]:
        """
        Called when a cross-exchange spatial arb spread is detected.
        Fires a BUY on the cheap exchange if net profit exceeds threshold.
        """
        if not self._dcfg.enabled:
            return None

        mode = self._cfg.trading.mode
        if mode == TradingMode.DISABLED:
            return None

        net_pct = spread.get("net_pct", 0.0)
        if net_pct <= 0 or net_pct < self._dcfg.graph_min_profit_pct:
            return None

        buy_ex   = spread.get("buy_ex", "")
        sell_ex  = spread.get("sell_ex", "")
        pair     = spread.get("pair", "")
        buy_price = spread.get("buy_price", 0.0)

        if not buy_ex or not pair or buy_price <= 0:
            return None

        if not self._exchange_enabled(buy_ex):
            return None

        if not self._check_cooldown(buy_ex, pair):
            return None

        capital = self._dcfg.max_capital_per_trade
        volume  = round(capital / buy_price, 6)

        cmd = OrderCommand(
            id           = str(uuid4()),
            exchange     = buy_ex,
            pair         = pair,
            side         = OrderSide.BUY,
            order_type   = OrderType.MARKET,
            price        = buy_price,
            volume       = volume,
            capital_usd  = capital,
            source       = SignalSource.GRAPH_ARB,   # reuse closest source type
            signal_score = net_pct / 100,
            confidence   = "HIGH" if net_pct > 1.0 else "MEDIUM",
            trading_mode = mode.value,
            dry_run      = (mode != TradingMode.LIVE),
            expires_at   = datetime.now(timezone.utc) + timedelta(seconds=self._dcfg.order_ttl_seconds),
            notes        = f"Spatial arb | {buy_ex}→{sell_ex} | net={net_pct:.3f}%",
        )

        return await self._process_order(cmd)

    def get_order_log(self, limit: int = 100) -> List[dict]:
        return list(reversed(self._order_log))[:limit]

    def get_stats(self) -> dict:
        total     = len(self._order_log)
        simulated = sum(1 for o in self._order_log if o.get("trading_mode") == "simulate")
        live      = sum(1 for o in self._order_log if o.get("trading_mode") == "live")
        return {
            "total_decisions":    total,
            "simulated_orders":   simulated,
            "live_orders":        live,
            "cooldowns_active":   len(self._last_order),
        }

    # ─── Internal ────────────────────────────────────────────────────────────

    def _exchange_enabled(self, exchange: str) -> bool:
        enabled_map = self._cfg.trading.exchange_enabled
        if not enabled_map:
            return True   # if no per-exchange config, allow all
        return enabled_map.get(exchange, False)

    def _check_cooldown(self, exchange: str, pair: str) -> bool:
        key  = f"{exchange}:{pair}"
        last = self._last_order.get(key)
        if last:
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if elapsed < self._dcfg.cooldown_seconds:
                logger.debug(f"[DECISION] Cooldown active for {key} ({elapsed:.0f}s < {self._dcfg.cooldown_seconds}s)")
                return False
        return True

    def _check_concurrent(self) -> bool:
        open_count = sum(
            1 for o in self._order_log[-50:]
            if o.get("status") in ("pending", "sent", "partial")
        )
        if open_count >= self._dcfg.max_concurrent_orders:
            logger.warning(f"[DECISION] Max concurrent orders reached ({open_count})")
            return False
        return True

    async def _process_order(self, cmd: OrderCommand) -> Optional[OrderCommand]:
        """Apply risk check, log, publish."""
        if cmd.is_expired():
            logger.debug(f"[DECISION] Order {cmd.id} expired before processing")
            return None

        if not self._check_concurrent():
            return None

        # Risk manager veto
        allowed, reason = self._risk.check(cmd)
        if not allowed:
            logger.warning(f"[DECISION] Risk manager blocked order: {reason}")
            self._log_order(cmd, status="blocked", notes=reason)
            # Set cooldown even for blocked orders so the same signal doesn't
            # spam the log on every scan tick (graph_arb fires every 5s)
            self._last_order[f"{cmd.exchange}:{cmd.pair}"] = datetime.now(timezone.utc)
            return None

        # Update cooldown
        self._last_order[f"{cmd.exchange}:{cmd.pair}"] = datetime.now(timezone.utc)

        # Log it
        self._log_order(cmd, status=cmd.trading_mode)

        mode = self._cfg.trading.mode
        if mode == TradingMode.SIMULATE:
            logger.info(
                f"[SIMULATE] {cmd.side.value.upper()} {cmd.pair} on {cmd.exchange} "
                f"@ {cmd.price} vol={cmd.volume} SL={cmd.stop_loss} "
                f"TP1={cmd.take_profit_1} TP2={cmd.take_profit_2} | {cmd.notes}"
            )
        elif mode == TradingMode.LIVE:
            await self._bus.publish_order_command(cmd.to_dict())
            logger.warning(
                f"[LIVE ORDER] {cmd.side.value.upper()} {cmd.pair} on {cmd.exchange} "
                f"@ {cmd.price} vol={cmd.volume} | {cmd.notes}"
            )

        return cmd

    def _log_order(self, cmd: OrderCommand, status: str = "pending", notes: str = "") -> None:
        entry = cmd.to_dict()
        entry["status"]    = status
        entry["log_notes"] = notes
        self._order_log.append(entry)
        if len(self._order_log) > 5000:
            self._order_log = self._order_log[-4000:]

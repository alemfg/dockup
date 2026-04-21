"""
Risk Manager (v3.3)
Circuit breaker layer that wraps the decision engine.
All order commands pass through here before being executed.

Checks:
  - Daily loss limit
  - Drawdown from peak balance
  - Consecutive loss streak
  - Per-exchange capital exposure
  - Per-pair open position size
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from typing import List, Optional, Tuple

from config.loader import AppConfig
from messaging.logging import get_logger
from messaging.models import OrderCommand
from storage.market_state import MarketState

logger = get_logger("brain.decision.risk")


class RiskManager:

    def __init__(self, config: AppConfig, market_state: MarketState):
        self._cfg    = config
        self._rcfg   = config.risk
        self._market = market_state

        self._halted:            bool  = False
        self._halt_reason:       str   = ""
        self._daily_loss:        float = 0.0
        self._daily_loss_date:   date  = datetime.now(timezone.utc).date()
        self._peak_balance:      float = 0.0
        self._consecutive_losses: int  = 0
        self._checks_log:        List[dict] = []

    # ─── Public ──────────────────────────────────────────────────────────────

    def check(self, cmd: OrderCommand) -> Tuple[bool, str]:
        """Return (allowed, reason). Called before every order."""
        if not self._rcfg.enabled:
            return True, ""

        if self._halted:
            return False, f"System halted: {self._halt_reason}"

        self._reset_daily_if_needed()

        # Daily loss
        if self._daily_loss >= self._rcfg.max_daily_loss_usd:
            self._halt(f"Daily loss limit reached (${self._daily_loss:.2f})")
            return False, self._halt_reason

        # Drawdown
        total = self._market.get_total_usd()
        if total > 0:
            if total > self._peak_balance:
                self._peak_balance = total
            if self._peak_balance > 0:
                drawdown_pct = ((self._peak_balance - total) / self._peak_balance) * 100
                if drawdown_pct >= self._rcfg.max_drawdown_pct:
                    self._halt(f"Drawdown limit reached ({drawdown_pct:.1f}%)")
                    return False, self._halt_reason

        # Consecutive losses
        if self._consecutive_losses >= self._rcfg.max_consecutive_losses:
            self._halt(f"Consecutive loss limit ({self._consecutive_losses})")
            return False, self._halt_reason

        # Exchange exposure — only enforce when we have balance data
        # If total is 0 the brain has no balance information yet; don't block.
        by_exchange = self._market.get_balances_by_exchange()
        if total > 0:
            ex_usd = sum(b.get("usd_value", 0.0) for b in by_exchange.get(cmd.exchange, []))
            if (ex_usd + cmd.capital_usd) / total > self._rcfg.max_exchange_exposure:
                return False, f"Exchange exposure limit for {cmd.exchange}"

        # Pair exposure
        open_usd = self._market.get_open_position_usd(cmd.exchange, cmd.pair)
        if open_usd + cmd.capital_usd > self._rcfg.max_pair_exposure_usd:
            return False, f"Pair exposure limit for {cmd.pair} (${open_usd:.0f} open)"

        self._log_check(cmd, allowed=True)
        return True, ""

    def record_result(self, pnl_usd: float) -> None:
        """Called when an order closes with a P&L figure."""
        self._reset_daily_if_needed()
        if pnl_usd < 0:
            self._daily_loss   += abs(pnl_usd)
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def resume(self) -> None:
        """Manually resume after a halt."""
        self._halted      = False
        self._halt_reason = ""
        logger.warning("[RISK] System halt manually cleared")

    def status(self) -> dict:
        total = self._market.get_total_usd()
        drawdown = 0.0
        if self._peak_balance > 0 and total > 0:
            drawdown = ((self._peak_balance - total) / self._peak_balance) * 100
        return {
            "halted":              self._halted,
            "halt_reason":         self._halt_reason,
            "daily_loss_usd":      round(self._daily_loss, 2),
            "max_daily_loss_usd":  self._rcfg.max_daily_loss_usd,
            "daily_loss_pct":      round(self._daily_loss / max(self._rcfg.max_daily_loss_usd, 1) * 100, 1),
            "drawdown_pct":        round(drawdown, 2),
            "max_drawdown_pct":    self._rcfg.max_drawdown_pct,
            "consecutive_losses":  self._consecutive_losses,
            "max_consecutive":     self._rcfg.max_consecutive_losses,
            "peak_balance_usd":    round(self._peak_balance, 2),
        }

    # ─── Internal ────────────────────────────────────────────────────────────

    def _halt(self, reason: str) -> None:
        self._halted      = True
        self._halt_reason = reason
        logger.error(f"[RISK] SYSTEM HALTED: {reason}")
        try:
            from events.event_bus import emit_sync, Category, Level
            emit_sync(
                category = Category.RISK,
                title    = "⛔ System halted",
                detail   = reason,
                level    = Level.ERROR,
                data     = {"reason": reason},
            )
        except Exception:
            pass

    def _reset_daily_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._daily_loss_date:
            self._daily_loss      = 0.0
            self._daily_loss_date = today

    def _log_check(self, cmd: OrderCommand, allowed: bool) -> None:
        self._checks_log.append({
            "order_id": cmd.id,
            "exchange": cmd.exchange,
            "pair":     cmd.pair,
            "allowed":  allowed,
            "ts":       datetime.now(timezone.utc).isoformat(),
        })
        if len(self._checks_log) > 500:
            self._checks_log = self._checks_log[-400:]

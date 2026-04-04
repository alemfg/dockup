"""
Alert Sender (v4)
Sends notifications via ntfy, Slack webhook, or generic webhook.
Triggered by: risk halts, SL/TP hits, worker deaths, large opportunities.

Config (config.yaml alerts section):
  ntfy_enabled: true
  ntfy_url: "https://ntfy.sh"
  ntfy_topic: "arbx-alerts"
  slack_enabled: true
  slack_webhook: "https://hooks.slack.com/services/..."
  webhook_enabled: true
  webhook_url: "https://your-server.com/webhook"
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from messaging.logging import get_logger

logger = get_logger("alerts.sender")

PRIORITY_MAP = {
    "critical": 5,
    "high":     4,
    "default":  3,
    "low":      2,
    "min":      1,
}

EMOJI_MAP = {
    "risk_halt":       "🛑",
    "sl_hit":          "🔴",
    "tp_hit":          "🟢",
    "worker_dead":     "💀",
    "opportunity":     "💰",
    "order_placed":    "📋",
    "order_failed":    "⚠️",
    "system":          "🧠",
}


class AlertSender:
    """
    Async alert sender. Call send() from any coroutine.
    Uses a single aiohttp session for efficiency.
    """

    def __init__(self, config):
        self._cfg     = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._queue:   asyncio.Queue = asyncio.Queue(maxsize=200)
        self._running  = False

    async def start(self) -> None:
        """Start background worker that drains the alert queue."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self._running = True
        asyncio.create_task(self._drain_loop(), name="alert_sender")
        logger.info("Alert sender started")

    async def stop(self) -> None:
        self._running = False
        if self._session:
            await self._session.close()

    async def send(
        self,
        event_type:   str,
        title:        str,
        message:      str,
        priority:     str = "default",
        tags:         Optional[list] = None,
    ) -> None:
        """
        Queue an alert. Non-blocking — drops if queue is full.
        event_type: risk_halt | sl_hit | tp_hit | worker_dead | opportunity | order_placed | order_failed | system
        """
        alert = {
            "event_type": event_type,
            "title":      title,
            "message":    message,
            "priority":   priority,
            "tags":       tags or [],
            "ts":         datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            logger.warning("Alert queue full — dropping alert")

    async def _drain_loop(self) -> None:
        while self._running:
            try:
                alert = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                await self._dispatch(alert)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Alert drain error: {exc}")

    async def _dispatch(self, alert: dict) -> None:
        """Send to all enabled channels."""
        cfg = self._cfg.alerts
        tasks = []

        if cfg.ntfy_enabled and cfg.ntfy_topic:
            tasks.append(self._send_ntfy(alert))
        if cfg.slack_enabled and cfg.slack_webhook:
            tasks.append(self._send_slack(alert))
        if cfg.webhook_enabled and cfg.webhook_url:
            tasks.append(self._send_webhook(alert))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"Alert send error: {r}")

    async def _send_ntfy(self, alert: dict) -> None:
        """Send to ntfy.sh (or self-hosted ntfy)."""
        cfg     = self._cfg.alerts
        url     = f"{cfg.ntfy_url.rstrip('/')}/{cfg.ntfy_topic}"
        emoji   = EMOJI_MAP.get(alert["event_type"], "📢")
        headers = {
            "Title":    f"{emoji} {alert['title']}",
            "Priority": str(PRIORITY_MAP.get(alert["priority"], 3)),
            "Tags":     ",".join(alert.get("tags", [])) or alert["event_type"],
        }
        async with self._session.post(url, data=alert["message"], headers=headers) as resp:
            if resp.status >= 400:
                logger.warning(f"ntfy returned {resp.status}")

    async def _send_slack(self, alert: dict) -> None:
        """Send to Slack webhook."""
        emoji   = EMOJI_MAP.get(alert["event_type"], "📢")
        payload = {
            "text": f"{emoji} *{alert['title']}*\n{alert['message']}",
            "attachments": [{
                "color":  "#ff0000" if alert["priority"] in ("critical", "high") else "#36a64f",
                "footer": f"ARBX · {alert['ts']}",
            }],
        }
        async with self._session.post(self._cfg.alerts.slack_webhook, json=payload) as resp:
            if resp.status >= 400:
                logger.warning(f"Slack returned {resp.status}")

    async def _send_webhook(self, alert: dict) -> None:
        """Send to generic webhook as JSON POST."""
        payload = {
            "source":     "arbx",
            "event_type": alert["event_type"],
            "title":      alert["title"],
            "message":    alert["message"],
            "priority":   alert["priority"],
            "timestamp":  alert["ts"],
        }
        async with self._session.post(self._cfg.alerts.webhook_url, json=payload) as resp:
            if resp.status >= 400:
                logger.warning(f"Webhook returned {resp.status}")


# ─── Convenience helpers ──────────────────────────────────────────────────────

async def alert_risk_halt(sender: AlertSender, reason: str) -> None:
    await sender.send("risk_halt", "ARBX — System Halted",
                      f"Risk manager halted all trading.\nReason: {reason}",
                      priority="critical", tags=["risk", "halt"])


async def alert_sl_hit(sender: AlertSender, pair: str, exchange: str, pnl: float) -> None:
    await sender.send("sl_hit", f"Stop Loss Hit — {pair}",
                      f"Exchange: {exchange}\nP&L: ${pnl:+.2f}",
                      priority="high", tags=["sl", pair.replace("/", "-")])


async def alert_tp_hit(sender: AlertSender, pair: str, exchange: str, tp: int, pnl: float) -> None:
    await sender.send("tp_hit", f"TP{tp} Hit — {pair}",
                      f"Exchange: {exchange}\nP&L: ${pnl:+.2f}",
                      priority="default", tags=["tp", pair.replace("/", "-")])


async def alert_worker_dead(sender: AlertSender, worker_id: str, exchange: str) -> None:
    await sender.send("worker_dead", f"Worker Dead — {exchange}",
                      f"Worker {worker_id} on {exchange} has lost heartbeat.",
                      priority="high", tags=["worker", exchange])


async def alert_opportunity(sender: AlertSender, pair: str, profit_pct: float, source: str) -> None:
    await sender.send("opportunity", f"Opportunity — {pair}",
                      f"Source: {source}\nNet profit: {profit_pct:.3f}%",
                      priority="default", tags=["opportunity", source])


async def alert_order(sender: AlertSender, side: str, pair: str, exchange: str,
                      price: float, mode: str) -> None:
    await sender.send("order_placed", f"Order {side.upper()} — {pair}",
                      f"Exchange: {exchange}\nPrice: {price}\nMode: {mode}",
                      priority="default", tags=["order", mode])

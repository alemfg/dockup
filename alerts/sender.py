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
        # Each _send_* method now creates its own session per call (simpler,
        # avoids lifecycle issues when called directly from test routes).
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
        if cfg.slack_enabled and getattr(cfg, "slack_webhook", ""):
            tasks.append(self._send_slack(alert))
        if getattr(cfg, "discord_enabled", False) and getattr(cfg, "discord_webhook", ""):
            tasks.append(self._send_discord(alert))
        if getattr(cfg, "telegram_enabled", False) and getattr(cfg, "telegram_bot_token", ""):
            tasks.append(self._send_telegram(alert))
        if getattr(cfg, "email_enabled", False) and getattr(cfg, "email_smtp_host", ""):
            tasks.append(self._send_email(alert))
        if cfg.webhook_enabled and cfg.webhook_url:
            tasks.append(self._send_webhook(alert))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"Alert send error: {r}")

    async def _ntfy_session(self):
        """Async context manager: yields the shared session or a fresh one-shot session."""
        if self._session and not self._session.closed:
            yield self._session
        else:
            # Called directly from test route before start() — create a one-shot session
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                yield s

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
        body = alert["message"]
        if isinstance(body, str):
            body = body.encode()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(url, data=body, headers=headers) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning(f"ntfy returned {resp.status}: {text[:200]}")

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
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(self._cfg.alerts.slack_webhook, json=payload) as resp:
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
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(self._cfg.alerts.webhook_url, json=payload) as resp:
                if resp.status >= 400:
                    logger.warning(f"Webhook returned {resp.status}")

    async def _send_discord(self, alert: dict) -> None:
        """Send to Discord via webhook."""
        emoji   = EMOJI_MAP.get(alert["event_type"], "📢")
        color   = 0xff0000 if alert["priority"] in ("critical","high") else 0x36a64f
        payload = {
            "embeds": [{
                "title":       f"{emoji} {alert['title']}",
                "description": alert["message"],
                "color":       color,
                "footer":      {"text": f"ARBX · {alert['ts']}"},
            }]
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(self._cfg.alerts.discord_webhook, json=payload) as resp:
                if resp.status >= 400:
                    logger.warning(f"Discord returned {resp.status}")

    async def _send_telegram(self, alert: dict) -> None:
        """Send to Telegram via Bot API."""
        cfg   = self._cfg.alerts
        emoji = EMOJI_MAP.get(alert["event_type"], "📢")
        text  = f"{emoji} *{alert['title']}*\n{alert['message']}"
        url   = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id":    cfg.telegram_chat_id,
            "text":       text,
            "parse_mode": "Markdown",
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status >= 400:
                    logger.warning(f"Telegram returned {resp.status}")

    async def _send_email(self, alert: dict) -> None:
        """Send via SMTP. Supports starttls (587), ssl (465), or none (25)."""
        import smtplib
        from email.mime.text import MIMEText
        cfg      = self._cfg.alerts
        emoji    = EMOJI_MAP.get(alert["event_type"], "📢")
        tls_mode = getattr(cfg, "email_tls_mode", "starttls")

        def _sync_send():
            msg = MIMEText(f"{alert['message']}\n\nTimestamp: {alert['ts']}")
            msg["Subject"] = f"{emoji} ARBX: {alert['title']}"
            msg["From"]    = cfg.email_from
            msg["To"]      = cfg.email_to
            port           = getattr(cfg, "email_smtp_port", 587)

            if tls_mode == "ssl":
                smtp = smtplib.SMTP_SSL(cfg.email_smtp_host, port)
            else:
                smtp = smtplib.SMTP(cfg.email_smtp_host, port)
                if tls_mode == "starttls":
                    smtp.starttls()
            with smtp:
                if cfg.email_password:
                    smtp.login(cfg.email_from, cfg.email_password)
                smtp.send_message(msg)

        await asyncio.get_event_loop().run_in_executor(None, _sync_send)


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

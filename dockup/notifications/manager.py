"""Multi-channel notification dispatcher."""
from __future__ import annotations

import asyncio
import smtplib
from email.mime.text import MIMEText

import httpx
import structlog

from dockup.config import NotificationSettings
from dockup.models import Alert, AlertLevel

log = structlog.get_logger(__name__)

_LEVEL_ORDER = {AlertLevel.INFO: 0, AlertLevel.WARNING: 1, AlertLevel.ERROR: 2, AlertLevel.CRITICAL: 3}


def _level_gte(level: AlertLevel, min_level: str) -> bool:
    try:
        return _LEVEL_ORDER[level] >= _LEVEL_ORDER[AlertLevel(min_level)]
    except (KeyError, ValueError):
        return True


class NotificationManager:
    def __init__(self, cfg: NotificationSettings) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(timeout=10)

    async def send(self, alert: Alert) -> None:
        tasks = []
        if self._cfg.ntfy.enabled and _level_gte(alert.level, self._cfg.ntfy.min_level):
            tasks.append(self._send_ntfy(alert))
        if self._cfg.slack.enabled and _level_gte(alert.level, self._cfg.slack.min_level):
            tasks.append(self._send_slack(alert))
        if self._cfg.webhook.enabled and _level_gte(alert.level, self._cfg.webhook.min_level):
            tasks.append(self._send_webhook(alert))
        if self._cfg.pagerduty.enabled and _level_gte(alert.level, self._cfg.pagerduty.min_level):
            tasks.append(self._send_pagerduty(alert))
        if self._cfg.teams.enabled and _level_gte(alert.level, self._cfg.teams.min_level):
            tasks.append(self._send_teams(alert))
        if self._cfg.email.enabled and _level_gte(alert.level, self._cfg.email.min_level):
            tasks.append(asyncio.to_thread(self._send_email, alert))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    log.warning("Notification channel failed", error=str(r))

    async def _send_ntfy(self, alert: Alert) -> None:
        cfg = self._cfg.ntfy
        url = f"{cfg.url.rstrip('/')}/{cfg.topic}"
        headers = {
            "Title": alert.title,
            "Priority": self._ntfy_priority(alert.level),
            "Tags": f"{alert.level.value},dockup,{alert.target}",
        }
        if cfg.token:
            headers["Authorization"] = f"Bearer {cfg.token}"
        resp = await self._client.post(url, content=alert.message, headers=headers)
        resp.raise_for_status()

    async def _send_slack(self, alert: Alert) -> None:
        payload = {
            "channel": self._cfg.slack.channel,
            "attachments": [{
                "color": self._slack_color(alert.level),
                "title": alert.title,
                "text": alert.message,
                "fields": [
                    {"title": "Target", "value": alert.target, "short": True},
                    {"title": "Time", "value": alert.timestamp.isoformat(), "short": True},
                ],
            }],
        }
        resp = await self._client.post(self._cfg.slack.webhook_url, json=payload)
        resp.raise_for_status()

    async def _send_webhook(self, alert: Alert) -> None:
        payload = {
            "level": alert.level.value,
            "title": alert.title,
            "message": alert.message,
            "target": alert.target,
            "timestamp": alert.timestamp.isoformat(),
        }
        resp = await self._client.post(self._cfg.webhook.url, json=payload)
        resp.raise_for_status()

    async def _send_pagerduty(self, alert: Alert) -> None:
        payload = {
            "routing_key": self._cfg.pagerduty.integration_key,
            "event_action": "trigger",
            "payload": {
                "summary": f"{alert.title}: {alert.message}",
                "severity": alert.level.value,
                "source": "dockup",
                "custom_details": {"target": alert.target},
            },
        }
        resp = await self._client.post("https://events.pagerduty.com/v2/enqueue", json=payload)
        resp.raise_for_status()

    async def _send_teams(self, alert: Alert) -> None:
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": self._teams_color(alert.level),
            "summary": alert.title,
            "sections": [{
                "activityTitle": alert.title,
                "activitySubtitle": f"Target: {alert.target} | {alert.timestamp.isoformat()}",
                "text": alert.message,
            }],
        }
        resp = await self._client.post(self._cfg.teams.webhook_url, json=payload)
        resp.raise_for_status()

    def _send_email(self, alert: Alert) -> None:
        cfg = self._cfg.email
        msg = MIMEText(f"{alert.message}\n\nTarget: {alert.target}\nTime: {alert.timestamp.isoformat()}")
        msg["Subject"] = f"[dockup] {alert.title}"
        msg["From"] = cfg.from_addr
        msg["To"] = ", ".join(cfg.to_addrs)

        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(cfg.username, cfg.password)
            smtp.sendmail(cfg.from_addr, cfg.to_addrs, msg.as_string())

    @staticmethod
    def _ntfy_priority(level: AlertLevel) -> str:
        return {"critical": "urgent", "error": "high", "warning": "default", "info": "low"}.get(level.value, "default")

    @staticmethod
    def _slack_color(level: AlertLevel) -> str:
        return {"critical": "danger", "error": "danger", "warning": "warning"}.get(level.value, "good")

    @staticmethod
    def _teams_color(level: AlertLevel) -> str:
        return {"critical": "FF0000", "error": "FF0000", "warning": "FFA500"}.get(level.value, "00CC00")

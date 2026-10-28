"""notifications.py — tiered notification dispatch (email + ntfy.sh).

Tiers:
- urgent: Reconciliation FAIL, run PARTIAL, LM Studio offline → email + ntfy
- summary: daily/weekly report (rotation_plan.md + brief) → email only
- debug: stage degraded, symbol unresolved → ntfy only (local debug)

Config (api.env):
- NOTIFY_EMAIL (sender address)
- NOTIFY_EMAIL_PASSWORD (Gmail App Password)
- NOTIFY_EMAIL_TO (recipient, comma-separated)
- NOTIFY_NTFY_TOPIC (ntfy.sh topic name, e.g. "portfolio-alerts")
- NOTIFY_ON_FAIL (1/0) — send urgent on failure
- NOTIFY_ON_COMPLETE (1/0) — send summary on successful run

No secrets are logged. Never raises (notifications are best-effort).
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)


def _cfg(key: str, default: str = "") -> str:
    return str(os.getenv(key, default) or "").strip()


def _email_available() -> bool:
    return bool(_cfg("NOTIFY_EMAIL") and _cfg("NOTIFY_EMAIL_PASSWORD") and _cfg("NOTIFY_EMAIL_TO"))


def _ntfy_available() -> bool:
    return bool(_cfg("NOTIFY_NTFY_TOPIC"))


def send_email(subject: str, body: str, to: Optional[str] = None) -> bool:
    """Send email via SMTP (Gmail default). Returns True on success."""
    sender = _cfg("NOTIFY_EMAIL")
    password = _cfg("NOTIFY_EMAIL_PASSWORD")
    recipient = to or _cfg("NOTIFY_EMAIL_TO")
    if not (sender and password and recipient):
        logger.debug("email: not configured (NOTIFY_EMAIL/NOTIFY_EMAIL_PASSWORD/NOTIFY_EMAIL_TO)")
        return False
    try:
        smtp_host = _cfg("NOTIFY_SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(_cfg("NOTIFY_SMTP_PORT", "465") or 465)
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, [r.strip() for r in recipient.split(",")], msg.as_string())
        logger.info("email: sent to %s — %s", recipient, subject)
        return True
    except Exception as exc:
        logger.warning("email: send failed: %s", type(exc).__name__)
        return False


def send_ntfy(title: str, body: str, priority: str = "default") -> bool:
    """Send push notification via ntfy.sh. Returns True on success."""
    topic = _cfg("NOTIFY_NTFY_TOPIC")
    if not topic:
        logger.debug("ntfy: not configured (NOTIFY_NTFY_TOPIC)")
        return False
    try:
        import requests
        server = _cfg("NOTIFY_NTFY_SERVER", "https://ntfy.sh")
        url = f"{server.rstrip('/')}/{topic}"
        headers = {"Title": title, "Priority": priority, "Tags": "chart_with_upwards_trend"}
        r = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=10)
        if r.status_code == 200:
            logger.info("ntfy: sent to %s — %s", topic, title)
            return True
        logger.warning("ntfy: HTTP %s", r.status_code)
        return False
    except Exception as exc:
        logger.warning("ntfy: send failed: %s", type(exc).__name__)
        return False


def notify_urgent(subject: str, body: str) -> None:
    """Urgent tier: email + ntfy (if configured)."""
    if _cfg("NOTIFY_ON_FAIL", "1") == "1":
        send_email(f"[URGENT] {subject}", body)
        send_ntfy(f"URGENT: {subject}", body, priority="urgent")


def notify_summary(subject: str, body: str) -> None:
    """Summary tier: email only (if configured)."""
    if _cfg("NOTIFY_ON_COMPLETE", "1") == "1":
        send_email(subject, body)


def notify_debug(title: str, body: str) -> None:
    """Debug tier: ntfy only (if configured)."""
    send_ntfy(title, body, priority="low")

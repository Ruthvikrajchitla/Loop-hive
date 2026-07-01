"""
LoopHive — Email Sender

Minimal SMTP sender for the outreach engine. Inert until SMTP creds are set.
For Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_USER=you@gmail.com,
SMTP_PASSWORD=<app password> (not your login password).
"""

from __future__ import annotations

import asyncio
import os

import structlog

logger = structlog.get_logger(__name__)


def _creds() -> dict | None:
    host = os.getenv("SMTP_HOST", "")
    user = os.getenv("SMTP_USER", "")
    pw = os.getenv("SMTP_PASSWORD", "")
    if not host or not user or not pw or "your_" in pw.lower():
        return None
    return {"host": host, "port": int(os.getenv("SMTP_PORT", "587")), "user": user, "pw": pw}


async def send_email(to: str, subject: str, body: str) -> dict:
    """Send a plain-text email. Returns {status}. Never raises."""
    creds = _creds()
    if not creds:
        return {"status": "skipped", "reason": "smtp_not_configured"}
    if not to:
        return {"status": "skipped", "reason": "no_recipient"}

    def _send():
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = creds["user"]
        msg["To"] = to
        with smtplib.SMTP(creds["host"], creds["port"], timeout=30) as s:
            s.starttls()
            s.login(creds["user"], creds["pw"])
            s.send_message(msg)

    try:
        await asyncio.to_thread(_send)
        logger.info("email_sent", to=to)
        return {"status": "sent"}
    except Exception as e:
        logger.warning("email_send_failed", error=str(e)[:150])
        return {"status": "error", "reason": str(e)[:150]}

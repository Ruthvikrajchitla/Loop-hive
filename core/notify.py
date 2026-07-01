"""
LoopHive — Boss Escalation

When agents hit something critical or beyond their ability, they escalate to the
boss (the human owner): a notification is logged for the dashboard, and — if a
boss email + SMTP are configured — an email is sent.
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)


async def escalate(title: str, body: str, level: str = "critical", source: str = "swarm") -> None:
    """Record a boss notification and email it if possible. Never fatal."""
    emailed = False
    boss_email = os.getenv("BOSS_EMAIL", "")
    boss_name = os.getenv("BOSS_NAME", "Boss")

    if boss_email and "your_" not in boss_email.lower():
        try:
            from publishers.email_sender import send_email
            res = await send_email(
                boss_email,
                f"[LoopHive · {level.upper()}] {title}",
                f"Hi {boss_name},\n\n{body}\n\n— Your LoopHive agent team",
            )
            emailed = res.get("status") == "sent"
        except Exception as e:
            logger.debug("escalation_email_failed", error=str(e)[:150])

    try:
        from storage.database import async_session_factory, Notification
        async with async_session_factory() as session:
            async with session.begin():
                session.add(Notification(
                    level=level, title=title[:300], body=body, source=source, emailed=emailed,
                ))
    except Exception as e:
        logger.debug("notification_log_failed", error=str(e)[:150])

    logger.info("boss_escalation", title=title[:80], level=level, emailed=emailed)

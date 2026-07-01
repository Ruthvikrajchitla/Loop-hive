"""
LoopHive — Email Reader (IMAP)

Reads the agent's inbox so it can understand and act on replies. Inert until IMAP
creds are set; falls back to the SMTP account (same Gmail app password works for
both). Marks fetched messages as seen so they aren't processed twice.
"""

from __future__ import annotations

import asyncio
import email
import os
from email.header import decode_header

import structlog

logger = structlog.get_logger(__name__)


def _creds() -> dict | None:
    host = os.getenv("IMAP_HOST", "imap.gmail.com")
    user = os.getenv("IMAP_USER", "") or os.getenv("SMTP_USER", "")
    pw = os.getenv("IMAP_PASSWORD", "") or os.getenv("SMTP_PASSWORD", "")
    if not host or not user or not pw or "your_" in pw.lower():
        return None
    return {"host": host, "port": int(os.getenv("IMAP_PORT", "993")), "user": user, "pw": pw}


def _decode(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _plain_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""


async def fetch_unread(limit: int = 10) -> list[dict]:
    """Fetch up to ``limit`` unread emails and mark them seen. Never raises."""
    creds = _creds()
    if not creds:
        return []

    def _fetch():
        import imaplib
        messages = []
        imap = imaplib.IMAP4_SSL(creds["host"], creds["port"])
        try:
            imap.login(creds["user"], creds["pw"])
            imap.select("INBOX")
            status, data = imap.search(None, "UNSEEN")
            if status != "OK":
                return messages
            ids = data[0].split()[:limit]
            for mid in ids:
                status, msg_data = imap.fetch(mid, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                sender = email.utils.parseaddr(msg.get("From", ""))[1]
                messages.append({
                    "sender": sender,
                    "subject": _decode(msg.get("Subject", "")),
                    "body": _plain_body(msg).strip()[:5000],
                    "message_id": msg.get("Message-ID", ""),
                })
                imap.store(mid, "+FLAGS", "\\Seen")
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        return messages

    try:
        msgs = await asyncio.to_thread(_fetch)
        logger.info("inbox_fetched", count=len(msgs))
        return msgs
    except Exception as e:
        logger.warning("inbox_fetch_failed", error=str(e)[:150])
        return []

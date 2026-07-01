"""
LoopHive — Telegram Poster

Publishes marketing/announcement posts to a Telegram channel via the Bot API
(the automation-friendly, ToS-compliant path). Inert until both
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set — then the marketing agent's
copy actually reaches your channel.

Setup:
  1. Message @BotFather → /newbot → copy the token → TELEGRAM_BOT_TOKEN
  2. Create a channel, add the bot as an admin, set TELEGRAM_CHAT_ID=@yourchannel
"""

from __future__ import annotations

import os

import httpx
import structlog

logger = structlog.get_logger(__name__)


def _creds() -> tuple[str, str] | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat or "your_" in token.lower():
        return None
    return token, chat


async def post_to_telegram(text: str, image_url: str | None = None) -> dict:
    """Post text (optionally with an image) to the configured Telegram channel.

    Returns {"status": "posted" | "skipped" | "error", ...}. Never raises.
    """
    creds = _creds()
    if not creds:
        return {"status": "skipped", "reason": "telegram_not_configured"}
    token, chat = creds
    text = (text or "").strip()
    if not text:
        return {"status": "skipped", "reason": "empty_text"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if image_url:
                resp = await client.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    json={"chat_id": chat, "caption": text[:1024], "photo": image_url},
                )
            else:
                resp = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": text[:4096], "disable_web_page_preview": False},
                )
            data = resp.json()
        if data.get("ok"):
            logger.info("telegram_posted", chat=chat, chars=len(text))
            return {"status": "posted", "message_id": data.get("result", {}).get("message_id")}
        logger.warning("telegram_post_rejected", error=str(data.get("description"))[:150])
        return {"status": "error", "reason": data.get("description")}
    except Exception as e:
        logger.warning("telegram_post_failed", error=str(e)[:150])
        return {"status": "error", "reason": str(e)[:150]}

"""
LoopHive — Twitter / X Poster

Posts to X via the v2 API (OAuth 1.0a user context) using tweepy. Inert until the
four Twitter keys are set. This is Otto's primary marketing channel.
"""

from __future__ import annotations

import asyncio
import os

import structlog

logger = structlog.get_logger(__name__)


def _keys() -> tuple[str, str, str, str] | None:
    ck = os.getenv("TWITTER_API_KEY", "")
    cs = os.getenv("TWITTER_API_SECRET", "")
    at = os.getenv("TWITTER_ACCESS_TOKEN", "")
    ats = os.getenv("TWITTER_ACCESS_SECRET", "")
    vals = [ck, cs, at, ats]
    if not all(vals) or any("your_" in v.lower() for v in vals):
        return None
    return ck, cs, at, ats


async def post_to_twitter(text: str) -> dict:
    """Post a single tweet (<=280 chars). Returns {status}. Never raises."""
    keys = _keys()
    if not keys:
        return {"status": "skipped", "reason": "twitter_not_configured"}
    text = (text or "").strip()
    if not text:
        return {"status": "skipped", "reason": "empty_text"}

    # Trim to the 280-char limit on a word boundary.
    if len(text) > 280:
        text = text[:277].rsplit(" ", 1)[0] + "…"

    def _post():
        import tweepy
        client = tweepy.Client(
            consumer_key=keys[0], consumer_secret=keys[1],
            access_token=keys[2], access_token_secret=keys[3],
        )
        return client.create_tweet(text=text)

    try:
        resp = await asyncio.to_thread(_post)
        tweet_id = resp.data.get("id") if resp and resp.data else None
        logger.info("twitter_posted", chars=len(text), id=tweet_id)
        return {"status": "posted", "id": tweet_id}
    except Exception as e:
        logger.warning("twitter_post_failed", error=str(e)[:150])
        return {"status": "error", "reason": str(e)[:150]}

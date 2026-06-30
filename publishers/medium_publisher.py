"""
LoopHive — Medium Publisher

Uses the official Medium API to publish article drafts.
Requires a Medium integration token.
"""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger(__name__)


class MediumPublisher:
    """Publishes posts to Medium via the REST API."""

    def __init__(self, api_token: str = ""):
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def get_user_id(self, client: httpx.AsyncClient) -> str | None:
        """Fetch the authenticated user's ID."""
        try:
            r = await client.get("https://api.medium.com/v1/me", headers=self.headers)
            if r.status_code == 200:
                data = r.json()
                return data.get("data", {}).get("id")
        except Exception as e:
            logger.error("medium_get_user_id_failed", error=str(e))
        return None

    async def publish_article(
        self, title: str, content_md: str, tags: list[str] = None, draft: bool = True
    ) -> dict:
        """Publish an article (defaults to draft mode as per Medium AI policy)."""
        logger.info("medium_article_publish_attempt", title=title)

        if not self.api_token or "your_" in self.api_token:
            logger.warning("medium_token_missing", action="simulating_medium_publish")
            return {
                "platform": "medium",
                "title": title,
                "url": f"https://medium.com/@simulated/post-{hash(title)}",
                "status": "draft",
            }

        async with httpx.AsyncClient(timeout=15.0) as client:
            user_id = await self.get_user_id(client)
            if not user_id:
                raise RuntimeError("Failed to authenticate with Medium API token.")

            url = f"https://api.medium.com/v1/users/{user_id}/posts"
            
            body = {
                "title": title,
                "contentFormat": "markdown",
                "content": content_md,
                "tags": tags or [],
                "publishStatus": "draft" if draft else "public",
            }

            r = await client.post(url, headers=self.headers, json=body)
            r.raise_for_status()
            res_data = r.json().get("data", {})

            return {
                "platform": "medium",
                "title": title,
                "url": res_data.get("url"),
                "status": res_data.get("publishStatus"),
            }
        
        raise RuntimeError("Medium publication failed.")

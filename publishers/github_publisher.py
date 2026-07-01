"""
LoopHive — GitHub Publisher

Ships an agent-built tool to a real GitHub repo (the portfolio engine), via the
GitHub REST API. Inert until GITHUB_TOKEN is set. Optionally targets an org
(GITHUB_ORG); otherwise publishes under the token owner's account.
"""

from __future__ import annotations

import base64
import os
import time

import httpx
import structlog

logger = structlog.get_logger(__name__)

API = "https://api.github.com"


def _slug(name: str) -> str:
    s = "".join(c if (c.isalnum() or c in "-_") else "-" for c in (name or "tool"))
    return s.strip("-").lower()[:80] or "tool"


async def publish_repo(name: str, files: dict[str, str], description: str = "") -> dict:
    """Create a public repo and commit ``files`` to it. Returns {status, url?}."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token or "your_" in token.lower():
        return {"status": "skipped", "reason": "github_not_configured"}
    org = os.getenv("GITHUB_ORG", "").strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Unique repo name so we never collide with an existing one.
    repo = f"{_slug(name)}-{int(time.time()) % 100000}"

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            if org:
                owner = org
                create_url = f"{API}/orgs/{org}/repos"
            else:
                me = await client.get(f"{API}/user", headers=headers)
                me.raise_for_status()
                owner = me.json()["login"]
                create_url = f"{API}/user/repos"

            create = await client.post(create_url, headers=headers, json={
                "name": repo,
                "description": (description or "Built autonomously by LoopHive")[:300],
                "private": False,
                "auto_init": False,
                "has_issues": True,
            })
            if create.status_code not in (200, 201):
                logger.warning("github_repo_create_failed", status=create.status_code, body=create.text[:200])
                return {"status": "error", "reason": create.text[:200]}

            committed = 0
            for path, content in files.items():
                b64 = base64.b64encode((content or "").encode("utf-8")).decode("ascii")
                put = await client.put(
                    f"{API}/repos/{owner}/{repo}/contents/{path}",
                    headers=headers,
                    json={"message": f"Add {path}", "content": b64},
                )
                if put.status_code in (200, 201):
                    committed += 1
                else:
                    logger.warning("github_file_commit_failed", path=path, status=put.status_code)

            url = f"https://github.com/{owner}/{repo}"
            logger.info("github_published", url=url, files=committed)
            return {"status": "published", "url": url, "files": committed}
    except Exception as e:
        logger.warning("github_publish_failed", error=str(e)[:200])
        return {"status": "error", "reason": str(e)[:200]}

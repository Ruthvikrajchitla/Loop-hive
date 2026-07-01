"""
LoopHive — Artifact Logging

One place to record every concrete piece of work an agent produces (research
briefs, posts, marketing copy, ...) so the dashboard can show it in full.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


async def log_artifact(agent_name: str, kind: str, title: str, content: str, url: str | None = None) -> None:
    """Persist an artifact. Never fatal."""
    try:
        from storage.database import async_session_factory, Artifact
        async with async_session_factory() as session:
            async with session.begin():
                session.add(Artifact(
                    agent_name=agent_name,
                    kind=kind,
                    title=(title or "")[:500],
                    content=content or "",
                    url=url,
                ))
    except Exception as e:
        logger.debug("artifact_log_failed", kind=kind, error=str(e)[:150])

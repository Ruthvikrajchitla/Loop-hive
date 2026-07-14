"""
LoopHive — Job Memory

CRUD for the resumable Job (Otto's working memory). Jobs are passed around as
plain dicts to avoid detached-ORM issues across async sessions.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

FIELDS = [
    "id", "kind", "request", "target_stage", "stage", "product_name", "build_type",
    "market_brief", "research_report", "plan", "files", "feedback", "round",
    "production_ready", "requester_email", "result_url", "delivered", "error",
]
DONE = ("done", "failed")


def _to_dict(job) -> dict:
    return {f: getattr(job, f) for f in FIELDS}


async def get_active_job() -> dict | None:
    """The next job to work on: boss tasks first, then any unfinished job (FIFO)."""
    try:
        from storage.database import async_session_factory, Job
        from sqlalchemy import select, case
        async with async_session_factory() as session:
            stmt = (
                select(Job).where(Job.stage.notin_(DONE))
                .order_by(case((Job.kind == "boss_task", 0), else_=1), Job.id)
                .limit(1)
            )
            job = (await session.execute(stmt)).scalars().first()
            return _to_dict(job) if job else None
    except Exception as e:
        logger.debug("get_active_job_failed", error=str(e)[:150])
        return None


async def create_job(**fields) -> dict | None:
    try:
        from storage.database import async_session_factory, Job
        async with async_session_factory() as session:
            async with session.begin():
                job = Job(**{k: v for k, v in fields.items() if k in FIELDS and k != "id"})
                session.add(job)
                await session.flush()
                d = _to_dict(job)
        logger.info("job_created", id=d["id"], kind=d["kind"], stage=d["stage"])
        return d
    except Exception as e:
        logger.error("create_job_failed", error=str(e)[:200])
        return None


async def save_job(job: dict) -> None:
    """Persist the current job state (memory checkpoint after each stage)."""
    try:
        from storage.database import async_session_factory, Job
        async with async_session_factory() as session:
            async with session.begin():
                row = await session.get(Job, job.get("id"))
                if not row:
                    return
                for f in FIELDS:
                    if f != "id" and f in job:
                        setattr(row, f, job[f])
    except Exception as e:
        logger.error("save_job_failed", error=str(e)[:200])


async def list_recent(limit: int = 30) -> list[dict]:
    try:
        from storage.database import async_session_factory, Job
        from sqlalchemy import select
        async with async_session_factory() as session:
            rows = (await session.execute(
                select(Job).order_by(Job.id.desc()).limit(limit)
            )).scalars().all()
            return [_to_dict(r) for r in rows]
    except Exception:
        return []

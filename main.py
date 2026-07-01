"""
LoopHive — Main Runner

Provides CLI commands to run the mission control dashboard or the autonomous
agent swarm. The swarm runs the three-tier loop engine continuously:

  - MicroLoop : every cycle  — full content→product→marketing pipeline
  - MesoLoop  : weekly       — strategy review over published content
  - MacroLoop : monthly      — niche evaluation (continue / pivot / kill)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import structlog
import uvicorn
from dotenv import load_dotenv

# Ensure local imports work
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.config import config
from core.loop_engine import MicroLoop, MesoLoop, MacroLoop, MacroDecision
from agents.orchestrator import OrchestratorAgent
from storage.database import init_db

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data helpers — read the DB so Meso/Macro operate on real state
# ---------------------------------------------------------------------------

async def _active_niche_name(default: str = "Notion Productivity") -> str:
    try:
        from storage.database import async_session_factory, Niche
        from sqlalchemy import select
        async with async_session_factory() as session:
            stmt = (
                select(Niche)
                .where(Niche.status == "active")
                .order_by(Niche.created_at.desc())
                .limit(1)
            )
            niche = (await session.execute(stmt)).scalar_one_or_none()
            if niche:
                return niche.name
    except Exception as e:
        logger.debug("active_niche_lookup_failed", error=str(e))
    return default


async def _published_content() -> list[dict]:
    """Published articles shaped for the MesoLoop's performance review."""
    try:
        from storage.database import async_session_factory, Content
        from sqlalchemy import select
        async with async_session_factory() as session:
            stmt = select(Content).where(Content.status == "published")
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "topic": c.title,
                    "engagement_score": c.engagement_seconds or c.views or 0,
                    "days_since_publish": 0,
                    "quality_score": c.quality_score,
                }
                for c in rows
            ]
    except Exception as e:
        logger.debug("published_content_lookup_failed", error=str(e))
        return []


async def _aggregate_kpis() -> dict:
    """Roll up the KPIs the MacroLoop needs from persisted state."""
    kpis: dict = {
        "traffic_trend_wow": 0.0,
        "avg_engagement_seconds": 0.0,
        "subscriber_growth_weekly": 0,
        "total_revenue": 0.0,
        "content_quality_avg": 0.0,
        "affiliate_clicks": 0,
        "articles_published": 0,
        "legal_issues": [],
    }
    try:
        from storage.database import async_session_factory, Content, Revenue
        from sqlalchemy import select, func
        async with async_session_factory() as session:
            published = select(Content).where(Content.status == "published")
            rows = (await session.execute(published)).scalars().all()
            kpis["articles_published"] = len(rows)
            if rows:
                kpis["content_quality_avg"] = sum(c.quality_score for c in rows) / len(rows)
                kpis["avg_engagement_seconds"] = sum(c.engagement_seconds for c in rows) / len(rows)
                kpis["affiliate_clicks"] = sum(c.affiliate_clicks for c in rows)
            total_rev = (await session.execute(select(func.sum(Revenue.amount)))).scalar()
            kpis["total_revenue"] = float(total_rev or 0.0)
    except Exception as e:
        logger.debug("kpi_aggregation_failed", error=str(e))
    return kpis


async def _today_counts() -> tuple[int, int]:
    """How many articles and products have been produced today (UTC)."""
    articles = products = 0
    try:
        import datetime
        from storage.database import async_session_factory, Content, Product
        from sqlalchemy import select, func
        now = datetime.datetime.utcnow()
        today = datetime.datetime(now.year, now.month, now.day)
        async with async_session_factory() as session:
            articles = (await session.execute(
                select(func.count(Content.id)).where(Content.created_at >= today)
            )).scalar() or 0
            products = (await session.execute(
                select(func.count(Product.id)).where(Product.created_at >= today)
            )).scalar() or 0
    except Exception as e:
        logger.debug("today_counts_failed", error=str(e))
    return articles, products


async def _outreach_count_today() -> int:
    """How many outreach attempts were logged today (UTC)."""
    try:
        import datetime
        from storage.database import async_session_factory, Outreach
        from sqlalchemy import select, func
        now = datetime.datetime.utcnow()
        today = datetime.datetime(now.year, now.month, now.day)
        async with async_session_factory() as session:
            return (await session.execute(
                select(func.count(Outreach.id)).where(Outreach.created_at >= today)
            )).scalar() or 0
    except Exception:
        return 0


async def _maybe_run_outreach(niche_name: str) -> None:
    """Run the capped, guarded, one-per-day outreach agent."""
    if not config.outreach_enabled:
        return
    if await _outreach_count_today() >= config.outreach_per_day:
        return
    from agents.outreach_agent import OutreachAgent
    from core.loop_engine import ContextWindow
    ctx = ContextWindow()
    ctx.add("system", f"niche: {niche_name}")
    res = await MicroLoop(max_iterations=1, timeout_seconds=300).run(
        OutreachAgent(), f"Find one person to help in {niche_name}", context=ctx
    )
    status = res.output.get("status") if isinstance(res.output, dict) else "?"
    print(f"  [Outreach] {status} (dry_run={config.outreach_dry_run})")


async def _apply_macro_decision(niche_name: str, decision: MacroDecision) -> None:
    """Persist the monthly verdict (pivot/kill flips the niche status)."""
    if decision == MacroDecision.CONTINUE:
        return
    new_status = "pivoted" if decision == MacroDecision.PIVOT else "killed"
    try:
        import datetime
        from storage.database import async_session_factory, Niche
        from sqlalchemy import select
        async with async_session_factory() as session:
            async with session.begin():
                stmt = select(Niche).where(Niche.name == niche_name)
                niche = (await session.execute(stmt)).scalar_one_or_none()
                if niche:
                    niche.status = new_status
                    niche.evaluated_at = datetime.datetime.utcnow()
                    niche.evaluation_decision = decision.value
        logger.info("macro_decision_applied", niche=niche_name, status=new_status)
    except Exception as e:
        logger.error("macro_decision_apply_failed", error=str(e))


# ---------------------------------------------------------------------------
# Swarm runner — the three-tier autonomous loop
# ---------------------------------------------------------------------------

async def run_swarm(continuous: bool = True, interval: float | None = None) -> None:
    """Run the autonomous agent swarm.

    With ``continuous=True`` it loops forever, sleeping ``interval`` seconds
    between micro cycles, and fires the weekly/monthly tiers on their schedules.
    With ``continuous=False`` it runs exactly one micro cycle (handy for CI/cron).
    """
    print("\n[LoopHive] Initializing Swarm Orchestrator...")
    await init_db()

    orchestrator = OrchestratorAgent()
    micro = MicroLoop(max_iterations=2, timeout_seconds=1800.0)
    meso = MesoLoop()
    macro = MacroLoop()

    if interval is None:
        interval = float(os.getenv("SWARM_INTERVAL_SECONDS", "3600"))
    meso_every = float(os.getenv("MESO_INTERVAL_SECONDS", str(7 * 86400)))
    macro_every = float(os.getenv("MACRO_INTERVAL_SECONDS", str(30 * 86400)))

    now = time.time()
    last_meso = now
    last_macro = now
    cycle = 0

    print("[LoopHive] Swarm initialized. Entering autonomous loop"
          + (" (single cycle)." if not continuous else f" (every {interval:.0f}s).") )

    target_articles = config.max_daily_articles
    target_products = config.max_daily_products
    idle_seconds = float(os.getenv("SWARM_IDLE_SECONDS", "1800"))  # re-check every 30 min when target met

    while True:
        # --- Daily target gate: build until quota met, then idle until tomorrow ---
        articles_today, products_today = await _today_counts()
        if articles_today >= target_articles and products_today >= target_products:
            logger.info(
                "daily_target_reached",
                articles=articles_today, products=products_today,
                target_articles=target_articles, target_products=target_products,
            )
            print(f"\n[LoopHive] Daily target met ({articles_today} articles, "
                  f"{products_today} products). Idling until the next day…")
            if not continuous:
                break
            await asyncio.sleep(idle_seconds)
            continue

        cycle += 1
        logger.info(
            "swarm_cycle_start", cycle=cycle,
            articles_today=articles_today, products_today=products_today,
            target_articles=target_articles, target_products=target_products,
        )

        # --- Tier 1: MicroLoop — run the full pipeline through perceive→verify ---
        res = await micro.run(
            orchestrator, "Run E2E pipeline for autonomous monetization"
        )
        report = res.output if isinstance(res.output, dict) else {}
        print(f"\n[LoopHive] Cycle {cycle} — status={res.status.value}")
        print(f"  Niche:    {report.get('niche', {}).get('name', 'Unknown')}")
        print(f"  Article:  {report.get('article_written', False)} "
              f"(quality {report.get('critic_score', 0)}, originality {report.get('originality_score', 0)})")
        print(f"  Product:  {report.get('product_created', False)}")
        print(f"  Channels: {report.get('marketing_channels', 0)}")

        niche_name = await _active_niche_name()
        now = time.time()

        # --- Tier 2: MesoLoop — weekly strategy review ---
        if now - last_meso >= meso_every:
            logger.info("swarm_meso_trigger", cycle=cycle)
            plan = await meso.run(niche_name, await _published_content())
            print(f"  [Meso] Weekly review: {len(plan.adjustments)} adjustment(s), "
                  f"{len(plan.content_briefs)} brief(s).")
            last_meso = now

        # --- Tier 3: MacroLoop — monthly niche evaluation ---
        if now - last_macro >= macro_every:
            logger.info("swarm_macro_trigger", cycle=cycle)
            evaluation = await macro.run(niche_name, await _aggregate_kpis())
            print(f"  [Macro] 30-day verdict for '{niche_name}': {evaluation.decision.value.upper()}")
            await _apply_macro_decision(niche_name, evaluation.decision)
            last_macro = now

        # --- Daily outreach (capped, guarded, transparent) ---
        await _maybe_run_outreach(niche_name)

        if not continuous:
            break
        await asyncio.sleep(interval)

    print("\n[LoopHive] Swarm run complete.")


def run_dashboard():
    """Start the mission control dashboard FastAPI application."""
    print("\n[LoopHive] Starting Swarm Dashboard at http://127.0.0.1:8000 ...")
    uvicorn.run(
        "dashboard.app:app",
        host=config.dashboard_host,
        port=config.dashboard_port,
        reload=True,
    )


if __name__ == "__main__":
    load_dotenv()

    parser = argparse.ArgumentParser(description="LoopHive Command Line Interface")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--swarm",
        action="store_true",
        help="Run the autonomous agent swarm continuously (MicroLoop + weekly/monthly tiers)",
    )
    group.add_argument(
        "--dashboard",
        action="store_true",
        help="Start the mission control dashboard (default)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="With --swarm, run a single cycle and exit instead of looping",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Seconds between micro cycles in continuous mode (default: SWARM_INTERVAL_SECONDS or 3600)",
    )

    args = parser.parse_args()

    if args.swarm:
        asyncio.run(run_swarm(continuous=not args.once, interval=args.interval))
    else:
        run_dashboard()

"""
LoopHive — Dashboard Routes

Real-time mission control. Every page reads live state from the database — there
is no hardcoded/mock data. Pages that have no data yet render explicit empty
states so you always know the true state of the swarm.

Live operational endpoints:
  - GET /api/live          → full live JSON snapshot
  - GET /dashboard/live    → overview live fragment (HTMX polled)
  - GET /agents/live       → agents live fragment (HTMX polled)
  - GET /fragments/topbar  → top bar niche + swarm status (HTMX polled)
"""

from __future__ import annotations

import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
import structlog

from core.llm_router import llm_router
from revenue.earnings_report import EarningsReport

logger = structlog.get_logger(__name__)

router = APIRouter()

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

report = EarningsReport()

# A "running" row older than this (no completion) is treated as stale, not live.
RUNNING_STALE_SECONDS = 600

# Ordered swarm pipeline. Each entry: agent_name → display metadata.
AGENT_META: list[dict] = [
    {"name": "niche_scout", "icon": "🔍", "stage": "Discovering niches",
     "description": "Scrapes trends and ranks high-intent commercial niches."},
    {"name": "legal_researcher", "icon": "⚖️", "stage": "Researching compliance",
     "description": "Investigates FTC / EU AI Act / platform rules for the niche."},
    {"name": "content_writer", "icon": "✍️", "stage": "Writing & revising the article",
     "description": "Drafts long-form articles and revises them on reviewer feedback."},
    {"name": "content_critic", "icon": "📝", "stage": "Reviewing draft quality",
     "description": "Scores drafts 0-100 on readability, depth, SEO and structure."},
    {"name": "plagiarism_checker", "icon": "🔎", "stage": "Checking originality",
     "description": "Runs originality detection; must clear the uniqueness gate."},
    {"name": "compliance_agent", "icon": "✅", "stage": "Injecting disclosures",
     "description": "Adds FTC affiliate and AI-content disclosures before publishing."},
    {"name": "product_creator", "icon": "📦", "stage": "Building the digital product",
     "description": "Synthesizes cheat sheets, guides and template packs."},
    {"name": "marketing_agent", "icon": "📣", "stage": "Creating the marketing campaign",
     "description": "Writes organic X / Reddit / LinkedIn launch copy."},
    {"name": "monthly_evaluator", "icon": "📊", "stage": "Evaluating niche KPIs",
     "description": "Aggregates KPIs and decides CONTINUE / PIVOT / KILL."},
]
AGENT_META_BY_NAME = {a["name"]: a for a in AGENT_META}
COORDINATOR_META = {"name": "orchestrator", "icon": "🧠", "stage": "Coordinating the pipeline",
                    "description": "Drives the specialist agents through the full lifecycle."}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_start() -> datetime.datetime:
    now = datetime.datetime.utcnow()
    return datetime.datetime(now.year, now.month, now.day)


def _ago(dt: datetime.datetime | None, now: datetime.datetime | None = None) -> str:
    if dt is None:
        return "—"
    now = now or datetime.datetime.utcnow()
    secs = max(0, int((now - dt).total_seconds()))
    if secs < 5:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _meta(name: str) -> dict:
    return AGENT_META_BY_NAME.get(name, COORDINATOR_META if name == "orchestrator"
                                  else {"name": name, "icon": "🤖", "stage": name, "description": ""})


def _agent_status(latest, now: datetime.datetime) -> str:
    """Derive a live status from an agent's most recent run."""
    if latest is None:
        return "idle"
    if latest.status == "running":
        started = latest.started_at or now
        if (now - started).total_seconds() <= RUNNING_STALE_SECONDS:
            return "running"
        return "idle"  # stale running (process likely stopped)
    if latest.status in ("failed", "aborted"):
        return "error"
    return "idle"


async def _live_state() -> dict:
    """Aggregate the full live snapshot of the swarm from the database."""
    from storage.database import (
        async_session_factory, AgentRun, Niche, Content, Product, MarketingCampaign,
    )
    from sqlalchemy import select, func, case

    now = datetime.datetime.utcnow()
    today = _today_start()

    state: dict = {
        "active_niche": "—",
        "active_agent": None,
        "project_stage": "Idle — awaiting next cycle",
        "current_topic": None,
        "current_task_started": None,
        "swarm_status": "idle",
        "agents": [],
        "stages": [],
        "timeline": [],
        "today": {"runs": 0, "tokens": 0, "articles": 0, "products": 0, "campaigns": 0, "successes": 0},
        "generated_at": now.isoformat(),
    }

    try:
        async with async_session_factory() as session:
            # Active niche
            niche = (await session.execute(
                select(Niche).where(Niche.status == "active")
                .order_by(Niche.created_at.desc()).limit(1)
            )).scalar_one_or_none()
            if niche:
                state["active_niche"] = niche.name

            # Latest run per agent (scan recent rows, keep first seen per agent)
            recent = (await session.execute(
                select(AgentRun).order_by(AgentRun.id.desc()).limit(500)
            )).scalars().all()
            latest_by_agent: dict = {}
            for r in recent:
                latest_by_agent.setdefault(r.agent_name, r)

            # Per-agent aggregates for today
            agg_rows = (await session.execute(
                select(
                    AgentRun.agent_name,
                    func.count(AgentRun.id),
                    func.sum(AgentRun.tokens_used),
                    func.sum(case((AgentRun.status == "success", 1), else_=0)),
                ).where(AgentRun.started_at >= today).group_by(AgentRun.agent_name)
            )).all()
            agg = {row[0]: {"runs": row[1] or 0, "tokens": int(row[2] or 0), "successes": row[3] or 0}
                   for row in agg_rows}

            # Build the agent cards (specialists + coordinator)
            for meta in AGENT_META + [COORDINATOR_META]:
                name = meta["name"]
                latest = latest_by_agent.get(name)
                a = agg.get(name, {"runs": 0, "tokens": 0, "successes": 0})
                status = _agent_status(latest, now)
                last_time = (latest.completed_at or latest.started_at) if latest else None
                sr = f"{int((a['successes'] / a['runs']) * 100)}%" if a["runs"] else "—"
                state["agents"].append({
                    "name": name,
                    "icon": meta["icon"],
                    "description": meta["description"],
                    "stage": meta["stage"],
                    "status": status,
                    "current_task": latest.task if (latest and status == "running") else None,
                    "last_task": latest.task if latest else None,
                    "last_status": latest.status if latest else None,
                    "last_run_ago": _ago(last_time, now),
                    "runs_today": a["runs"],
                    "tokens_today": a["tokens"],
                    "success_rate": sr,
                })

            # Current live activity = most recent fresh "running" row (prefer specialists)
            running = [r for r in recent if r.status == "running"
                       and r.started_at and (now - r.started_at).total_seconds() <= RUNNING_STALE_SECONDS]
            active = next((r for r in running if r.agent_name != "orchestrator"),
                          running[0] if running else None)
            if active:
                meta = _meta(active.agent_name)
                state["active_agent"] = active.agent_name
                state["project_stage"] = meta["stage"]
                state["current_topic"] = active.task
                state["current_task_started"] = _ago(active.started_at, now)
                state["swarm_status"] = "running"

            # Pipeline stage tracker (ordered specialists)
            for meta in AGENT_META:
                name = meta["name"]
                a = agg.get(name, {"successes": 0, "runs": 0})
                if name == state["active_agent"]:
                    st = "active"
                elif a["successes"] > 0:
                    st = "done"
                elif a["runs"] > 0:
                    st = "attempted"
                else:
                    st = "pending"
                state["stages"].append({"name": name, "icon": meta["icon"],
                                        "stage": meta["stage"], "state": st})

            # Today KPIs
            today_runs = sum(v["runs"] for v in agg.values())
            today_tokens = sum(v["tokens"] for v in agg.values())
            today_succ = sum(v["successes"] for v in agg.values())
            articles_today = (await session.execute(
                select(func.count(Content.id)).where(Content.created_at >= today)
            )).scalar() or 0
            products_today = (await session.execute(
                select(func.count(Product.id)).where(Product.created_at >= today)
            )).scalar() or 0
            campaigns_today = (await session.execute(
                select(func.count(MarketingCampaign.id)).where(MarketingCampaign.created_at >= today)
            )).scalar() or 0
            state["today"] = {
                "runs": today_runs, "tokens": today_tokens, "successes": today_succ,
                "articles": articles_today, "products": products_today, "campaigns": campaigns_today,
            }

            # Recent activity timeline
            for r in recent[:15]:
                meta = _meta(r.agent_name)
                state["timeline"].append({
                    "agent": r.agent_name,
                    "icon": meta["icon"],
                    "task": r.task or meta["stage"],
                    "status": r.status,
                    "tokens": r.tokens_used or 0,
                    "duration": round(r.duration_seconds or 0, 1),
                    "ago": _ago(r.completed_at or r.started_at, now),
                })
    except Exception as e:
        logger.error("live_state_failed", error=str(e))

    return state


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@router.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard")
async def get_dashboard(request: Request):
    state = await _live_state()
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={"live": state}
    )


@router.get("/dashboard/live")
async def get_dashboard_live(request: Request):
    """HTMX-polled live fragment for the overview page."""
    state = await _live_state()
    return templates.TemplateResponse(
        request=request, name="_overview_live.html", context={"live": state}
    )


@router.get("/fragments/topbar")
async def get_topbar(request: Request):
    state = await _live_state()
    return templates.TemplateResponse(
        request=request, name="_topbar.html", context={"live": state}
    )


@router.get("/agents")
async def get_agents(request: Request):
    state = await _live_state()
    llm_usage = llm_router.get_usage_summary()
    return templates.TemplateResponse(
        request=request, name="agents.html",
        context={"live": state, "llm_usage": llm_usage},
    )


@router.get("/agents/live")
async def get_agents_live(request: Request):
    state = await _live_state()
    llm_usage = llm_router.get_usage_summary()
    return templates.TemplateResponse(
        request=request, name="_agents_live.html",
        context={"live": state, "llm_usage": llm_usage},
    )


@router.get("/niches")
async def get_niches(request: Request):
    current_niche = None
    discovered_niches = []
    try:
        from storage.database import async_session_factory, Niche
        from sqlalchemy import select
        async with async_session_factory() as session:
            db_niches = (await session.execute(
                select(Niche).order_by(Niche.score.desc())
            )).scalars().all()
            for n in db_niches:
                n_data = {
                    "name": n.name,
                    "description": n.description or f"Niche guides for {n.name}.",
                    "score": round(n.score, 1),
                    "status": n.status,
                    "decision": n.evaluation_decision,
                }
                discovered_niches.append(n_data)
                if n.status == "active" and not current_niche:
                    current_niche = n_data
    except Exception as e:
        logger.error("query_niches_failed", error=str(e))

    return templates.TemplateResponse(
        request=request, name="niches.html",
        context={"current_niche": current_niche, "discovered_niches": discovered_niches},
    )


@router.get("/content")
async def get_content(request: Request):
    pipeline = {"draft": [], "review": [], "plagiarism": [], "compliance": [], "published": []}
    try:
        from storage.database import async_session_factory, Content
        from sqlalchemy import select
        async with async_session_factory() as session:
            db_contents = (await session.execute(
                select(Content).order_by(Content.created_at.desc())
            )).scalars().all()
            for c in db_contents:
                card = {
                    "title": c.title,
                    "score": round(c.quality_score, 0),
                    "originality": round(c.originality_score, 0),
                    "words": c.word_count or 0,
                    "url": c.published_url or "",
                }
                status = (c.status or "draft").lower()
                if status in ("draft", "drafting"):
                    pipeline["draft"].append(card)
                elif status in ("review", "in_review", "critic"):
                    pipeline["review"].append(card)
                elif status in ("plagiarism", "originality", "plag_check"):
                    pipeline["plagiarism"].append(card)
                elif status in ("compliance", "comply"):
                    pipeline["compliance"].append(card)
                else:
                    pipeline["published"].append(card)
    except Exception as e:
        logger.error("query_content_failed", error=str(e))

    return templates.TemplateResponse(
        request=request, name="content.html", context={"pipeline": pipeline}
    )


@router.get("/products")
async def get_products(request: Request):
    products = []
    try:
        from storage.database import async_session_factory, Product
        from sqlalchemy import select
        async with async_session_factory() as session:
            db_products = (await session.execute(
                select(Product).order_by(Product.created_at.desc())
            )).scalars().all()
            for p in db_products:
                products.append({
                    "id": p.id,
                    "name": p.name,
                    "type": p.product_type,
                    "price": p.price,
                    "sales": p.total_sales,
                    "revenue": p.total_revenue,
                    "platform": p.platform or "—",
                    "url": p.platform_url or "",
                    "status": p.status,
                    "has_content": bool(p.content),
                })
    except Exception as e:
        logger.error("query_products_failed", error=str(e))

    return templates.TemplateResponse(
        request=request, name="products.html", context={"products": products}
    )


@router.get("/products/{product_id}")
async def get_product_detail(request: Request, product_id: int):
    """View the full generated product content + sales copy for manual upload."""
    import markdown as md
    product = None
    try:
        from storage.database import async_session_factory, Product
        async with async_session_factory() as session:
            p = await session.get(Product, product_id)
            if p:
                product = {
                    "id": p.id,
                    "name": p.name,
                    "type": p.product_type,
                    "price": p.price,
                    "status": p.status,
                    "content_md": p.content or "",
                    "content_html": md.markdown(p.content or "", extensions=["tables", "fenced_code"]),
                    "sales_md": p.sales_page_copy or "",
                    "sales_html": md.markdown(p.sales_page_copy or "", extensions=["tables", "fenced_code"]),
                }
    except Exception as e:
        logger.error("product_detail_failed", error=str(e))

    if product is None:
        return RedirectResponse(url="/products")
    return templates.TemplateResponse(
        request=request, name="product_detail.html", context={"product": product}
    )


@router.get("/products/{product_id}/download")
async def download_product(product_id: int):
    """Download the product (body + sales copy) as a Markdown file for manual upload."""
    try:
        from storage.database import async_session_factory, Product
        async with async_session_factory() as session:
            p = await session.get(Product, product_id)
            if not p:
                return RedirectResponse(url="/products")
            slug = "".join(c if c.isalnum() else "-" for c in (p.name or "product")).strip("-").lower()
            doc = (
                f"# {p.name}\n\n_Type: {p.product_type} · Suggested price: ${p.price:.2f}_\n\n"
                f"{p.content or ''}\n\n"
                f"\n\n---\n\n# Sales Page Copy\n\n{p.sales_page_copy or ''}\n"
            )
            return Response(
                content=doc,
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
            )
    except Exception as e:
        logger.error("product_download_failed", error=str(e))
        return RedirectResponse(url="/products")


@router.get("/products/{product_id}/ebook.pdf")
async def download_product_pdf(product_id: int):
    """Render the product as a styled PDF ebook (with a Pexels cover) on demand."""
    try:
        from storage.database import async_session_factory, Product
        from publishers.ebook_builder import build_ebook_pdf
        async with async_session_factory() as session:
            p = await session.get(Product, product_id)
            if not p or not p.content:
                return RedirectResponse(url=f"/products/{product_id}")
            pdf = await build_ebook_pdf(
                title=p.name,
                content_md=p.content,
                subtitle=f"A LoopHive {p.product_type}",
                price=p.price,
                cover_query=p.name,
            )
            if not pdf:
                return RedirectResponse(url=f"/products/{product_id}")
            slug = "".join(c if c.isalnum() else "-" for c in (p.name or "ebook")).strip("-").lower()
            return Response(
                content=pdf,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{slug}.pdf"'},
            )
    except Exception as e:
        logger.error("product_pdf_failed", error=str(e))
        return RedirectResponse(url=f"/products/{product_id}")


@router.get("/content/{content_id}/download")
async def download_article(content_id: int):
    """Download a generated article as a Markdown file for manual publishing."""
    try:
        from storage.database import async_session_factory, Content
        async with async_session_factory() as session:
            c = await session.get(Content, content_id)
            if not c:
                return RedirectResponse(url="/content")
            slug = "".join(ch if ch.isalnum() else "-" for ch in (c.title or "article")).strip("-").lower()
            doc = f"# {c.title}\n\n{c.body or ''}\n"
            return Response(
                content=doc,
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
            )
    except Exception as e:
        logger.error("article_download_failed", error=str(e))
        return RedirectResponse(url="/content")


@router.get("/earnings")
async def get_earnings(request: Request):
    summary = await _earnings_summary()
    return templates.TemplateResponse(
        request=request, name="earnings.html", context={"summary": summary}
    )


@router.get("/compliance")
async def get_compliance(request: Request):
    rules = []
    try:
        from storage.database import async_session_factory, ComplianceRule
        from sqlalchemy import select
        async with async_session_factory() as session:
            db_rules = (await session.execute(
                select(ComplianceRule).order_by(ComplianceRule.researched_at.desc())
            )).scalars().all()
            for r in db_rules:
                rules.append({
                    "category": (r.category or "general").upper(),
                    "rule_text": r.rule,
                    "severity": r.severity,
                    "platform": r.platform or "all",
                })
    except Exception as e:
        logger.error("query_compliance_rules_failed", error=str(e))

    return templates.TemplateResponse(
        request=request, name="compliance.html", context={"rules": rules}
    )


@router.get("/onboarding")
async def get_onboarding(request: Request):
    steps = [
        {"num": 1, "task": "Create a Substack Newsletter", "desc": "Sign up on substack.com and note your username.", "done": False},
        {"num": 2, "task": "Register a Domain name", "desc": "Purchase a cheap domain (e.g. .xyz) on Namecheap for ~$1/yr.", "done": False},
        {"num": 3, "task": "Create a Cloudflare Account", "desc": "Sign up for Cloudflare free DNS services to point your domain.", "done": False},
        {"num": 4, "task": "Sign up on Gumroad or Payhip", "desc": "Create a merchant account to list products for sale.", "done": False},
        {"num": 5, "task": "Obtain API keys", "desc": "Get API keys for Gemini (AI Studio) and Groq (Groq Console).", "done": False},
    ]
    return templates.TemplateResponse(
        request=request, name="onboarding.html", context={"steps": steps}
    )


# ---------------------------------------------------------------------------
# JSON APIs
# ---------------------------------------------------------------------------

async def _earnings_summary() -> dict:
    """Real earnings from the Revenue table. Cost is $0 on free LLM tiers."""
    breakdown = {"products": 0.0, "affiliates": 0.0, "newsletter": 0.0, "ads": 0.0}
    total_revenue = 0.0
    source_map = {"product": "products", "affiliate": "affiliates",
                  "newsletter": "newsletter", "adsense": "ads"}
    try:
        from storage.database import async_session_factory, Revenue
        from sqlalchemy import select, func
        async with async_session_factory() as session:
            rows = (await session.execute(
                select(Revenue.source, func.sum(Revenue.amount)).group_by(Revenue.source)
            )).all()
            for src, amt in rows:
                amt = float(amt or 0.0)
                total_revenue += amt
                breakdown[source_map.get(src, "products")] = breakdown.get(source_map.get(src, "products"), 0.0) + amt
    except Exception as e:
        logger.error("earnings_summary_failed", error=str(e))

    return {
        "total_revenue": total_revenue,
        "total_cost": 0.0,
        "net_profit": total_revenue,
        "breakdown": breakdown,
    }


@router.get("/api/live")
async def api_live():
    return await _live_state()


@router.get("/api/stats")
async def get_api_stats():
    summary = await _earnings_summary()
    state = await _live_state()
    return {
        "total_revenue": f"${summary['total_revenue']:.2f}",
        "total_cost": f"${summary['total_cost']:.2f}",
        "net_profit": f"${summary['net_profit']:.2f}",
        "active_niche": state["active_niche"],
        "swarm_status": state["swarm_status"],
        "project_stage": state["project_stage"],
        "active_agent": state["active_agent"],
    }

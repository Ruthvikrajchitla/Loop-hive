"""
LoopHive — Dashboard Routes

Defines endpoints for pages (Overview, Niches, Content, Products, Earnings, Agents, Compliance, Onboarding)
and JSON APIs for HTMX polling updates.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.budget_manager import budget_manager
from revenue.earnings_report import EarningsReport
from core.llm_router import llm_router
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()

# Setup templates path
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

report = EarningsReport()


@router.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard")
async def get_dashboard(request: Request):
    summary = report.get_summary()
    weekly_chart = report.get_weekly_report()
    
    # Try querying actual data from database
    recent_content = []
    active_niche = "Notion Productivity"
    try:
        from storage.database import async_session_factory, Content, Product, Niche, AgentRun
        from sqlalchemy.future import select
        async with async_session_factory() as session:
            # Get active niche
            stmt = select(Niche).where(Niche.status == "active").order_by(Niche.created_at.desc()).limit(1)
            db_niche = (await session.execute(stmt)).scalar_one_or_none()
            if db_niche:
                active_niche = db_niche.name
            
            # Query latest articles
            stmt = select(Content).order_by(Content.created_at.desc()).limit(5)
            db_contents = (await session.execute(stmt)).scalars().all()
            for c in db_contents:
                recent_content.append({
                    "title": c.title,
                    "type": "Article",
                    "quality_score": c.quality_score,
                    "originality_score": c.originality_score,
                    "status": c.status,
                    "url": c.published_url or "https://substack.com",
                    "date": "Auto-Generated"
                })
            # Query latest products
            stmt = select(Product).order_by(Product.created_at.desc()).limit(5)
            db_products = (await session.execute(stmt)).scalars().all()
            for p in db_products:
                recent_content.append({
                    "title": p.name,
                    "type": "Product",
                    "quality_score": p.quality_score or 90.0,
                    "originality_score": p.originality_score or 95.0,
                    "status": p.status,
                    "url": p.platform_url or "https://gumroad.com",
                    "date": "Auto-Generated"
                })
    except Exception as e:
        logger.error("query_dashboard_failed", error=str(e))

    if not recent_content:
        # Mock data for fallback
        recent_content = [
            {
                "title": "10 Notion Hacks That Saved Me 5 Hours/Week",
                "type": "Article",
                "quality_score": 85.0,
                "originality_score": 92.0,
                "status": "published",
                "url": "https://substack.com",
                "date": "Placeholder"
            },
            {
                "title": "Ultimate Notion Productivity Planner Template",
                "type": "Product",
                "quality_score": 95.0,
                "originality_score": 98.0,
                "status": "published",
                "url": "https://gumroad.com",
                "date": "Placeholder"
            }
        ]

    # Query agent runs to get real stats
    agent_summary = [
        {"name": "niche_scout", "status": "idle", "success_rate": "100%", "tokens": 0},
        {"name": "legal_researcher", "status": "idle", "success_rate": "100%", "tokens": 0},
        {"name": "content_writer", "status": "idle", "success_rate": "100%", "tokens": 0},
        {"name": "content_critic", "status": "idle", "success_rate": "100%", "tokens": 0},
        {"name": "plagiarism_checker", "status": "idle", "success_rate": "100%", "tokens": 0},
        {"name": "compliance_agent", "status": "idle", "success_rate": "100%", "tokens": 0},
        {"name": "product_creator", "status": "idle", "success_rate": "100%", "tokens": 0},
        {"name": "marketing_agent", "status": "idle", "success_rate": "100%", "tokens": 0},
        {"name": "monthly_evaluator", "status": "idle", "success_rate": "100%", "tokens": 0},
    ]
    try:
        from storage.database import async_session_factory, AgentRun
        from sqlalchemy import func
        async with async_session_factory() as session:
            for item in agent_summary:
                stmt = select(
                    func.count(AgentRun.id),
                    func.sum(AgentRun.tokens_used),
                    func.count(AgentRun.id).filter(AgentRun.status == "success")
                ).where(AgentRun.agent_name == item["name"])
                res = (await session.execute(stmt)).fetchone()
                if res and res[0] > 0:
                    runs = res[0]
                    tokens = res[1] or 0
                    successes = res[2] or 0
                    item["success_rate"] = f"{int((successes / runs) * 100)}%"
                    item["tokens"] = int(tokens)
    except Exception as e:
        logger.error("query_agent_summary_failed", error=str(e))

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "summary": summary,
            "weekly_chart": weekly_chart,
            "recent_content": recent_content,
            "agents": agent_summary,
            "active_niche": active_niche,
            "next_eval_date": "28 days left",
        }
    )


@router.get("/niches")
async def get_niches(request: Request):
    current_niche = None
    discovered_niches = []

    try:
        from storage.database import async_session_factory, Niche
        from sqlalchemy.future import select
        async with async_session_factory() as session:
            stmt = select(Niche).order_by(Niche.score.desc())
            db_niches = (await session.execute(stmt)).scalars().all()
            for n in db_niches:
                n_data = {
                    "name": n.name,
                    "description": n.description or f"Niche guides for {n.name}.",
                    "score": n.score,
                    "status": n.status,
                    "traffic_trend": "+15.4% WoW",
                    "engagement": "124s avg",
                    "subscriber_growth": "+12/week"
                }
                discovered_niches.append(n_data)
                if n.status == "active":
                    current_niche = n_data
    except Exception as e:
        logger.error("query_niches_failed", error=str(e))

    if not current_niche:
        current_niche = {
            "name": "Notion Productivity",
            "description": "Niche Notion templates for remote freelancers and students to organize daily workflows.",
            "score": 92.5,
            "traffic_trend": "+15.4% WoW",
            "engagement": "124s avg",
            "subscriber_growth": "+12/week",
        }
    
    if not discovered_niches:
        discovered_niches = [
            {"name": "Notion Productivity", "score": 92.5, "status": "active"},
            {"name": "Home Espresso Guides", "score": 81.0, "status": "discovered"},
            {"name": "Excel Budget Trackers", "score": 78.4, "status": "discovered"},
        ]

    return templates.TemplateResponse(
        request=request,
        name="niches.html",
        context={
            "current_niche": current_niche,
            "discovered_niches": discovered_niches,
        }
    )


@router.get("/content")
async def get_content(request: Request):
    pipeline = {
        "draft": [],
        "review": [],
        "plagiarism": [],
        "compliance": [],
        "published": []
    }
    
    try:
        from storage.database import async_session_factory, Content
        from sqlalchemy.future import select
        async with async_session_factory() as session:
            stmt = select(Content).order_by(Content.created_at.desc())
            db_contents = (await session.execute(stmt)).scalars().all()
            for c in db_contents:
                card = {
                    "title": c.title,
                    "score": c.quality_score,
                    "originality": c.originality_score,
                    "words": c.word_count or 1500,
                    "url": c.published_url or "https://substack.com"
                }
                status = c.status.lower()
                if status in ["draft", "drafting"]:
                    pipeline["draft"].append(card)
                elif status in ["review", "in_review", "critic"]:
                    pipeline["review"].append(card)
                elif status in ["plagiarism", "originality", "plag_check"]:
                    pipeline["plagiarism"].append(card)
                elif status in ["compliance", "comply"]:
                    pipeline["compliance"].append(card)
                else: # published or approved
                    pipeline["published"].append(card)
    except Exception as e:
        logger.error("query_content_failed", error=str(e))

    if not any(pipeline.values()):
        # Kanban mockup fallback
        pipeline = {
            "draft": [
                {"title": "How to Automate Notion with Webhooks", "score": 0, "originality": 0, "words": 1500}
            ],
            "review": [
                {"title": "The Best Notion Templates for College Students", "score": 68.0, "originality": 0, "words": 1800}
            ],
            "plagiarism": [
                {"title": "5 Notion Templates Every Freelance Designer Needs", "score": 82.0, "originality": 94.0, "words": 2200}
            ],
            "compliance": [
                {"title": "How I Organize My Remote Writing business in Notion", "score": 85.0, "originality": 91.0, "words": 2400}
            ],
            "published": [
                {"title": "10 Notion Hacks That Saved Me 5 Hours/Week", "score": 85.0, "originality": 92.0, "words": 2100, "url": "https://substack.com"}
            ]
        }

    return templates.TemplateResponse(
        request=request,
        name="content.html",
        context={"pipeline": pipeline}
    )


@router.get("/products")
async def get_products(request: Request):
    products = []
    try:
        from storage.database import async_session_factory, Product
        from sqlalchemy.future import select
        async with async_session_factory() as session:
            stmt = select(Product).order_by(Product.created_at.desc())
            db_products = (await session.execute(stmt)).scalars().all()
            for p in db_products:
                products.append({
                    "name": p.name,
                    "type": p.product_type,
                    "price": p.price,
                    "sales": p.total_sales,
                    "revenue": p.total_revenue,
                    "platform": p.platform or "gumroad",
                    "url": p.platform_url or "https://gumroad.com",
                    "status": p.status
                })
    except Exception as e:
        logger.error("query_products_failed", error=str(e))

    if not products:
        products = [
            {
                "name": "Ultimate Notion Productivity Planner Template",
                "type": "template_pack",
                "price": 12.00,
                "sales": 1,
                "revenue": 12.00,
                "platform": "gumroad",
                "url": "https://gumroad.com",
                "status": "published"
            },
            {
                "name": "The Notion Power User Guide (Ebook)",
                "type": "ebook",
                "price": 6.00,
                "sales": 1,
                "revenue": 6.00,
                "platform": "payhip",
                "url": "https://payhip.com",
                "status": "published"
            }
        ]
    return templates.TemplateResponse(
        request=request,
        name="products.html",
        context={"products": products}
    )


@router.get("/earnings")
async def get_earnings(request: Request):
    summary = report.get_summary()
    return templates.TemplateResponse(
        request=request,
        name="earnings.html",
        context={"summary": summary}
    )


@router.get("/agents")
async def get_agents(request: Request):
    llm_usage = llm_router.get_usage_summary()
    
    agent_details = [
        {
            "name": "niche_scout",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Scrapes trends and discovers high-intent commercial niches."
        },
        {
            "name": "legal_researcher",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Investigates niche-specific laws and creates compliance policies."
        },
        {
            "name": "content_writer",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Drafts long-form, outline-based articles and newsletter content."
        },
        {
            "name": "content_critic",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Evaluates article drafts against readability and detail criteria."
        },
        {
            "name": "plagiarism_checker",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Checks written content originality using n-gram metrics."
        },
        {
            "name": "compliance_agent",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Injects required disclosures and ensures rules compliance."
        },
        {
            "name": "product_creator",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Synthesizes cheat sheets, PDF guides, and template packs."
        },
        {
            "name": "marketing_agent",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Drafts social media post campaigns and newsletter drafts."
        },
        {
            "name": "monthly_evaluator",
            "status": "idle",
            "runs": 0,
            "success_rate": "100%",
            "tokens": 0,
            "description": "Aggregates revenue and traffic metrics to continue or pivot niches."
        }
    ]

    try:
        from storage.database import async_session_factory, AgentRun
        from sqlalchemy import func
        async with async_session_factory() as session:
            for item in agent_details:
                stmt = select(
                    func.count(AgentRun.id),
                    func.sum(AgentRun.tokens_used),
                    func.count(AgentRun.id).filter(AgentRun.status == "success")
                ).where(AgentRun.agent_name == item["name"])
                res = (await session.execute(stmt)).fetchone()
                if res and res[0] > 0:
                    runs = res[0]
                    tokens = res[1] or 0
                    successes = res[2] or 0
                    item["runs"] = int(runs)
                    item["success_rate"] = f"{int((successes / runs) * 100)}%"
                    item["tokens"] = int(tokens)
    except Exception as e:
        logger.error("query_agents_page_failed", error=str(e))

    return templates.TemplateResponse(
        request=request,
        name="agents.html",
        context={
            "agents": agent_details,
            "llm_usage": llm_usage,
        }
    )


@router.get("/compliance")
async def get_compliance(request: Request):
    rules = []
    try:
        from storage.database import async_session_factory, ComplianceRule
        from sqlalchemy.future import select
        async with async_session_factory() as session:
            stmt = select(ComplianceRule).order_by(ComplianceRule.researched_at.desc())
            db_rules = (await session.execute(stmt)).scalars().all()
            for r in db_rules:
                rules.append({
                    "category": r.category.upper(),
                    "rule_text": r.rule,
                    "severity": r.severity
                })
    except Exception as e:
        logger.error("query_compliance_rules_failed", error=str(e))

    if not rules:
        rules = [
            {"category": "ftc", "rule_text": "All blog posts must include an affiliate link disclosure above the fold.", "severity": "required"},
            {"category": "eu_ai_act", "rule_text": "All AI-generated text must be tagged with visual and machine-readable markers.", "severity": "required"},
            {"category": "platform_tos", "rule_text": "Medium bans AI-generated articles from the Partner Program paywall.", "severity": "required"},
        ]
    return templates.TemplateResponse(
        request=request,
        name="compliance.html",
        context={"rules": rules}
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
        request=request,
        name="onboarding.html",
        context={"steps": steps}
    )


@router.get("/api/stats")
async def get_api_stats():
    summary = report.get_summary()
    return {
        "total_revenue": f"${summary['total_revenue']:.2f}",
        "total_cost": f"${summary['total_cost']:.2f}",
        "net_profit": f"${summary['net_profit']:.2f}",
        "active_niche": "Notion Productivity",
    }

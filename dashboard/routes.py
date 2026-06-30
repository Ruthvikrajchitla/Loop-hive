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
    
    # Mock data for frontend display
    recent_content = [
        {
            "title": "10 Notion Hacks That Saved Me 5 Hours/Week",
            "type": "Article",
            "quality_score": 85.0,
            "originality_score": 92.0,
            "status": "published",
            "url": "https://substack.com",
            "date": "2 hours ago"
        },
        {
            "title": "Ultimate Notion Productivity Planner Template",
            "type": "Product",
            "quality_score": 95.0,
            "originality_score": 98.0,
            "status": "published",
            "url": "https://gumroad.com",
            "date": "Yesterday"
        }
    ]

    agent_summary = [
        {"name": "niche_scout", "status": "idle", "success_rate": "100%", "tokens": 12400},
        {"name": "legal_researcher", "status": "idle", "success_rate": "100%", "tokens": 8500},
        {"name": "content_writer", "status": "idle", "success_rate": "90%", "tokens": 45300},
        {"name": "content_critic", "status": "idle", "success_rate": "100%", "tokens": 19400},
        {"name": "plagiarism_checker", "status": "idle", "success_rate": "100%", "tokens": 5800},
        {"name": "compliance_agent", "status": "idle", "success_rate": "100%", "tokens": 4200},
        {"name": "product_creator", "status": "idle", "success_rate": "95%", "tokens": 31200},
        {"name": "marketing_agent", "status": "idle", "success_rate": "100%", "tokens": 16000},
        {"name": "monthly_evaluator", "status": "idle", "success_rate": "100%", "tokens": 3000},
    ]

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "summary": summary,
            "weekly_chart": weekly_chart,
            "recent_content": recent_content,
            "agents": agent_summary,
            "active_niche": "Notion Productivity",
            "next_eval_date": "28 days left",
        }
    )


@router.get("/niches")
async def get_niches(request: Request):
    current_niche = {
        "name": "Notion Productivity",
        "description": "Niche Notion templates for remote freelancers and students to organize daily workflows.",
        "score": 92.5,
        "traffic_trend": "+15.4% WoW",
        "engagement": "124s avg",
        "subscriber_growth": "+12/week",
    }
    
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
    # Kanban mockup
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
            "runs": 2,
            "success_rate": "100%",
            "tokens": 12400,
            "description": "Scrapes trends and discovers high-intent commercial niches."
        },
        {
            "name": "legal_researcher",
            "status": "idle",
            "runs": 2,
            "success_rate": "100%",
            "tokens": 8500,
            "description": "Investigates niche-specific laws and creates compliance policies."
        },
        {
            "name": "content_writer",
            "status": "idle",
            "runs": 5,
            "success_rate": "90%",
            "tokens": 45300,
            "description": "Drafts long-form, outline-based articles and newsletter content."
        }
    ]
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

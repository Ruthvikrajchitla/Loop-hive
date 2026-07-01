"""
LoopHive — Database Models

SQLAlchemy models for persisting all system state:
niches, content, products, revenue, agent runs, and compliance.
"""

from __future__ import annotations

import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean, DateTime, JSON,
    ForeignKey, create_engine, Enum as SQLEnum,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from core.config import config

Base = declarative_base()


class Niche(Base):
    """A discovered niche the system is working on or has evaluated."""
    __tablename__ = "niches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    score = Column(Float, default=0.0)  # Discovery score
    status = Column(String(50), default="discovered")  # discovered, active, pivoted, killed
    started_at = Column(DateTime, nullable=True)
    evaluated_at = Column(DateTime, nullable=True)
    evaluation_decision = Column(String(50), nullable=True)  # continue, pivot, kill
    evaluation_reasoning = Column(Text, nullable=True)
    kpis = Column(JSON, default=dict)
    keywords = Column(JSON, default=list)  # Top keywords for this niche
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    content = relationship("Content", back_populates="niche")
    products = relationship("Product", back_populates="niche")


class Content(Base):
    """A piece of content (article, newsletter issue, social post)."""
    __tablename__ = "content"

    id = Column(Integer, primary_key=True, autoincrement=True)
    niche_id = Column(Integer, ForeignKey("niches.id"), nullable=True)
    title = Column(String(500), nullable=False)
    content_type = Column(String(50), default="article")  # article, newsletter, social_post
    body = Column(Text, default="")
    meta_description = Column(String(300), default="")
    keywords = Column(JSON, default=list)
    word_count = Column(Integer, default=0)

    # Quality scores
    quality_score = Column(Float, default=0.0)  # 0-100 from Content Critic
    originality_score = Column(Float, default=0.0)  # 0-100 from Plagiarism Checker
    readability_score = Column(Float, default=0.0)  # Flesch-Kincaid

    # Publishing
    status = Column(String(50), default="draft")  # draft, review, approved, published, rejected
    published_platform = Column(String(100), nullable=True)
    published_url = Column(String(500), nullable=True)
    published_at = Column(DateTime, nullable=True)

    # Analytics
    views = Column(Integer, default=0)
    engagement_seconds = Column(Float, default=0.0)
    affiliate_clicks = Column(Integer, default=0)
    revenue_generated = Column(Float, default=0.0)

    # Compliance
    has_ai_disclosure = Column(Boolean, default=False)
    has_affiliate_disclosure = Column(Boolean, default=False)
    compliance_checked = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    niche = relationship("Niche", back_populates="content")


class Product(Base):
    """A digital product created for sale."""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    niche_id = Column(Integer, ForeignKey("niches.id"), nullable=True)
    name = Column(String(300), nullable=False)
    product_type = Column(String(50), default="ebook")  # ebook, template_pack, prompt_pack, etc.
    description = Column(Text, default="")
    price = Column(Float, default=0.0)
    file_path = Column(String(500), nullable=True)
    content = Column(Text, default="")        # Full product body (the deliverable buyers get)
    sales_page_copy = Column(Text, default="")

    # Distribution
    platform = Column(String(100), nullable=True)  # gumroad, payhip
    platform_url = Column(String(500), nullable=True)
    status = Column(String(50), default="draft")  # draft, review, published

    # Sales metrics
    total_sales = Column(Integer, default=0)
    total_revenue = Column(Float, default=0.0)

    # Quality
    quality_score = Column(Float, default=0.0)
    originality_score = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    niche = relationship("Niche", back_populates="products")


class Revenue(Base):
    """Revenue tracking — every dollar earned."""
    __tablename__ = "revenue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(100), nullable=False)  # affiliate, product, newsletter, adsense
    amount = Column(Float, nullable=False)
    description = Column(String(500), default="")
    content_id = Column(Integer, ForeignKey("content.id"), nullable=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    recorded_at = Column(DateTime, default=datetime.datetime.utcnow)


class AgentRun(Base):
    """Logs every agent execution for monitoring and debugging."""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(100), nullable=False)
    task = Column(String(500), default="")
    status = Column(String(50), default="running")  # running, success, failed, aborted
    iterations_used = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    duration_seconds = Column(Float, default=0.0)
    result_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ComplianceRule(Base):
    """Compliance rules discovered by the Legal Research Agent."""
    __tablename__ = "compliance_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(100), nullable=False)  # ftc, eu_ai_act, platform_tos, niche_specific
    platform = Column(String(100), nullable=True)  # medium, substack, amazon, etc.
    rule = Column(Text, nullable=False)
    severity = Column(String(50), default="required")  # required, recommended, optional
    disclosure_template = Column(Text, nullable=True)
    source_url = Column(String(500), nullable=True)
    researched_at = Column(DateTime, default=datetime.datetime.utcnow)


class MarketingCampaign(Base):
    """Marketing campaigns for products and content."""
    __tablename__ = "marketing_campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(300), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    content_id = Column(Integer, ForeignKey("content.id"), nullable=True)
    channels = Column(JSON, default=list)  # ["x", "reddit", "linkedin", "email"]
    status = Column(String(50), default="planned")  # planned, active, completed
    posts_created = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Outreach(Base):
    """One transparent, value-first outreach attempt (draft or sent)."""
    __tablename__ = "outreach"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target = Column(String(300), default="")        # who/what the opportunity is
    target_url = Column(String(500), nullable=True)  # the public request/post
    recipient_email = Column(String(300), nullable=True)
    subject = Column(String(300), default="")
    body = Column(Text, default="")
    status = Column(String(50), default="draft")     # draft, sent, skipped, error
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Artifact(Base):
    """Any concrete piece of work an agent produced — so it's fully viewable."""
    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(100), default="")
    kind = Column(String(60), default="")           # research_brief, telegram_post, marketing_copy, ...
    title = Column(String(500), default="")
    content = Column(Text, default="")
    url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Notification(Base):
    """An escalation to the boss (human owner)."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(20), default="info")      # info, critical
    title = Column(String(300), default="")
    body = Column(Text, default="")
    source = Column(String(100), default="")        # which agent/stage raised it
    status = Column(String(30), default="unread")   # unread, read
    emailed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class InboxMessage(Base):
    """An incoming email the agent read, understood, and acted on."""
    __tablename__ = "inbox_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sender = Column(String(300), default="")
    subject = Column(String(500), default="")
    body = Column(Text, default="")
    intent = Column(String(50), default="other")   # opt_out, interested, question, build_task, modification, other
    action_summary = Column(Text, nullable=True)    # what the agent did about it
    reply_draft = Column(Text, nullable=True)
    status = Column(String(50), default="drafted")  # drafted, replied, suppressed, actioned, error
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Suppression(Base):
    """Emails that opted out (Reply STOP) — never contact again."""
    __tablename__ = "suppressions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(300), nullable=False)
    reason = Column(String(200), default="opt_out")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ---------------------------------------------------------------------------
# Database engine and session
# ---------------------------------------------------------------------------

async_engine = create_async_engine(config.db_url, echo=False)
async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables and apply lightweight column migrations."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent migrations for columns added after the initial release so
        # existing SQLite databases keep working without a manual rebuild.
        if "sqlite" in config.db_url:
            await _ensure_column(conn, "products", "content", "TEXT")


async def _ensure_column(conn, table: str, column: str, coltype: str) -> None:
    """Add a column to an existing SQLite table if it isn't there yet."""
    try:
        res = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        existing = [row[1] for row in res.fetchall()]
        if column not in existing:
            await conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"
            )
    except Exception:
        pass


async def get_session() -> AsyncSession:
    """Get an async database session."""
    async with async_session_factory() as session:
        yield session

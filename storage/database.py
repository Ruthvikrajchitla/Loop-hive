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


# ---------------------------------------------------------------------------
# Database engine and session
# ---------------------------------------------------------------------------

async_engine = create_async_engine(config.db_url, echo=False)
async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Get an async database session."""
    async with async_session_factory() as session:
        yield session

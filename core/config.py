"""LoopHive — Core configuration module."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _resolve_db_url() -> str:
    """Resolve DATABASE_URL, normalizing Postgres URLs to the async driver.

    Render/Heroku hand out `postgres://...` connection strings; SQLAlchemy's async
    engine needs `postgresql+asyncpg://...`. This lets you paste Render's Postgres
    URL straight into the DATABASE_URL env var to survive deploys (SQLite on
    Render's ephemeral disk is wiped on every restart). Defaults to local SQLite.
    """
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./loophive.db")
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


def _resolve_topics() -> list[str]:
    """Content/product topics within the niche. Override with TOPIC_POOL (| separated)."""
    raw = os.getenv("TOPIC_POOL", "")
    if raw.strip():
        return [t.strip() for t in raw.split("|") if t.strip()]
    # Default "AI Hub" rotation — varied formats + subjects so content isn't repetitive.
    return [
        "The best AI tools for content creation in 2026",
        "How to build an agentic research workflow step by step",
        "The complete prompt engineering guide for professionals",
        "Top AI automation tools to save 10+ hours a week",
        "Setting up your first AI agent stack: a beginner's guide",
        "Best AI coding assistants compared",
        "How to automate your marketing with AI agents",
        "The complete guide to RAG and AI knowledge bases",
        "AI productivity systems for knowledge workers",
        "Best free AI tools every founder should know",
        "How to chain AI agents into an end-to-end workflow",
        "The ultimate ChatGPT + Claude prompt playbook",
    ]


@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM provider."""
    name: str
    api_key: str
    base_url: str
    model: str
    max_rpm: int  # Requests per minute
    max_rpd: int  # Requests per day
    max_tpm: int  # Tokens per minute
    priority: int  # Lower = higher priority in cascade
    supports_json: bool = True
    supports_streaming: bool = True
    quality: bool = True  # Strong enough for writing? Weak models (e.g. 8B) set False.


@dataclass
class AppConfig:
    """Global application configuration."""

    # Paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    db_url: str = field(default_factory=_resolve_db_url)

    # Dashboard
    dashboard_host: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_HOST", "0.0.0.0")
    )
    dashboard_port: int = field(
        default_factory=lambda: int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8000")))
    )

    # Quality thresholds
    quality_threshold: int = field(
        default_factory=lambda: int(os.getenv("QUALITY_THRESHOLD", "70"))
    )
    plagiarism_threshold: int = field(
        default_factory=lambda: int(os.getenv("PLAGIARISM_THRESHOLD", "85"))
    )

    # Niche focus — force the swarm onto one niche instead of re-discovering each cycle.
    # Empty string lets the NicheScout discover niches as before.
    forced_niche: str = field(
        default_factory=lambda: os.getenv(
            "FORCED_NICHE", "AI Tools, Agentic Workflows & Prompt Engineering"
        )
    )
    topic_pool: list[str] = field(default_factory=_resolve_topics)

    # Deep research (topic research agent)
    research_enabled: bool = field(
        default_factory=lambda: os.getenv("RESEARCH_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    research_depth: int = field(  # how many search queries / source batches to gather
        default_factory=lambda: int(os.getenv("RESEARCH_DEPTH", "4"))
    )
    research_max_sources: int = field(
        default_factory=lambda: int(os.getenv("RESEARCH_MAX_SOURCES", "8"))
    )

    # Mixture-of-Agents "fusion" writing — several models draft, an aggregator fuses.
    fusion_enabled: bool = field(
        default_factory=lambda: os.getenv("FUSION_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    fusion_proposers: int = field(  # number of independent drafts to fuse
        default_factory=lambda: int(os.getenv("FUSION_PROPOSERS", "3"))
    )
    fusion_aggregator: str = field(  # provider name that fuses the drafts ("" = auto)
        default_factory=lambda: os.getenv("FUSION_AGGREGATOR", "nvidia-ultra")
    )
    # Final editorial pass — the premium model that produces the FINAL product draft.
    finalize_enabled: bool = field(
        default_factory=lambda: os.getenv("FINALIZE_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    finalize_provider: str = field(
        default_factory=lambda: os.getenv("FINALIZE_PROVIDER", "nvidia-ultra")
    )

    # Code products — the swarm builds real tools, tests them in a sandbox, and
    # ships the working ones to a GitHub org (the portfolio engine).
    code_products_enabled: bool = field(
        default_factory=lambda: os.getenv("CODE_PRODUCTS_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    code_product_every: int = field(  # build a code tool every N cycles
        default_factory=lambda: int(os.getenv("CODE_PRODUCT_EVERY", "3"))
    )
    sandbox_timeout: int = field(
        default_factory=lambda: int(os.getenv("SANDBOX_TIMEOUT", "60"))
    )
    code_refine_rounds: int = field(  # self-heal loops when the sandbox reports errors
        default_factory=lambda: int(os.getenv("CODE_REFINE_ROUNDS", "2"))
    )

    # Outreach — ONE transparent, value-first message per day. Off + dry-run by
    # default: it composes and stores drafts for review; it only actually sends
    # when OUTREACH_ENABLED=true AND OUTREACH_DRY_RUN=false AND SMTP creds exist.
    outreach_enabled: bool = field(
        default_factory=lambda: os.getenv("OUTREACH_ENABLED", "false").lower() in ("1", "true", "yes")
    )
    outreach_dry_run: bool = field(
        default_factory=lambda: os.getenv("OUTREACH_DRY_RUN", "true").lower() in ("1", "true", "yes")
    )
    outreach_per_day: int = field(
        default_factory=lambda: int(os.getenv("OUTREACH_PER_DAY", "1"))
    )

    # Ebook rendering & length (long-form products are generated chapter-by-chapter)
    ebook_pdf_enabled: bool = field(
        default_factory=lambda: os.getenv("EBOOK_PDF_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    ebook_min_sections: int = field(  # chapters for a long-form product (ebook/guide/playbook)
        default_factory=lambda: int(os.getenv("EBOOK_MIN_SECTIONS", "12"))
    )
    ebook_section_words: int = field(  # target words per chapter
        default_factory=lambda: int(os.getenv("EBOOK_SECTION_WORDS", "900"))
    )

    # Content limits
    max_daily_articles: int = field(
        default_factory=lambda: int(os.getenv("MAX_DAILY_ARTICLES", "5"))
    )
    max_daily_products: int = field(
        default_factory=lambda: int(os.getenv("MAX_DAILY_PRODUCTS", "2"))
    )
    max_weekly_products: int = field(
        default_factory=lambda: int(os.getenv("MAX_WEEKLY_PRODUCTS", "1"))
    )

    # Logging
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )

    # Monthly evaluation
    evaluation_period_days: int = 30
    min_traffic_trend_weeks: int = 2  # Weeks of declining traffic before pivot
    min_subscriber_growth_week: int = 5  # Min new subscribers/week to continue

    def get_llm_providers(self) -> list[LLMProviderConfig]:
        """Get all configured LLM providers, sorted by priority."""
        providers = []

        # Priority 1: Google Gemini (most generous free tier)
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            providers.append(LLMProviderConfig(
                name="gemini",
                api_key=gemini_key,
                base_url="https://generativelanguage.googleapis.com/v1beta",
                model="gemini-2.0-flash",
                max_rpm=15,
                max_rpd=1500,
                max_tpm=1_000_000,
                priority=1,
            ))

        # Priority 2: Groq (blazing fast, good free tier)
        groq_key = os.getenv("GROQ_API_KEY", "")
        if groq_key:
            providers.append(LLMProviderConfig(
                name="groq-fast",
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
                model="llama-3.1-8b-instant",
                max_rpm=30,
                max_rpd=14400,
                max_tpm=6000,
                priority=2,
                quality=False,  # Fast but weak at long-form prose — kept off writing tasks.
            ))
            providers.append(LLMProviderConfig(
                name="groq-smart",
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
                model="llama-3.3-70b-versatile",
                max_rpm=30,
                max_rpd=1000,
                max_tpm=12000,
                priority=3,
            ))

        # NVIDIA NIM (build.nvidia.com) — free Nemotron models.
        #  - nvidia-nemotron : Nemotron-Super-49B, the fast quality workhorse
        #  - nvidia-ultra    : Nemotron-Ultra-550B, premium model used as the
        #                      fusion aggregator (slow/reasoning; low cascade priority)
        nvidia_key = os.getenv("NVIDIA_API_KEY", "")
        if nvidia_key:
            providers.append(LLMProviderConfig(
                name="nvidia-nemotron",
                api_key=nvidia_key,
                base_url="https://integrate.api.nvidia.com/v1",
                model=os.getenv("NVIDIA_NEMOTRON_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1"),
                max_rpm=40,
                max_rpd=1000,
                max_tpm=100000,
                priority=3,
            ))
            providers.append(LLMProviderConfig(
                name="nvidia-ultra",
                api_key=nvidia_key,
                base_url="https://integrate.api.nvidia.com/v1",
                model=os.getenv("NVIDIA_ULTRA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
                max_rpm=20,
                max_rpd=300,
                max_tpm=200000,
                priority=9,  # last resort in the normal cascade — it's slow
            ))

        # Priority 4: OpenRouter (free reasoning models). Model id is env-overridable
        # because OpenRouter's free model ids change often (set OPENROUTER_MODEL to a
        # current ':free' model from openrouter.ai/models, e.g. a Qwen/Kimi/DeepSeek one).
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if openrouter_key:
            providers.append(LLMProviderConfig(
                name="openrouter",
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
                model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
                max_rpm=20,
                max_rpd=200,
                max_tpm=50000,
                priority=5,
            ))

        # Priority 5: Cerebras
        cerebras_key = os.getenv("CEREBRAS_API_KEY", "")
        if cerebras_key:
            providers.append(LLMProviderConfig(
                name="cerebras",
                api_key=cerebras_key,
                base_url="https://api.cerebras.ai/v1",
                model="gpt-oss-120b",
                max_rpm=5,
                max_rpd=500,
                max_tpm=30000,
                priority=5,
            ))

        # Priority 6: xAI Grok
        xai_key = os.getenv("XAI_API_KEY", "")
        if xai_key:
            providers.append(LLMProviderConfig(
                name="grok",
                api_key=xai_key,
                base_url="https://api.x.ai/v1",
                model="grok-3-mini",
                max_rpm=15,
                max_rpd=1000,
                max_tpm=100000,
                priority=6,
            ))

        return sorted(providers, key=lambda p: p.priority)


# Global config singleton
config = AppConfig()

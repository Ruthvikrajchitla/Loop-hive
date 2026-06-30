"""LoopHive — Core configuration module."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


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


@dataclass
class AppConfig:
    """Global application configuration."""

    # Paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    db_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///./loophive.db"
        )
    )

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

    # Content limits
    max_daily_articles: int = field(
        default_factory=lambda: int(os.getenv("MAX_DAILY_ARTICLES", "5"))
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

        # Priority 4: OpenRouter (free reasoning models)
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if openrouter_key:
            providers.append(LLMProviderConfig(
                name="openrouter",
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
                model="deepseek/deepseek-r1:free",
                max_rpm=20,
                max_rpd=200,
                max_tpm=50000,
                priority=4,
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

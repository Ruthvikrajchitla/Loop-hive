"""
LoopHive — Analyzer Agent (Market Analyst)

Scans the market across the web, Reddit, Twitter/X, and Quora to find what people
are actually struggling with or asking to be built, spots trends, and hands the
team a market brief + one concrete product idea worth building.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.config import config
from core.loop_engine import ContextWindow, Verification
from core.research_tools import gather_sources

logger = structlog.get_logger(__name__)


class AnalyzerAgent(AgentBase):
    """Finds trending, in-demand product ideas from real market signals."""

    def __init__(self, router=None):
        super().__init__(
            name="analyzer_agent",
            description="Analyzes market trends and unmet needs across the web, Reddit, Twitter, and Quora.",
            system_prompt=(
                "You are a sharp market analyst. You read real signals from communities (Reddit, X, Quora, "
                "forums), identify genuine unmet needs and trends, and separate hype from durable demand. "
                "You recommend concrete, buildable products people would actually use or pay for."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        self.mark_running()
        niche = config.forced_niche or "AI tools & developer productivity"
        return {"timestamp": time.time(), "niche": niche}

    async def reason(self, state: dict, goal: str) -> dict:
        niche = state["niche"]
        queries = [
            f"{niche} reddit what people wish existed 2026",
            f'"i wish there was a tool" OR "someone should build" {niche}',
            f"most requested {niche} tools twitter 2026",
            f"biggest problems {niche} quora",
            f"trending {niche} product ideas 2026",
            f"{niche} people struggling with — reddit",
        ]
        return {"niche": niche, "queries": queries[: max(3, config.research_depth)]}

    async def act(self, plan: dict) -> dict:
        niche = plan["niche"]
        sources: list[dict] = []
        for q in plan["queries"]:
            sources.extend(await gather_sources(q, max_sources=4))
        # De-dup
        seen, uniq = set(), []
        for s in sources:
            k = (s.get("url") or s.get("title") or "").lower()
            if k and k not in seen and s.get("content"):
                seen.add(k)
                uniq.append(s)
        uniq = uniq[: config.research_max_sources]
        logger.info("market_signals_gathered", niche=niche, sources=len(uniq))

        corpus = "\n\n".join(
            f"SOURCE ({s['source']}): {s['title']}\n{s['content'][:1500]}" for s in uniq
        )[:20000] or "No external signals retrieved; use your own market expertise."

        result = await self.ask_llm_json(
            f"Niche: {niche}\n\nMarket signals:\n{corpus}\n\n"
            f"Analyze the demand and recommend ONE concrete, buildable software product (a tool, browser "
            f"extension, website, or small app) that addresses a real, recurring pain point.\n\n"
            f"Output JSON: {{'market_report': str (markdown: trends, top pain points, who has them, "
            f"why now), 'product_name': str, 'product_idea': str (one paragraph: what to build and for whom), "
            f"'build_type': 'developer tool|browser extension|static website|python package|github starter kit'}}",
            temperature=0.4, max_tokens=2500,
        )
        result["source_count"] = len(uniq)
        self.mark_success({"product_name": result.get("product_name"), "sources": len(uniq)})
        return result

    async def verify(self, result: Any, goal: str) -> Verification:
        if not isinstance(result, dict) or not result.get("product_idea") or "error" in result:
            return Verification(is_complete=False, should_retry=True,
                                feedback="Produce a market report and one concrete product idea.",
                                reason="No product idea.")
        return Verification(is_complete=True, score=92.0,
                            feedback=f"Market brief ready; recommended: {result.get('product_name')}.")

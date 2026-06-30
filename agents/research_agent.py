"""
LoopHive — Deep Research Agent

Researches the actual TOPIC (not just legal rules). For a topic in the niche it:
  1. Plans several targeted search queries
  2. Gathers real sources from the web (Tavily) + academic papers (arXiv)
  3. Synthesizes everything into a structured research brief

The brief is handed to the writer so it composes from real sources, not memory —
the core quality lever. Works with no key (arXiv only); richer with TAVILY_API_KEY.
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


class ResearchBrief(dict):
    """Just a dict tag so the loop/orchestrator can recognize the output."""


class DeepResearchAgent(AgentBase):
    """Gathers and synthesizes real research on a topic before any writing happens."""

    def __init__(self, router=None):
        super().__init__(
            name="research_agent",
            description="Researches the topic across the web and papers, then writes a source-backed brief.",
            system_prompt=(
                "You are a meticulous research analyst. You read sources carefully, extract concrete "
                "facts, statistics, trends, tools, and differing viewpoints, and you never invent data. "
                "You produce dense, well-structured research briefs that a writer can turn into an "
                "authoritative, original article or ebook."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        """Read the niche and topic from context."""
        self.mark_running()
        niche = config.forced_niche or "AI Tools & Workflows"
        topic = ""
        for entry in reversed(context.entries):
            for line in entry["content"].split("\n"):
                low = line.lower().strip()
                if low.startswith("niche:"):
                    niche = line.split(":", 1)[1].strip() or niche
                elif low.startswith("topic:"):
                    topic = line.split(":", 1)[1].strip() or topic
                elif "Goal:" in line and not topic:
                    topic = line.split("Goal:", 1)[1].strip()
        return {"timestamp": time.time(), "niche": niche, "topic": topic or niche}

    async def reason(self, state: dict, goal: str) -> dict:
        """Plan targeted search queries for the topic."""
        topic = state["topic"]
        niche = state["niche"]
        queries = [
            topic,
            f"{topic} 2026 latest",
            f"best tools for {topic}",
            f"{topic} comparison and pricing",
            f"{topic} statistics and adoption",
            f"how to {topic}",
            f"{topic} common mistakes",
        ]
        return {
            "topic": topic,
            "niche": niche,
            "queries": queries[: max(1, config.research_depth)],
        }

    async def act(self, plan: dict) -> ResearchBrief:
        """Gather sources, then synthesize a research brief."""
        topic = plan["topic"]
        niche = plan["niche"]
        queries = plan["queries"]

        # 1. Gather sources across queries.
        per_query = max(2, config.research_max_sources // max(1, len(queries)))
        all_sources: list[dict] = []
        for q in queries:
            all_sources.extend(await gather_sources(q, max_sources=per_query))

        # De-dup across queries and cap total.
        seen: set[str] = set()
        sources: list[dict] = []
        for s in all_sources:
            key = (s.get("url") or s.get("title") or "").lower()
            if key and key not in seen:
                seen.add(key)
                sources.append(s)
        sources = sources[: config.research_max_sources]

        logger.info("research_gathered", topic=topic[:80], sources=len(sources), queries=len(queries))

        # 2. Synthesize into a structured brief (cite source titles).
        if sources:
            corpus = "\n\n".join(
                f"SOURCE [{i+1}] ({s['source']}): {s['title']}\nURL: {s['url']}\n{s['content']}"
                for i, s in enumerate(sources)
            )[:24000]
            synth_prompt = (
                f"Topic: {topic}\nNiche: {niche}\n\n"
                f"Using ONLY the sources below, write a dense research brief for a writer who will create "
                f"an authoritative, original guide/ebook on this topic. Structure it as Markdown with:\n"
                f"## Key Facts & Statistics (cite the source number)\n"
                f"## Current Trends (2025-2026)\n"
                f"## Tools / Examples / Case Studies\n"
                f"## Audience Pain Points & Common Questions\n"
                f"## Differing Viewpoints or Pitfalls\n"
                f"## Recommended Article/Ebook Outline (with section headings)\n\n"
                f"Be concrete and specific — pull out numbers, names, and quotes. Do not invent facts "
                f"that aren't in the sources.\n\nSOURCES:\n{corpus}"
            )
        else:
            # No external sources available — still produce a strong brief from expertise.
            synth_prompt = (
                f"No external sources were retrievable. Write a thorough, expert research brief for a "
                f"writer creating an authoritative guide/ebook on '{topic}' within the '{niche}' niche. "
                f"Use Markdown with sections: Key Facts, Current Trends (2025-2026), Tools/Examples, "
                f"Audience Pain Points & Questions, Pitfalls, and a Recommended Outline. Be concrete and "
                f"avoid generic filler."
            )

        report = await self.ask_llm(synth_prompt, temperature=0.4, max_tokens=4096)

        brief = ResearchBrief({
            "topic": topic,
            "niche": niche,
            "report": report,
            "sources": [{"title": s["title"], "url": s["url"], "source": s["source"]} for s in sources],
            "source_count": len(sources),
        })
        self.mark_success({"topic": topic, "sources": len(sources), "report_chars": len(report)})
        return brief

    async def verify(self, result: Any, goal: str) -> Verification:
        """A usable brief needs a substantive report."""
        if not isinstance(result, dict) or not result.get("report"):
            return Verification(
                is_complete=False, should_retry=True,
                feedback="Research produced no brief. Retry the synthesis.",
                reason="Empty research report.",
            )
        report = result["report"]
        if len(report) < 600 or "error" in report.lower()[:50]:
            return Verification(
                is_complete=False, should_retry=True,
                feedback="Research brief is too thin. Gather more and synthesize a denser, source-backed brief.",
                reason="Research brief too short.",
            )
        return Verification(
            is_complete=True, score=95.0,
            feedback=f"Research brief ready ({len(report)} chars, {result.get('source_count', 0)} sources).",
        )

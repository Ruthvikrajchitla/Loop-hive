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
        """Iterative deep research: search → synthesize → find gaps → dig deeper, over
        several rounds, then write a final comprehensive report. Genuinely thorough
        (real depth over many searches + synthesis passes), not a single quick pass."""
        topic = plan["topic"]
        niche = plan["niche"]
        queries = plan["queries"]

        all_sources: list[dict] = []
        seen: set[str] = set()
        notes = ""
        rounds = max(1, config.research_rounds)

        for rnd in range(1, rounds + 1):
            per_query = max(2, config.research_max_sources // max(1, len(queries)))
            for q in queries:
                for s in await gather_sources(q, max_sources=per_query):
                    key = (s.get("url") or s.get("title") or "").lower()
                    if key and key not in seen and s.get("content"):
                        seen.add(key)
                        all_sources.append(s)
            logger.info("research_round", round=rnd, of=rounds, topic=topic[:60], sources=len(all_sources))

            # Synthesize/deepen the running notes with everything gathered so far.
            corpus = "\n\n".join(
                f"SOURCE ({s['source']}): {s['title']}\n{s['content'][:1800]}" for s in all_sources
            )[:26000] or "No external sources retrieved; rely on expert knowledge."
            notes = await self.ask_llm(
                f"Topic: {topic} (niche: {niche}).\n\nPRIOR NOTES:\n{notes[:6000]}\n\n"
                f"NEW SOURCES:\n{corpus}\n\n"
                f"Update and DEEPEN the running research notes: concrete facts and numbers, named real "
                f"tools/products, exactly what users struggle with and want, how the best solutions work, "
                f"differentiators, pitfalls, and the current 2026 state. Be specific; never invent. Markdown.",
                temperature=0.35, max_tokens=4096,
            )

            # Find the biggest remaining gaps and search those next round.
            if rnd < rounds:
                gaps = await self.ask_llm_json(
                    f"Given these research notes on '{topic}', list the 3-5 MOST IMPORTANT questions that "
                    f"are still unanswered or too shallow — the things we must dig into next to make this "
                    f"research genuinely deep and decision-ready.\n\nNOTES:\n{notes[:6000]}\n\n"
                    f"Output JSON: {{'queries': [str]}}",
                    temperature=0.3, max_tokens=700,
                )
                queries = [q for q in gaps.get("queries", []) if isinstance(q, str) and q.strip()][: config.research_depth]
                if not queries:
                    break

        # Final comprehensive, decision-ready report — fused across all models (MoA).
        report = await self.ask_llm_fused(
            f"Write the FINAL, comprehensive research report on '{topic}' (niche: {niche}) from the notes "
            f"below. Markdown sections: ## Overview ## Key Facts & Numbers ## Current State (2026) "
            f"## Tools & Real Examples ## User Pain Points & Unmet Needs ## How the Best Solutions Work "
            f"## Pitfalls ## What To Build (concrete, opinionated recommendations). Dense, specific, and "
            f"decision-ready — this drives an engineering team's build.\n\nNOTES:\n{notes[:16000]}",
            temperature=0.4, max_tokens=5000,
        )

        brief = ResearchBrief({
            "topic": topic, "niche": niche, "report": report,
            "sources": [{"title": s["title"], "url": s["url"], "source": s["source"]} for s in all_sources],
            "source_count": len(all_sources),
            "rounds": rounds,
        })
        self.mark_success({"topic": topic, "sources": len(all_sources), "report_chars": len(report), "rounds": rounds})
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

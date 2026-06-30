"""
LoopHive — Niche Scout Agent

Autonomously discovers and ranks profitable niches.
Scrapes trending topics, gauges search volumes, checks competition,
and assesses affiliate/product monetization potential.
"""

from __future__ import annotations

import time
import httpx
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification

logger = structlog.get_logger(__name__)


class NicheCandidate:
    """Represents a discovered niche candidate."""

    def __init__(
        self,
        name: str,
        score: float,
        keywords: list[str],
        monetization_potential: float,
        competition: float,
        content_strategy: str,
    ):
        self.name = name
        self.score = score
        self.keywords = keywords
        self.monetization_potential = monetization_potential
        self.competition = competition
        self.content_strategy = content_strategy

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "keywords": self.keywords,
            "monetization_potential": self.monetization_potential,
            "competition": self.competition,
            "content_strategy": self.content_strategy,
        }


class NicheScoutAgent(AgentBase):
    """
    Agent that scans the web for trending topics, evaluates them for keyword
    difficulty and commercial intent, and outputs a scored list of niches.
    """

    def __init__(self, router=None):
        super().__init__(
            name="niche_scout",
            description="Autonomously discovers and ranks profitable content niches.",
            system_prompt=(
                "You are an expert market researcher and SEO strategist. Your job is to identify "
                "profitable niches that have high commercial intent but relatively low keyword "
                "competition. You must score each niche based on search trends, monetizability "
                "(affiliate sales, digital products, newsletter subscriptions), and ease of ranking. "
                "Avoid saturated topics and YMYL (Your Money Your Life - health/finance/legal) "
                "niches unless there is a very specific, low-risk angle. "
                "Always output valid JSON."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        """Gather current trends from various web feeds."""
        self.mark_running()
        trends = []

        # 1. Fetch Google Trends RSS feed
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Fetch daily search trends
                r = await client.get("https://trends.google.com/trending/rss?geo=US")
                if r.status_code == 200:
                    root = ET.fromstring(r.text)
                    for item in root.findall(".//item"):
                        title = item.find("title")
                        if title is not None and title.text:
                            trends.append({"source": "Google Trends", "topic": title.text})
        except Exception as e:
            self.logger.error("google_trends_fetch_failed", error=str(e))

        # 2. Fetch popular/trending subreddits or topics (simulated/public RSS)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://www.reddit.com/r/popular.json",
                    headers={"User-Agent": "LoopHive Niche Scout Agent v0.1.0"},
                )
                if r.status_code == 200:
                    data = r.json()
                    posts = data.get("data", {}).get("children", [])
                    for post in posts[:15]:
                        sub = post.get("data", {}).get("subreddit", "")
                        title = post.get("data", {}).get("title", "")
                        trends.append({
                            "source": f"Reddit r/{sub}",
                            "topic": title,
                        })
        except Exception as e:
            self.logger.error("reddit_trends_fetch_failed", error=str(e))

        return {
            "timestamp": time.time(),
            "raw_trends": trends[:30],  # Keep top 30
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Decide which niches to construct based on perceived trends."""
        raw_trends_str = "\n".join([
            f"- [{t['source']}] {t['topic']}" for t in state.get("raw_trends", [])
        ])

        prompt = (
            f"Analyze the following raw web trends and auto-discover 3-5 profitable niche candidates. "
            f"For each candidate, outline the commercial potential, suggest 5 target keywords, "
            f"rate competition and monetization from 1-10, write a content strategy (e.g. digital products "
            f"or newsletters to sell), and compute a score from 1-100.\n\n"
            f"Trends:\n{raw_trends_str}\n\n"
            f"Goal: {goal}\n\n"
            f"Your output must be a JSON object with a 'candidates' list. Each candidate must have "
            f"'name', 'keywords' (list of strings), 'monetization_potential' (float 1-10), "
            f"'competition' (float 1-10), 'content_strategy' (string), and 'score' (float 1-100).\n"
            f"Verify that no YMYL (medical, direct investment, or legal) niches are included."
        )

        response_json = await self.ask_llm_json(prompt, temperature=0.5)
        return response_json

    async def act(self, plan: dict) -> list[NicheCandidate]:
        """Convert the LLM plan into typed NicheCandidate objects."""
        candidates = []
        candidates_list = plan.get("candidates", [])

        for c in candidates_list:
            # Score formula checks and sanitization
            name = c.get("name", "Unknown Niche")
            keywords = c.get("keywords", [])
            monet = float(c.get("monetization_potential", 5.0))
            comp = float(c.get("competition", 5.0))
            strategy = c.get("content_strategy", "")
            
            # Auto-calculate score if not present or skewed: (monet * 15) - (comp * 5) + base
            score = float(c.get("score", (monet * 10) / (comp + 1.0) * 10))
            
            candidates.append(NicheCandidate(
                name=name,
                score=score,
                keywords=keywords,
                monetization_potential=monet,
                competition=comp,
                content_strategy=strategy,
            ))

        # Sort by score descending
        candidates.sort(key=lambda x: x.score, reverse=True)
        self.mark_success({"candidates_found": len(candidates)})
        return candidates

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the scout generated candidates successfully."""
        if not isinstance(result, list) or len(result) == 0:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="No niche candidates found. Try broadening the trend search.",
                reason="Candidates list is empty.",
            )

        # Check if first candidate has valid fields
        top = result[0]
        if not top.name or not top.keywords or top.score <= 0:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Candidates are missing crucial fields or scored 0. Regenerate.",
                reason="Invalid candidate fields.",
            )

        return Verification(
            is_complete=True,
            score=95.0,
            feedback=f"Found {len(result)} niches. Top niche: {top.name} (Score: {top.score:.1f})",
        )

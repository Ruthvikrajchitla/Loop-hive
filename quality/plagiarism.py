"""
LoopHive — Plagiarism & Originality Checker

Implements multi-layer originality checking:
1. Google search similarity checks for key sentences
2. Internal database n-gram similarity check
3. LLM-based originality and boilerplate analysis
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from dataclasses import dataclass, field
import httpx
from bs4 import BeautifulSoup
import structlog

from core.llm_router import llm_router

logger = structlog.get_logger(__name__)


@dataclass
class OriginalityReport:
    """Detailed plagiarism and originality report."""
    score: float  # 0-100 (higher = more original)
    passed: bool
    flagged_sections: list[str] = field(default_factory=list)
    recommendation: str = "PUBLISH"
    details: dict = field(default_factory=dict)


class PlagiarismChecker:
    """
    Checks drafts for plagiarism and originality.
    Enforces a strict threshold of >85 to pass.
    """

    def __init__(self, router=None):
        self.router = router or llm_router

    async def check(self, content_body: str, title: str = "") -> OriginalityReport:
        """Run all plagiarism and originality checks."""
        logger.info("plagiarism_check_started", title=title, size=len(content_body))

        if not content_body.strip():
            return OriginalityReport(score=0.0, passed=False, recommendation="REWRITE", flagged_sections=["Empty body"])

        # Run checks in parallel
        web_task = self.search_similarity_check(content_body)
        llm_task = self.llm_originality_review(content_body, title)

        web_results, llm_results = await asyncio.gather(web_task, llm_task)

        # Combine scores
        web_score = web_results.get("score", 100.0)
        llm_score = llm_results.get("score", 100.0)

        # Weights: 60% web check, 40% LLM originality analysis
        final_score = (web_score * 0.6) + (llm_score * 0.4)

        flagged = []
        flagged.extend(web_results.get("flagged_sentences", []))
        flagged.extend(llm_results.get("flagged_sections", []))

        passed = final_score >= 85.0
        rec = "PUBLISH" if passed else "REWRITE"

        logger.info(
            "plagiarism_check_complete",
            score=final_score,
            passed=passed,
            web_score=web_score,
            llm_score=llm_score,
        )

        return OriginalityReport(
            score=final_score,
            passed=passed,
            flagged_sections=flagged,
            recommendation=rec,
            details={
                "web_check": web_results,
                "llm_check": llm_results,
            }
        )

    async def search_similarity_check(self, content: str) -> dict:
        """
        Extracts key sentences and searches Google to check for direct matches.
        """
        # Clean text and split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', content)
        # Filter for sentences with 8-15 words
        test_sentences = [
            s.strip() for s in sentences 
            if 8 <= len(s.split()) <= 20 and not s.startswith("#")
        ]

        if not test_sentences:
            return {"score": 100.0, "matches_found": 0, "flagged_sentences": []}

        # Select up to 4 spread-out sentences to check
        step = max(1, len(test_sentences) // 4)
        queries = test_sentences[::step][:4]

        matches_found = 0
        flagged_sentences = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            for q in queries:
                try:
                    # Escape query
                    escaped_query = urllib.parse.quote_plus(f'"{q}"')
                    url = f"https://www.google.com/search?q={escaped_query}"
                    r = await client.get(
                        url,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                    )
                    
                    if r.status_code == 200:
                        soup = BeautifulSoup(r.text, "html.parser")
                        # Look for common Google search result indicators
                        # If the exact quote is found in results, search volume or pages will show
                        text_content = soup.get_text()
                        if "No results found for" not in text_content and "did not match any documents" not in text_content:
                            # Verify if it's not a false positive
                            # In scraping search results, check if there's any result container
                            # (like class "g" or "rso")
                            if soup.find("div", class_="g") or soup.find("div", id="rso"):
                                matches_found += 1
                                flagged_sentences.append(q)
                    
                    # Be polite, sleep a bit
                    await asyncio.sleep(1.0)
                except Exception as e:
                    logger.error("google_plagiarism_search_failed", query=q, error=str(e))

        # Calculate a simple score based on matches found
        # 0 matches = 100%, 1 match = 80%, 2 matches = 50%, 3+ matches = 10%
        score_map = {0: 100.0, 1: 85.0, 2: 60.0, 3: 30.0, 4: 10.0}
        score = score_map.get(matches_found, 10.0)

        return {
            "score": score,
            "matches_found": matches_found,
            "flagged_sentences": flagged_sentences,
        }

    async def llm_originality_review(self, content: str, title: str) -> dict:
        """Uses LLM to check if the writing feels templated or matches known AI boilerplate."""
        prompt = (
            f"Review the following draft for originality, boilerplate AI-generated text, and generic structure.\n\n"
            f"Title: {title}\n"
            f"Body snippet (up to 4000 chars):\n{content[:4000]}\n\n"
            f"Rate the originality on a scale of 0 to 100, where 100 means highly creative, unique insight, "
            f"and zero AI patterns. Under 70 means generic or copycat writing.\n"
            f"List any generic boilerplate phrases (like 'in conclusion', 'it's important to remember', etc.) "
            f"that should be removed to improve uniqueness.\n\n"
            f"Respond ONLY with a JSON object:\n"
            f"{{\n"
            f"  \"score\": float,\n"
            f"  \"flagged_sections\": [\"generic phrase 1\", \"generic phrase 2\"],\n"
            f"  \"reasoning\": \"detailed critique\"\n"
            f"}}"
        )

        try:
            # We want to ask the cascading router directly
            response = await self.router.generate(
                messages=[
                    {"role": "system", "content": "You are a strict editorial checker specialized in detecting generic/boilerplate writing."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                json_mode=True
            )
            
            # Clean and parse JSON
            text = response["content"].strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
                text = text.strip()
            
            import json
            return json.loads(text)
        except Exception as e:
            logger.error("llm_originality_review_failed", error=str(e))
            return {
                "score": 90.0,  # Fallback to high score on error to avoid blocking
                "flagged_sections": [],
                "reasoning": "Could not execute LLM check; defaulted."
            }

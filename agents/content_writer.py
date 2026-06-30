"""
LoopHive — Content Writer Agent

Generates high-quality, long-form, SEO-optimized articles and newsletter issues.
Applies multi-pass writing: outline → draft → edit → polish.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification

logger = structlog.get_logger(__name__)


class ContentWriterAgent(AgentBase):
    """
    Agent that generates long-form content using a multi-pass process.
    Uses target keywords, outlines, drafts, and self-editing before outputting markdown.
    """

    def __init__(self, router=None):
        super().__init__(
            name="content_writer",
            description="Generates high-quality, long-form articles and newsletters.",
            system_prompt=(
                "You are an elite content writer, copywriter, and SEO specialist. Your articles are "
                "original, engaging, and highly informative, structured with proper headings, bullet points, "
                "and tables where appropriate. You avoid fluff and repetitive phrasing, and optimize "
                "placement of target keywords naturally. Always write in clean Markdown."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        """Parse the incoming goal or topic from the context."""
        self.mark_running()
        # Find the latest task description or brief
        brief = {}
        for entry in reversed(context.entries):
            if "Goal:" in entry["content"]:
                brief["raw_goal"] = entry["content"].replace("Goal:", "").strip()
                break

        # Defaults
        brief["title"] = brief.get("raw_goal", "Niche Topic Guide")
        brief["keywords"] = ["productivity", "tools", "guide"]
        brief["content_type"] = "article"
        
        return {
            "timestamp": time.time(),
            "brief": brief,
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Decide the structure and layout (Outline step)."""
        brief = state.get("brief", {})
        title = brief.get("title", "Topic Guide")
        
        # Pass 1: Generate an Outline
        outline_prompt = (
            f"Create a detailed structural outline for a 2000+ word article on the topic: '{title}'.\n"
            f"Include target SEO keywords: {', '.join(brief.get('keywords', []))}.\n"
            f"Specify H2 and H3 headings, and briefly describe what goes under each section.\n\n"
            f"Your output must be JSON with 'title', 'keywords', and a list of 'outline_sections' (each "
            f"containing 'heading' and 'description')."
        )
        
        outline_json = await self.ask_llm_json(outline_prompt, temperature=0.4)
        return {
            "brief": brief,
            "outline": outline_json,
        }

    async def act(self, plan: dict) -> dict:
        """Generate the first draft and polish it based on the outline (Drafting & Polish steps)."""
        brief = plan.get("brief", {})
        outline = plan.get("outline", {})
        title = outline.get("title", brief.get("title"))
        
        outline_str = "\n".join([
            f"## {s.get('heading')}\n{s.get('description')}"
            for s in outline.get("outline_sections", [])
        ])

        # Pass 2: Write Draft
        draft_prompt = (
            f"You are writing a comprehensive, deep-dive article titled: '{title}'.\n"
            f"Here is the outline you must follow:\n{outline_str}\n\n"
            f"Instructions:\n"
            f"- Write in a clear, authoritative, and engaging tone.\n"
            f"- Aim for depth and clarity. Use tables, bullet points, and clean typography.\n"
            f"- Weave keywords ({', '.join(brief.get('keywords', []))}) naturally into the text.\n"
            f"- Do not add placeholders. All examples and advice must be real and concrete.\n\n"
            f"Write the full article body in Markdown."
        )

        draft = await self.ask_llm(draft_prompt, temperature=0.7)

        # Pass 3: Self-Edit/Polish
        polish_prompt = (
            f"You are editing the following article:\n\n{draft}\n\n"
            f"Tasks:\n"
            f"1. Fix any grammar, structural, or clarity issues.\n"
            f"2. Ensure transitions between sections are smooth.\n"
            f"3. Generate a compelling SEO meta description (max 150 characters).\n"
            f"4. Add a suggested word count.\n\n"
            f"Output a JSON object with keys: 'meta_description', 'word_count', and 'polished_body' (the updated Markdown body)."
        )

        polished_data = await self.ask_llm_json(polish_prompt, temperature=0.3)
        
        result = {
            "title": title,
            "meta_description": polished_data.get("meta_description", ""),
            "word_count": polished_data.get("word_count", len(polished_data.get("polished_body", "").split())),
            "body": polished_data.get("polished_body", draft),
        }
        
        self.mark_success(result)
        return result

    async def revise(self, draft: dict, feedback: str) -> dict:
        """Rewrite an existing draft to address critic / plagiarism feedback.

        Returns the same shape as ``act()`` so it can flow straight back into the
        critic → plagiarism gate for re-checking.
        """
        title = draft.get("title", "Untitled")
        body = draft.get("body", "")

        revise_prompt = (
            f"You are revising the article titled '{title}' based on reviewer feedback.\n\n"
            f"REVIEWER FEEDBACK (address every point):\n{feedback}\n\n"
            f"CURRENT DRAFT:\n{body[:8000]}\n\n"
            f"Rewrite the article to fully resolve the feedback — improve depth, originality, "
            f"readability, structure, and natural keyword usage. Rephrase any flagged or generic "
            f"boilerplate passages in an original voice. Keep it 2000+ words in clean Markdown.\n\n"
            f"Output a JSON object with keys: 'meta_description', 'word_count', 'polished_body'."
        )

        revised = await self.ask_llm_json(revise_prompt, temperature=0.5)
        polished_body = revised.get("polished_body") or body
        return {
            "title": title,
            "meta_description": revised.get("meta_description", draft.get("meta_description", "")),
            "word_count": revised.get("word_count", len(polished_body.split())),
            "body": polished_body,
        }

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the written content meets basic quality parameters."""
        if not isinstance(result, dict) or "body" not in result:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Failed to generate article content body.",
                reason="Invalid output structure.",
            )

        body = result.get("body", "")
        word_count = int(result.get("word_count", 0))

        if len(body) < 1000 or word_count < 200:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback=f"Article is too short ({len(body)} chars, {word_count} words). Aim for a deeper, more detailed article.",
                reason="Content length insufficient.",
            )

        return Verification(
            is_complete=True,
            score=90.0,
            feedback=f"Article '{result.get('title')}' successfully written. Word count: {word_count}. Original body size: {len(body)} characters.",
        )

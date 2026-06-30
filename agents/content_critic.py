"""
LoopHive — Content Critic Agent

Evaluates content quality, depth, formatting, and SEO optimization.
Acts as a quality gate — rejecting low-quality drafts and suggesting revisions.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification

logger = structlog.get_logger(__name__)


class ContentCriticAgent(AgentBase):
    """
    Agent that critiques content drafts before they go to plagiarism/compliance checks.
    Evaluates readability, structure, depth, and keyword usage.
    """

    def __init__(self, router=None):
        super().__init__(
            name="content_critic",
            description="Reviews article drafts and gives constructive quality feedback.",
            system_prompt=(
                "You are an editor-in-chief and expert content reviewer. Your job is to analyze "
                "article drafts for readability, clarity, depth of insight, formatting (H2/H3 use), "
                "plagiarism risks, and keyword alignment. You must score the content out of 100. "
                "Be critical, strict, and highlight actionable points for improvement. "
                "Always output JSON."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        """Find the drafted content to review from the context history."""
        self.mark_running()
        draft = {}
        for entry in reversed(context.entries):
            # Check if this contains the output from the content writer
            if "[COMPRESSED HISTORY]" not in entry["content"] and "body" in entry["content"]:
                # The prompt could contain JSON, try parsing or treat as raw
                try:
                    import json
                    draft = json.loads(entry["content"])
                except Exception:
                    draft = {"body": entry["content"]}
                break
            
            # Simple fallback if the last model response holds the draft
            if entry["role"] == "model" or entry["role"] == "assistant":
                draft = {"body": entry["content"]}

        return {
            "timestamp": time.time(),
            "draft": draft,
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Critique the draft and score it."""
        draft = state.get("draft", {})
        body = draft.get("body", "")
        title = draft.get("title", "Unknown Draft")

        if not body:
            return {
                "score": 0.0,
                "readability": "Poor",
                "critique": "Draft body is empty.",
                "improvements": ["Write the article draft first."],
            }

        prompt = (
            f"Critique the following article draft:\n\n"
            f"Title: {title}\n"
            f"Body:\n{body[:8000]}\n\n"  # Keep within context window limits
            f"Goal: {goal}\n\n"
            f"Provide an evaluation JSON with these fields:\n"
            f"- 'score': float (0-100)\n"
            f"- 'readability': string (e.g. Easy, Medium, High complexity)\n"
            f"- 'seo_alignment': string (Good, Average, Poor)\n"
            f"- 'formatting_ok': boolean\n"
            f"- 'depth_rating': float (1-10)\n"
            f"- 'critique': string (general summary feedback)\n"
            f"- 'improvements': list of strings (actionable changes to score higher)\n"
        )

        response_json = await self.ask_llm_json(prompt, temperature=0.2)
        return response_json

    async def act(self, plan: dict) -> dict:
        """Log the score and result."""
        self.mark_success(plan)
        return plan

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify quality score meets our threshold of 70/100."""
        if not isinstance(result, dict):
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Critique failed to parse correctly.",
                reason="Invalid output structure.",
            )

        score = float(result.get("score", 0.0))
        improvements = result.get("improvements", [])
        critique = result.get("critique", "No critique details.")

        if score < 70.0:
            feedback_msg = (
                f"Draft rejected with quality score {score}/100. "
                f"Critique: {critique}\n"
                f"Required Improvements:\n" + "\n".join([f"- {i}" for i in improvements])
            )
            return Verification(
                is_complete=False,
                should_retry=True,  # This will cause the writer agent to retry
                feedback=feedback_msg,
                reason="Quality score below 70 threshold.",
                score=score,
            )

        return Verification(
            is_complete=True,
            score=score,
            feedback=f"Draft approved with quality score {score}/100. Ready for plagiarism check.",
        )

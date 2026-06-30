"""
LoopHive — Plagiarism Checker Agent

Wraps the plagiarism checker engine into an autonomous agent role.
Inspects the content quality output, runs external/internal originality checks,
and fails the loop verification if similarity or boilerplate thresholds are breached.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification
from quality.plagiarism import PlagiarismChecker, OriginalityReport

logger = structlog.get_logger(__name__)


class PlagiarismCheckerAgent(AgentBase):
    """
    Agent that acts as the second quality gate: Originality/Plagiarism Check.
    Enforces that content must score >85 in uniqueness before it is passed to compliance.
    """

    def __init__(self, router=None):
        super().__init__(
            name="plagiarism_checker",
            description="Inspects article drafts for plagiarism, copy-pasting, and AI boilerplate.",
            system_prompt=(
                "You are an academic referee and copy-editing expert. Your role is to examine "
                "articles for originality, ensure no sections resemble online content too closely, "
                "and verify that the text possesses a high degree of uniqueness."
            ),
            router=router,
        )
        self.checker = PlagiarismChecker(router=self.router)

    async def perceive(self, context: ContextWindow) -> dict:
        """Locate the drafted/critic-approved content from the history."""
        self.mark_running()
        draft = {}
        for entry in reversed(context.entries):
            # Locate the entry that contains our content (normally from the content_writer)
            if "body" in entry["content"] and "[COMPRESSED HISTORY]" not in entry["content"]:
                try:
                    import json
                    draft = json.loads(entry["content"])
                except Exception:
                    draft = {"body": entry["content"]}
                break

        return {
            "timestamp": time.time(),
            "draft": draft,
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Decide what checks to run. In this agent, the action is running the plagiarism checks."""
        # We pass the draft body to act() for checking
        return {"draft": state.get("draft", {})}

    async def act(self, plan: dict) -> OriginalityReport:
        """Run the multi-layered plagiarism checker."""
        draft = plan.get("draft", {})
        body = draft.get("body", "")
        title = draft.get("title", "Unknown Draft")
        
        report = await self.checker.check(body, title)
        self.mark_success({
            "score": report.score,
            "passed": report.passed,
            "flagged_count": len(report.flagged_sections),
        })
        return report

    async def verify(self, result: Any, goal: str) -> Verification:
        """Enforce the originality threshold (>85)."""
        if not isinstance(result, OriginalityReport):
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Plagiarism checker did not produce an OriginalityReport.",
                reason="Invalid output type.",
            )

        if not result.passed:
            feedback_msg = (
                f"Content failed the plagiarism/originality check with score {result.score:.1f}/100. "
                f"Uniqueness threshold is 85/100.\n"
                f"Flagged sections or boilerplate terms to rewrite:\n"
                + "\n".join([f"- {s}" for s in result.flagged_sections])
            )
            return Verification(
                is_complete=False,
                should_retry=True,  # Triggers a retry of the writer agent
                feedback=feedback_msg,
                reason="Originality score below 85 threshold.",
                score=result.score,
            )

        return Verification(
            is_complete=True,
            score=result.score,
            feedback=f"Originality check passed: {result.score:.1f}/100. Ready for compliance checking.",
        )

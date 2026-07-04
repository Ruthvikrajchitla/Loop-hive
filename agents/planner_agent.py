"""
LoopHive — Planner Agent (Technical Architect)

Takes the analyzer's market brief and the research report and produces a complete
product-development plan: what to build, the architecture, the file structure, the
features, and the acceptance criteria the Builder must satisfy and the Critic
validates against.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification

logger = structlog.get_logger(__name__)


class PlannerAgent(AgentBase):
    """Designs the full product architecture and acceptance criteria."""

    def __init__(self, router=None):
        super().__init__(
            name="planner_agent",
            description="Turns market + research into a full product architecture and build plan.",
            system_prompt=(
                "You are a pragmatic technical product architect. You translate demand and research into a "
                "precise, buildable plan: a crisp scope, a sensible tech stack, an explicit file structure, "
                "the concrete features, and testable acceptance criteria. You keep scope shippable, not bloated."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        self.mark_running()
        market, research, idea, name, build_type = "", "", "", "", "developer tool"
        for entry in reversed(context.entries):
            c = entry["content"]
            if "MARKET BRIEF" in c and not market:
                market = c.split("MARKET BRIEF", 1)[1][:6000]
            elif "RESEARCH BRIEF" in c and not research:
                research = c.split("RESEARCH BRIEF", 1)[1][:8000]
            for line in c.split("\n"):
                low = line.lower().strip()
                if low.startswith("product_name:"):
                    name = line.split(":", 1)[1].strip() or name
                elif low.startswith("product_idea:"):
                    idea = line.split(":", 1)[1].strip() or idea
                elif low.startswith("build_type:"):
                    build_type = line.split(":", 1)[1].strip() or build_type
        return {"timestamp": time.time(), "market": market, "research": research,
                "idea": idea, "name": name, "build_type": build_type}

    async def reason(self, state: dict, goal: str) -> dict:
        return state

    async def act(self, plan: dict) -> dict:
        spec = await self.ask_llm_json(
            f"Design the full development plan for this product.\n\n"
            f"PRODUCT: {plan.get('name')} — {plan.get('idea')}\n"
            f"Preferred build type: {plan.get('build_type')}\n\n"
            f"MARKET BRIEF:\n{plan.get('market','')[:4000]}\n\n"
            f"RESEARCH BRIEF:\n{plan.get('research','')[:6000]}\n\n"
            f"Output JSON with:\n"
            f"- 'product_name': str\n- 'description': str (one line)\n"
            f"- 'build_type': 'developer tool|browser extension|static website|python package|github starter kit'\n"
            f"- 'stack': [str]\n- 'dependencies': [str]\n"
            f"- 'features': [str]  (the concrete capabilities to implement)\n"
            f"- 'files': [{{'path': str, 'purpose': str}}]  (3-9 files, correct extensions)\n"
            f"- 'acceptance_criteria': [str]  (testable checks that define 'done')",
            temperature=0.4, max_tokens=3000,
        )
        self.mark_success({"product": spec.get("product_name"), "files": len(spec.get("files", []))})
        return spec

    async def verify(self, result: Any, goal: str) -> Verification:
        if not isinstance(result, dict) or not result.get("files") or "error" in result:
            return Verification(is_complete=False, should_retry=True,
                                feedback="Plan must include a file list.", reason="No files in plan.")
        if not result.get("acceptance_criteria"):
            return Verification(is_complete=False, should_retry=True,
                                feedback="Plan must include testable acceptance criteria.", reason="No criteria.")
        return Verification(is_complete=True, score=93.0,
                            feedback=f"Plan ready: {len(result.get('files', []))} files, "
                                     f"{len(result.get('acceptance_criteria', []))} criteria.")

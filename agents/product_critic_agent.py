"""
LoopHive — Product Critic (QA & Validation)

Independently validates the built product: re-runs the sandbox, checks the code
against the plan's acceptance criteria, hunts for errors and leftovers, and rates
whether it's production-ready. If not, it sends specific feedback back to the
Builder for another round.
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification
from core.config import config
from core.sandbox import validate

logger = structlog.get_logger(__name__)


class ProductCriticAgent(AgentBase):
    """Second-pass QA that decides if the product is truly done."""

    def __init__(self, router=None):
        super().__init__(
            name="product_critic",
            description="Validates the built product against the plan and rates production-readiness.",
            system_prompt=(
                "You are a ruthless but fair senior QA engineer. You verify software actually meets its "
                "requirements: correct logic, no stubs/TODOs, no missing pieces, sane structure, and every "
                "acceptance criterion satisfied. You do not rubber-stamp — you only pass truly shippable work."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        self.mark_running()
        files, criteria, name = {}, [], ""
        for entry in reversed(context.entries):
            c = entry["content"]
            if "FILES:" in c and not files:
                try:
                    files = json.loads(c.split("FILES:", 1)[1].strip())
                except Exception:
                    files = {}
            if "PLAN:" in c and not criteria:
                try:
                    plan = json.loads(c.split("PLAN:", 1)[1].strip())
                    criteria = plan.get("acceptance_criteria", []) or []
                    name = plan.get("product_name", "")
                except Exception:
                    pass
        return {"timestamp": time.time(), "files": files, "criteria": criteria, "name": name}

    async def reason(self, state: dict, goal: str) -> dict:
        return state

    async def act(self, plan: dict) -> dict:
        files = plan.get("files", {})
        criteria = plan.get("criteria", [])
        if not files:
            return {"production_ready": False, "score": 0, "issues": ["No files to review."],
                    "missing": [], "sandbox_ok": False, "feedback": "No product was built."}

        sandbox_ok, sandbox_log = validate(files, execution=config.execution_sandbox,
                                           install_timeout=config.sandbox_install_timeout)
        listing = "\n\n".join(f"### {p}\n{(c or '')[:2500]}" for p, c in list(files.items())[:12])[:22000]

        review = await self.ask_llm_json(
            f"Validate this product against its acceptance criteria.\n\n"
            f"ACCEPTANCE CRITERIA:\n" + "\n".join(f"- {x}" for x in criteria) + "\n\n"
            f"SANDBOX (syntax/compile): {'PASS' if sandbox_ok else 'FAIL'}\n{sandbox_log[:800]}\n\n"
            f"FILES:\n{listing}\n\n"
            f"Check for: unmet criteria, stubs/TODOs/placeholders, obvious bugs, missing files/wiring.\n"
            f"Output JSON: {{'production_ready': bool, 'score': int (0-100), "
            f"'missing': [str], 'issues': [str], 'summary': str}}",
            temperature=0.2, max_tokens=1500,
        )
        production_ready = bool(review.get("production_ready")) and sandbox_ok
        fb_parts = []
        if not sandbox_ok:
            fb_parts.append(f"Sandbox failed: {sandbox_log[:400]}")
        fb_parts += [f"Missing: {m}" for m in review.get("missing", [])]
        fb_parts += [f"Issue: {i}" for i in review.get("issues", [])]
        return {
            "production_ready": production_ready,
            "score": int(review.get("score", 0)),
            "missing": review.get("missing", []),
            "issues": review.get("issues", []),
            "sandbox_ok": sandbox_ok,
            "summary": review.get("summary", ""),
            "feedback": "\n".join(fb_parts) or "Looks complete.",
        }

    async def verify(self, result: Any, goal: str) -> Verification:
        # The critic's job is to PRODUCE a verdict — it completes once it has one.
        # The orchestrator reads result['production_ready'] and loops the builder if
        # needed (retrying the critic on the same files would never change the verdict).
        if not isinstance(result, dict) or "production_ready" not in result:
            return Verification(is_complete=False, should_retry=True,
                                feedback="No valid review produced.", reason="Bad output.")
        ready = result.get("production_ready")
        return Verification(
            is_complete=True, score=float(result.get("score", 0)),
            feedback=(f"Production-ready ({result.get('score')}/100)." if ready
                      else f"Not ready: {result.get('feedback', '')[:160]}"),
        )

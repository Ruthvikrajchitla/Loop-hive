"""
LoopHive — Monthly Evaluator Agent

Reviews niche performance KPIs after 30 days and decides:
- CONTINUE: Keep publishing and selling in current niche.
- PIVOT: Discontinue current niche and auto-discover a new one.
- KILL: Immediately halt due to legal or toxic conditions.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification, MacroLoop, MacroDecision, MonthlyEvaluation

logger = structlog.get_logger(__name__)


class MonthlyEvaluatorAgent(AgentBase):
    """
    Agent that acts as the primary analytical critic for monthly reviews.
    Aggregates traffic and sales database metrics to invoke the MacroLoop.
    """

    def __init__(self, router=None):
        super().__init__(
            name="monthly_evaluator",
            description="Analyzes monthly traffic, engagement, and sales to make pivot decisions.",
            system_prompt=(
                "You are an expert business analyst and data scientist. Your job is to analyze "
                "performance metrics of our current digital marketing niche and determine "
                "whether it is viable to continue or if we should pivot to a new niche. "
                "You base your decisions strictly on data (conversion rates, traffic trends, cost/revenue). "
                "Always output JSON."
            ),
            router=router,
        )
        self.macro_loop = MacroLoop()

    async def perceive(self, context: ContextWindow) -> dict:
        """Fetch actual or mock KPIs from database/analytics."""
        self.mark_running()
        # In a real app, this would query the SQLite DB for:
        # SELECT SUM(amount) FROM revenue, count(views) from content, etc.
        # Here we fetch from state or mock it for E2E flow
        mock_kpis = {
            "traffic_trend_wow": 15.4,          # +15.4% week-over-week
            "avg_engagement_seconds": 124.0,    # ~2 minutes
            "subscriber_growth_weekly": 12,     # +12 subs/week
            "total_revenue": 18.00,             # $18 earned
            "content_quality_avg": 82.5,        # 82.5/100 critic score
            "affiliate_clicks": 34,
            "articles_published": 8,
            "legal_issues": [],
        }

        # Check if history passed custom test KPIs
        for entry in reversed(context.entries):
            if "test_kpis" in entry["content"]:
                try:
                    import json
                    # Find JSON in content
                    start = entry["content"].find("{")
                    end = entry["content"].rfind("}")
                    if start != -1 and end != -1:
                        mock_kpis = json.loads(entry["content"][start:end + 1])
                except Exception:
                    pass

        return {
            "timestamp": time.time(),
            "kpis": mock_kpis,
            "niche": "Notion Productivity",
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Call MacroLoop logic to decide niche viability and explain why."""
        niche = state.get("niche", "Unknown")
        kpis = state.get("kpis", {})
        
        # Run macro loop scoring logic
        evaluation = await self.macro_loop.run(niche, kpis)
        
        return {
            "decision": evaluation.decision.value,
            "niche": evaluation.niche,
            "kpis": evaluation.kpis,
            "reasoning": evaluation.reasoning,
        }

    async def act(self, plan: dict) -> MonthlyEvaluation:
        """Construct the MonthlyEvaluation object."""
        decision_str = plan.get("decision", "continue")
        niche = plan.get("niche", "")
        kpis = plan.get("kpis", {})
        reasoning = plan.get("reasoning", "")
        
        eval_obj = MonthlyEvaluation(
            decision=MacroDecision(decision_str),
            niche=niche,
            kpis=kpis,
            reasoning=reasoning,
        )
        
        self.mark_success({
            "decision": eval_obj.decision.value,
            "niche": eval_obj.niche,
            "revenue": kpis.get("total_revenue", 0.0),
        })
        return eval_obj

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the evaluation completes with a valid decision."""
        if not isinstance(result, MonthlyEvaluation):
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Evaluation failed to produce a MonthlyEvaluation object.",
                reason="Invalid output type.",
            )

        return Verification(
            is_complete=True,
            score=100.0,
            feedback=f"Monthly evaluation complete for '{result.niche}'. Decision: {result.decision.value.upper()}.",
        )

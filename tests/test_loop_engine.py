"""
LoopHive — Loop Engine Unit Tests

Verifies that MicroLoop, MesoLoop, and MacroLoop behave correctly.
"""

from __future__ import annotations

import pytest
from core.loop_engine import (
    MicroLoop,
    Verification,
    LoopStatus,
    MacroLoop,
    MacroDecision,
    ContextWindow,
)


class MockAgent:
    """Mock agent implementing AgentProtocol for testing."""

    def __init__(self, name="mock_agent", max_fail_cycles=0):
        self._name = name
        self.max_fail_cycles = max_fail_cycles
        self.cycles = 0

    @property
    def name(self) -> str:
        return self._name

    async def perceive(self, context: ContextWindow) -> dict:
        return {"cycle": self.cycles}

    async def reason(self, state: dict, goal: str) -> dict:
        return {"action": "do_work", "cycle": state["cycle"]}

    async def act(self, plan: dict) -> str:
        self.cycles += 1
        return f"result_cycle_{self.cycles}"

    async def verify(self, result: str, goal: str) -> Verification:
        if self.cycles <= self.max_fail_cycles:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback=f"Retry requested at cycle {self.cycles}",
                score=50.0,
            )
        return Verification(is_complete=True, score=95.0)


@pytest.mark.asyncio
async def test_micro_loop_success():
    """Verify micro-loop succeeds on immediate completion."""
    agent = MockAgent(max_fail_cycles=0)
    loop = MicroLoop(max_iterations=5)
    res = await loop.run(agent, "Complete work")
    
    assert res.status == LoopStatus.SUCCESS
    assert res.iterations_used == 1
    assert res.output == "result_cycle_1"


@pytest.mark.asyncio
async def test_micro_loop_retry_success():
    """Verify micro-loop succeeds after multiple retries."""
    agent = MockAgent(max_fail_cycles=2)
    loop = MicroLoop(max_iterations=5)
    res = await loop.run(agent, "Complete work")
    
    assert res.status == LoopStatus.SUCCESS
    assert res.iterations_used == 3
    assert res.output == "result_cycle_3"


@pytest.mark.asyncio
async def test_micro_loop_max_iterations():
    """Verify micro-loop stops when hitting iteration ceiling."""
    agent = MockAgent(max_fail_cycles=10)
    loop = MicroLoop(max_iterations=3)
    res = await loop.run(agent, "Complete work")
    
    assert res.status == LoopStatus.MAX_ITERATIONS
    assert res.iterations_used == 3


@pytest.mark.asyncio
async def test_macro_loop_evaluation():
    """Verify monthly evaluation pivot/continue logic."""
    macro = MacroLoop()

    # Case 1: Healthy niche -> continue
    kpis_ok = {
        "traffic_trend_wow": 10.0,
        "avg_engagement_seconds": 60.0,
        "subscriber_growth_weekly": 10,
        "total_revenue": 5.0,
        "content_quality_avg": 80.0,
        "articles_published": 6,
        "legal_issues": [],
    }
    eval_ok = await macro.run("notion", kpis_ok)
    assert eval_ok.decision == MacroDecision.CONTINUE

    # Case 2: Poor niche -> pivot
    kpis_poor = {
        "traffic_trend_wow": -5.0,
        "avg_engagement_seconds": 10.0,
        "subscriber_growth_weekly": 1,
        "total_revenue": 0.0,
        "content_quality_avg": 50.0,
        "articles_published": 6,
        "legal_issues": [],
    }
    eval_poor = await macro.run("notion", kpis_poor)
    assert eval_poor.decision == MacroDecision.PIVOT

    # Case 3: Legal issue -> kill
    kpis_toxic = {
        "traffic_trend_wow": 10.0,
        "avg_engagement_seconds": 60.0,
        "subscriber_growth_weekly": 10,
        "total_revenue": 5.0,
        "content_quality_avg": 80.0,
        "articles_published": 6,
        "legal_issues": ["Platform banned account for ToS violation"],
    }
    eval_toxic = await macro.run("notion", kpis_toxic)
    assert eval_toxic.decision == MacroDecision.KILL

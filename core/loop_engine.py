"""
LoopHive — Three-Tier Loop Engine

The heart of the system. Implements loop engineering at three time scales:
  - MicroLoop:  Per-task (minutes)   — Perceive → Reason → Act → Verify
  - MesoLoop:   Weekly              — Strategy review & content planning
  - MacroLoop:  Monthly             — Niche evaluation: Continue / Pivot / Kill
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class LoopStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"
    MAX_ITERATIONS = "max_iterations"


class MacroDecision(str, Enum):
    CONTINUE = "continue"
    PIVOT = "pivot"
    KILL = "kill"


@dataclass
class LoopResult:
    """Result of a single micro-loop execution."""
    status: LoopStatus
    output: Any = None
    reason: str = ""
    iterations_used: int = 0
    total_tokens_used: int = 0
    duration_seconds: float = 0.0


@dataclass
class Verification:
    """Result of the verify step in a micro-loop."""
    is_complete: bool = False
    should_retry: bool = False
    should_abort: bool = False
    feedback: str = ""
    reason: str = ""
    score: float = 0.0  # 0-100 quality/completion score


@dataclass
class WeeklyPlan:
    """Output of the meso-loop — what to do this week."""
    content_briefs: list[dict] = field(default_factory=list)
    product_tasks: list[dict] = field(default_factory=list)
    marketing_tasks: list[dict] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)
    top_performers: list[dict] = field(default_factory=list)


@dataclass
class MonthlyEvaluation:
    """Output of the macro-loop — continue, pivot, or kill."""
    decision: MacroDecision
    niche: str
    kpis: dict = field(default_factory=dict)
    new_niche: str | None = None
    reasoning: str = ""


@dataclass
class ContextWindow:
    """
    Manages conversation context to prevent 'context rot'.
    Keeps recent iterations fresh and summarizes old ones.
    """
    entries: list[dict] = field(default_factory=list)
    max_entries: int = 20
    total_tokens: int = 0

    def add(self, role: str, content: str, tokens: int = 0):
        """Add a new context entry."""
        self.entries.append({
            "role": role,
            "content": content,
            "tokens": tokens,
            "timestamp": time.time(),
        })
        self.total_tokens += tokens
        self._prune_if_needed()

    def add_feedback(self, feedback: str):
        """Add verification feedback for the next iteration."""
        self.add("system", f"[FEEDBACK] {feedback}")

    def prune_stale(self):
        """Summarize and compress old entries to prevent context rot."""
        if len(self.entries) <= self.max_entries // 2:
            return

        # Keep the first entry (system prompt) and last half of entries
        keep_count = self.max_entries // 2
        old_entries = self.entries[1:-keep_count]

        if not old_entries:
            return

        # Summarize old entries into a single condensed entry
        summary_parts = []
        for entry in old_entries:
            content = entry["content"]
            if len(content) > 200:
                content = content[:200] + "..."
            summary_parts.append(f"[{entry['role']}] {content}")

        summary = "[COMPRESSED HISTORY]\n" + "\n".join(summary_parts[-5:])

        # Replace old entries with summary
        self.entries = (
            [self.entries[0]]
            + [{"role": "system", "content": summary, "tokens": 0, "timestamp": time.time()}]
            + self.entries[-keep_count:]
        )
        self._recalculate_tokens()

    def _prune_if_needed(self):
        """Auto-prune when context grows too large."""
        if len(self.entries) > self.max_entries:
            self.prune_stale()

    def _recalculate_tokens(self):
        """Recalculate total token count."""
        self.total_tokens = sum(e.get("tokens", 0) for e in self.entries)

    def to_messages(self) -> list[dict]:
        """Convert to LLM message format."""
        return [
            {"role": e["role"], "content": e["content"]}
            for e in self.entries
        ]

    def clear(self):
        """Reset the context window."""
        self.entries.clear()
        self.total_tokens = 0


# ---------------------------------------------------------------------------
# Agent Protocol — every agent must implement these
# ---------------------------------------------------------------------------

class AgentProtocol(Protocol):
    """Protocol that all agents must follow to work with the loop engine."""

    @property
    def name(self) -> str: ...

    async def perceive(self, context: ContextWindow) -> dict:
        """Gather current state — what does the world look like?"""
        ...

    async def reason(self, state: dict, goal: str) -> dict:
        """Decide what to do next based on state and goal."""
        ...

    async def act(self, plan: dict) -> Any:
        """Execute the plan."""
        ...

    async def verify(self, result: Any, goal: str) -> Verification:
        """Check if the goal is met."""
        ...


# ---------------------------------------------------------------------------
# Tier 1: MicroLoop — Per-task execution (minutes)
# ---------------------------------------------------------------------------

class MicroLoop:
    """
    The fundamental execution loop for any single task.

    Perceive → Reason → Act → Verify
    Repeats until goal is met, max iterations hit, or abort signal.
    """

    def __init__(self, max_iterations: int = 10, timeout_seconds: float = 300.0):
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds

    async def run(self, agent: AgentProtocol, goal: str) -> LoopResult:
        """Execute the micro-loop for a given agent and goal."""
        context = ContextWindow()
        context.add("system", f"Goal: {goal}")
        start_time = time.time()
        total_tokens = 0

        logger.info(
            "micro_loop_started",
            agent=agent.name,
            goal=goal[:100],
            max_iterations=self.max_iterations,
        )

        for iteration in range(1, self.max_iterations + 1):
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > self.timeout_seconds:
                logger.warning("micro_loop_timeout", agent=agent.name, elapsed=elapsed)
                return LoopResult(
                    status=LoopStatus.FAILED,
                    reason=f"Timeout after {elapsed:.1f}s",
                    iterations_used=iteration,
                    total_tokens_used=total_tokens,
                    duration_seconds=elapsed,
                )

            try:
                # 1. PERCEIVE
                state = await agent.perceive(context)
                logger.debug("perceive_complete", agent=agent.name, iteration=iteration)

                # 2. REASON
                plan = await agent.reason(state, goal)
                logger.debug("reason_complete", agent=agent.name, iteration=iteration)

                # 3. ACT
                result = await agent.act(plan)
                logger.debug("act_complete", agent=agent.name, iteration=iteration)

                # 4. VERIFY
                verification = await agent.verify(result, goal)
                logger.info(
                    "verify_complete",
                    agent=agent.name,
                    iteration=iteration,
                    complete=verification.is_complete,
                    score=verification.score,
                )

                if verification.is_complete:
                    duration = time.time() - start_time
                    logger.info(
                        "micro_loop_success",
                        agent=agent.name,
                        iterations=iteration,
                        duration=duration,
                    )
                    return LoopResult(
                        status=LoopStatus.SUCCESS,
                        output=result,
                        iterations_used=iteration,
                        total_tokens_used=total_tokens,
                        duration_seconds=duration,
                    )

                if verification.should_abort:
                    duration = time.time() - start_time
                    logger.warning(
                        "micro_loop_aborted",
                        agent=agent.name,
                        reason=verification.reason,
                    )
                    return LoopResult(
                        status=LoopStatus.ABORTED,
                        reason=verification.reason,
                        iterations_used=iteration,
                        total_tokens_used=total_tokens,
                        duration_seconds=duration,
                    )

                if verification.should_retry:
                    context.add_feedback(verification.feedback)
                    context.prune_stale()
                    logger.debug(
                        "micro_loop_retry",
                        agent=agent.name,
                        iteration=iteration,
                        feedback=verification.feedback[:100],
                    )

            except Exception as e:
                logger.error(
                    "micro_loop_error",
                    agent=agent.name,
                    iteration=iteration,
                    error=str(e),
                )
                context.add_feedback(f"Error in iteration {iteration}: {str(e)}")
                continue

        duration = time.time() - start_time
        logger.warning(
            "micro_loop_max_iterations",
            agent=agent.name,
            max_iterations=self.max_iterations,
        )
        return LoopResult(
            status=LoopStatus.MAX_ITERATIONS,
            reason=f"Reached max iterations ({self.max_iterations})",
            iterations_used=self.max_iterations,
            total_tokens_used=total_tokens,
            duration_seconds=duration,
        )


# ---------------------------------------------------------------------------
# Tier 2: MesoLoop — Weekly strategy review
# ---------------------------------------------------------------------------

class MesoLoop:
    """
    Weekly strategy loop. Reviews performance and adjusts content plan.

    Runs once per week (via scheduler).
    Analyzes what content is performing, what isn't, and plans the next week.
    """

    def __init__(self, analytics_agent=None, content_planner=None):
        self.analytics = analytics_agent
        self.planner = content_planner

    async def run(self, niche: str, published_content: list[dict]) -> WeeklyPlan:
        """Run weekly strategy review."""
        logger.info("meso_loop_started", niche=niche)

        # 1. Gather weekly metrics
        metrics = {}
        if self.analytics:
            metrics = await self.analytics.get_weekly_summary()

        # 2. Identify top performers
        top_performers = sorted(
            published_content,
            key=lambda c: c.get("engagement_score", 0),
            reverse=True,
        )[:5]

        # 3. Identify underperformers
        underperformers = [
            c for c in published_content
            if c.get("engagement_score", 0) < 10 and c.get("days_since_publish", 0) > 7
        ]

        # 4. Generate adjustments
        adjustments = []
        if top_performers:
            top_topics = [c.get("topic", "") for c in top_performers]
            adjustments.append(f"Double down on topics like: {', '.join(top_topics[:3])}")
        if underperformers:
            adjustments.append(
                f"Reduce content similar to {len(underperformers)} underperforming pieces"
            )

        # 5. Plan next week's content (max 5 quality pieces)
        content_briefs = []
        if self.planner:
            content_briefs = await self.planner.generate_weekly_briefs(
                niche=niche,
                top_performers=top_performers,
                max_pieces=5,
            )

        plan = WeeklyPlan(
            content_briefs=content_briefs,
            adjustments=adjustments,
            top_performers=top_performers,
        )

        logger.info(
            "meso_loop_complete",
            briefs=len(content_briefs),
            adjustments=len(adjustments),
        )
        return plan


# ---------------------------------------------------------------------------
# Tier 3: MacroLoop — Monthly niche evaluation
# ---------------------------------------------------------------------------

class MacroLoop:
    """
    Monthly evaluation loop. The 'employee review'.

    After 30 days, evaluates whether the current niche is viable:
      - CONTINUE: KPIs trending up → keep going, scale up
      - PIVOT:    KPIs flat/declining → switch to a new niche
      - KILL:     Legal issues or zero traction → abandon entirely
    """

    # Thresholds for evaluation
    MIN_TRAFFIC_GROWTH = 0.0     # Week-over-week traffic must not decline
    MIN_ENGAGEMENT_TIME = 30.0   # Average seconds on page
    MIN_SUBSCRIBER_GROWTH = 5    # New subscribers per week
    MIN_CONTENT_QUALITY = 70.0   # Average quality score

    async def run(self, niche: str, kpis: dict) -> MonthlyEvaluation:
        """Evaluate niche performance and decide: continue, pivot, or kill."""
        logger.info("macro_loop_started", niche=niche, kpis=kpis)

        # Extract KPIs
        traffic_trend = kpis.get("traffic_trend_wow", 0)  # Week-over-week %
        avg_engagement = kpis.get("avg_engagement_seconds", 0)
        subscriber_growth = kpis.get("subscriber_growth_weekly", 0)
        total_revenue = kpis.get("total_revenue", 0)
        content_quality_avg = kpis.get("content_quality_avg", 0)
        affiliate_clicks = kpis.get("affiliate_clicks", 0)
        articles_published = kpis.get("articles_published", 0)
        legal_issues = kpis.get("legal_issues", [])

        # Decision logic
        reasoning_parts = []

        # KILL conditions (immediate)
        if legal_issues:
            reasoning = f"Legal issues detected: {', '.join(legal_issues)}"
            logger.warning("macro_loop_kill", niche=niche, reason=reasoning)
            return MonthlyEvaluation(
                decision=MacroDecision.KILL,
                niche=niche,
                kpis=kpis,
                reasoning=reasoning,
            )

        # Score each KPI
        score = 0
        max_score = 5

        if traffic_trend >= self.MIN_TRAFFIC_GROWTH:
            score += 1
            reasoning_parts.append(f"✅ Traffic trend: {traffic_trend:+.1f}% WoW")
        else:
            reasoning_parts.append(f"❌ Traffic declining: {traffic_trend:+.1f}% WoW")

        if avg_engagement >= self.MIN_ENGAGEMENT_TIME:
            score += 1
            reasoning_parts.append(f"✅ Engagement: {avg_engagement:.0f}s avg")
        else:
            reasoning_parts.append(f"❌ Low engagement: {avg_engagement:.0f}s avg")

        if subscriber_growth >= self.MIN_SUBSCRIBER_GROWTH:
            score += 1
            reasoning_parts.append(f"✅ Subscriber growth: +{subscriber_growth}/week")
        else:
            reasoning_parts.append(f"❌ Slow subscriber growth: +{subscriber_growth}/week")

        if total_revenue > 0 or affiliate_clicks > 0:
            score += 1
            reasoning_parts.append(
                f"✅ Revenue signals: ${total_revenue:.2f} revenue, "
                f"{affiliate_clicks} affiliate clicks"
            )
        else:
            reasoning_parts.append("❌ No revenue or affiliate clicks yet")

        if content_quality_avg >= self.MIN_CONTENT_QUALITY:
            score += 1
            reasoning_parts.append(f"✅ Content quality: {content_quality_avg:.0f}/100 avg")
        else:
            reasoning_parts.append(f"❌ Low content quality: {content_quality_avg:.0f}/100 avg")

        reasoning = "\n".join(reasoning_parts)
        reasoning += f"\n\nScore: {score}/{max_score}"

        # Decision
        if score >= 3:
            decision = MacroDecision.CONTINUE
            reasoning += "\n→ Decision: CONTINUE — enough positive signals"
        elif articles_published < 5:
            decision = MacroDecision.CONTINUE
            reasoning += "\n→ Decision: CONTINUE — not enough content yet to judge"
        else:
            decision = MacroDecision.PIVOT
            reasoning += "\n→ Decision: PIVOT — insufficient traction after 30 days"

        logger.info(
            "macro_loop_decision",
            niche=niche,
            decision=decision.value,
            score=f"{score}/{max_score}",
        )

        return MonthlyEvaluation(
            decision=decision,
            niche=niche,
            kpis=kpis,
            reasoning=reasoning,
        )

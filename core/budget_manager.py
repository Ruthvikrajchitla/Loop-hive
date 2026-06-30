"""
LoopHive — Budget Manager

Tracks API costs, daily usage, and earnings across all revenue channels.
Ensures the system stays within free-tier limits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DailyBudget:
    """Tracks daily API usage and costs."""
    date: str = ""
    total_requests: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0  # Should always be $0 on free tiers
    providers_used: dict = field(default_factory=dict)


@dataclass
class RevenueEntry:
    """A single revenue event."""
    source: str  # "affiliate", "product", "newsletter", "adsense"
    amount: float
    description: str
    timestamp: float = field(default_factory=time.time)


class BudgetManager:
    """
    Tracks costs and revenue for the entire system.

    Primary job: ensure we never accidentally spend money on API calls.
    Secondary job: track all incoming revenue.
    """

    def __init__(self):
        self.daily_budgets: list[DailyBudget] = []
        self.revenue_entries: list[RevenueEntry] = []
        self._current_day: DailyBudget | None = None

    def record_api_usage(self, provider: str, tokens: int, cost: float = 0.0):
        """Record an API call for budget tracking."""
        budget = self._get_current_day()
        budget.total_requests += 1
        budget.total_tokens += tokens
        budget.estimated_cost += cost
        budget.providers_used[provider] = budget.providers_used.get(provider, 0) + 1

        if cost > 0:
            logger.warning(
                "paid_api_usage_detected",
                provider=provider,
                cost=cost,
                total_today=budget.estimated_cost,
            )

    def record_revenue(self, source: str, amount: float, description: str = ""):
        """Record incoming revenue."""
        entry = RevenueEntry(
            source=source,
            amount=amount,
            description=description,
        )
        self.revenue_entries.append(entry)
        logger.info(
            "revenue_recorded",
            source=source,
            amount=amount,
            description=description,
        )

    def get_total_revenue(self) -> float:
        """Get total revenue earned."""
        return sum(e.amount for e in self.revenue_entries)

    def get_total_cost(self) -> float:
        """Get total API costs incurred."""
        return sum(b.estimated_cost for b in self.daily_budgets)

    def get_net_profit(self) -> float:
        """Revenue minus costs."""
        return self.get_total_revenue() - self.get_total_cost()

    def get_revenue_by_source(self) -> dict[str, float]:
        """Get revenue breakdown by source."""
        breakdown: dict[str, float] = {}
        for entry in self.revenue_entries:
            breakdown[entry.source] = breakdown.get(entry.source, 0) + entry.amount
        return breakdown

    def get_daily_summary(self) -> dict:
        """Get summary for today."""
        budget = self._get_current_day()
        return {
            "date": budget.date,
            "requests": budget.total_requests,
            "tokens": budget.total_tokens,
            "cost": budget.estimated_cost,
            "providers": budget.providers_used,
            "total_revenue": self.get_total_revenue(),
            "net_profit": self.get_net_profit(),
        }

    def _get_current_day(self) -> DailyBudget:
        """Get or create today's budget tracker."""
        import datetime
        today = datetime.date.today().isoformat()

        if self._current_day is None or self._current_day.date != today:
            self._current_day = DailyBudget(date=today)
            self.daily_budgets.append(self._current_day)

        return self._current_day


# Global budget manager
budget_manager = BudgetManager()

"""
LoopHive — Earnings Report

Aggregates costs, sales volume, and revenues across affiliate and product channels.
"""

from __future__ import annotations

import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class EarningsReport:
    """Consolidates financial stats for the web dashboard."""

    def __init__(self, budget_manager=None):
        from core.budget_manager import budget_manager as default_mgr
        self.manager = budget_manager or default_mgr

    def get_summary(self) -> dict[str, Any]:
        """Aggregate daily metrics."""
        breakdown = self.manager.get_revenue_by_source()
        total_rev = self.manager.get_total_revenue()
        total_cost = self.manager.get_total_cost()
        
        # Format for dashboard
        return {
            "total_revenue": total_rev,
            "total_cost": total_cost,
            "net_profit": total_rev - total_cost,
            "breakdown": {
                "affiliates": breakdown.get("affiliate", 0.0),
                "products": breakdown.get("product", 0.0),
                "newsletter": breakdown.get("newsletter", 0.0),
                "ads": breakdown.get("adsense", 0.0),
            },
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

    def get_weekly_report(self) -> list[dict]:
        """Return fake or actual past 7 days breakdown for graph display."""
        today = datetime.date.today()
        report = []
        for i in range(6, -1, -1):
            day = today - datetime.timedelta(days=i)
            report.append({
                "date": day.strftime("%a"),  # e.g. Mon, Tue
                "revenue": 0.0,
                "cost": 0.0,
            })
        
        # Inject today's live revenue if any exists
        summary = self.get_summary()
        report[-1]["revenue"] = summary["total_revenue"]
        report[-1]["cost"] = summary["total_cost"]
        
        return report

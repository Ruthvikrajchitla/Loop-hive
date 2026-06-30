"""
LoopHive — Compliance Rulebook

Maintains legal rules, platform policies, and disclosure text templates
for FTC compliance, EU AI Act, and major platforms.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Rule:
    """A specific legal or platform rule."""
    category: str  # ftc, eu_ai_act, platform_tos, niche_specific
    rule_text: str
    severity: str = "required"  # required, recommended, optional
    platform: str | None = None
    disclosure_template: str | None = None
    source_url: str | None = None


class ComplianceRulebook:
    """
    Rulebook compiled by the Legal Research Agent.
    Dictates what content can/cannot be created and what disclosures are required.
    """

    def __init__(self, niche: str = ""):
        self.niche = niche
        self.rules: list[Rule] = []
        self.allowed_content_types: list[str] = ["articles", "newsletters", "checklists"]
        self.banned_content_types: list[str] = []
        self.disclosures: dict[str, str] = {
            "ftc_affiliate": "This post contains affiliate links. If you purchase through these links, I may earn a commission.",
            "ai_disclosure": "This content was created with the assistance of AI tools. All facts and claims have been verified.",
            "eu_ai_label": "[AI-GENERATED CONTENT]",
        }

    def add_rule(self, rule: Rule):
        """Add a rule to the rulebook."""
        self.rules.append(rule)

    def get_rules_for_platform(self, platform: str) -> list[Rule]:
        """Get all rules that apply to a specific publishing platform."""
        return [r for r in self.rules if r.platform == platform or r.platform is None]

    def get_required_disclosures(self, platform: str) -> list[str]:
        """Get the required disclosure texts for a platform."""
        req = []
        # Check rules for required disclosures
        for r in self.get_rules_for_platform(platform):
            if r.severity == "required" and r.disclosure_template:
                req.append(r.disclosure_template)

        # Fallback default ones
        if not req:
            req.append(self.disclosures["ftc_affiliate"])
            if platform in ["medium", "youtube", "instagram"]:
                req.append(self.disclosures["ai_disclosure"])

        return req

    def to_json(self) -> str:
        """Serialize the rulebook to JSON."""
        data = {
            "niche": self.niche,
            "allowed_content_types": self.allowed_content_types,
            "banned_content_types": self.banned_content_types,
            "disclosures": self.disclosures,
            "rules": [
                {
                    "category": r.category,
                    "rule_text": r.rule_text,
                    "severity": r.severity,
                    "platform": r.platform,
                    "disclosure_template": r.disclosure_template,
                    "source_url": r.source_url,
                }
                for r in self.rules
            ],
        }
        return json.dumps(data, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> ComplianceRulebook:
        """Deserialize the rulebook from JSON."""
        data = json.loads(json_str)
        obj = cls(niche=data.get("niche", ""))
        obj.allowed_content_types = data.get("allowed_content_types", [])
        obj.banned_content_types = data.get("banned_content_types", [])
        obj.disclosures = data.get("disclosures", {})
        
        for r in data.get("rules", []):
            obj.add_rule(Rule(
                category=r["category"],
                rule_text=r["rule_text"],
                severity=r.get("severity", "required"),
                platform=r.get("platform"),
                disclosure_template=r.get("disclosure_template"),
                source_url=r.get("source_url"),
            ))
        return obj

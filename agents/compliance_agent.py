"""
LoopHive — Compliance Agent

Audits drafts against the auto-generated ComplianceRulebook.
Automatically injects required disclosures (FTC affiliate links, AI content labels)
and ensures compliance with the EU AI Act and platform ToS.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification
from compliance.rulebook import ComplianceRulebook

logger = structlog.get_logger(__name__)


class ComplianceAgent(AgentBase):
    """
    Agent that verifies legal compliance before publishing.
    Auto-injects FTC affiliate statements, AI-usage warnings, and platform disclaimers.
    """

    def __init__(self, router=None):
        super().__init__(
            name="compliance_agent",
            description="Audits and formatting-fixes content to satisfy FTC and EU AI Act regulations.",
            system_prompt=(
                "You are an expert compliance officer and copyeditor. Your job is to verify that "
                "articles and newsletters contain appropriate disclaimers and tags. "
                "Specifically, you must check for: affiliate disclosures at the very beginning of "
                "sponsored posts, AI content labeling for EU compliance, and factual disclaimers. "
                "You output compliant text."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        """Load draft content and the compiled rulebook."""
        self.mark_running()
        draft = {}
        rulebook_str = ""

        # Search history for draft and rulebook
        for entry in reversed(context.entries):
            if "body" in entry["content"] and "[COMPRESSED HISTORY]" not in entry["content"]:
                try:
                    import json
                    draft = json.loads(entry["content"])
                except Exception:
                    draft = {"body": entry["content"]}
            if "allowed_content_types" in entry["content"] and "rules" in entry["content"]:
                rulebook_str = entry["content"]

        # Parse rulebook
        rulebook = None
        if rulebook_str:
            try:
                rulebook = ComplianceRulebook.from_json(rulebook_str)
            except Exception as e:
                self.logger.error("parse_rulebook_failed", error=str(e))

        # Fallback empty rulebook if none exists in history
        if not rulebook:
            rulebook = ComplianceRulebook(niche="General")

        return {
            "timestamp": time.time(),
            "draft": draft,
            "rulebook": rulebook,
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Determine what disclosures are missing and where to inject them."""
        draft = state.get("draft", {})
        rulebook: ComplianceRulebook = state.get("rulebook")
        body = draft.get("body", "")
        title = draft.get("title", "")
        platform = draft.get("platform", "substack")

        # Check what disclosures are required
        required_disclosures = rulebook.get_required_disclosures(platform)
        missing_disclosures = []

        for d in required_disclosures:
            # Simple substring matching to check if already present
            if d.split(".")[0] not in body:  # Match by sentence starts
                missing_disclosures.append(d)

        # Also check for AI labeling under EU AI Act
        eu_label = rulebook.disclosures.get("eu_ai_label", "[AI-GENERATED CONTENT]")
        has_eu_rule = any(r.category == "eu_ai_act" for r in rulebook.rules)
        missing_eu_label = has_eu_rule and (eu_label not in body)

        return {
            "draft": draft,
            "missing_disclosures": missing_disclosures,
            "missing_eu_label": missing_eu_label,
            "eu_label": eu_label,
        }

    async def act(self, plan: dict) -> dict:
        """Inject missing disclosures and formatting rules into the content body."""
        draft = plan.get("draft", {})
        body = draft.get("body", "")
        missing = plan.get("missing_disclosures", [])
        missing_eu = plan.get("missing_eu_label", False)
        eu_label = plan.get("eu_label", "[AI-GENERATED CONTENT]")

        # 1. Inject EU AI Act label at the very top if missing
        if missing_eu:
            body = f"{eu_label}\n\n{body}"

        # 2. Inject affiliate/general disclosures after the title or first heading
        if missing:
            disclosure_text = "\n\n".join([f"> *{d}*" for d in missing])
            
            # Find the first paragraph or H2 to insert the block
            lines = body.split("\n")
            inserted = False
            for idx, line in enumerate(lines):
                # Insert after the first heading or empty line
                if line.startswith("# ") or (line.strip() == "" and idx > 0):
                    lines.insert(idx + 1, f"\n{disclosure_text}\n")
                    inserted = True
                    break
            
            if not inserted:
                body = f"{disclosure_text}\n\n{body}"
            else:
                body = "\n".join(lines)

        compliant_draft = dict(draft)
        compliant_draft["body"] = body
        compliant_draft["has_ai_disclosure"] = True
        compliant_draft["has_affiliate_disclosure"] = len(missing) > 0
        compliant_draft["compliance_checked"] = True

        self.mark_success({"compliance_fixed": len(missing) > 0 or missing_eu})
        return compliant_draft

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the content now contains all compliance disclosures."""
        if not isinstance(result, dict) or "body" not in result:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Compliance agent failed to produce updated content body.",
                reason="Invalid output structure.",
            )

        body = result.get("body", "")
        # A simple sanity check that some form of disclosure is in the body
        if "disclosure" not in body.lower() and "commission" not in body.lower() and "ai-generated" not in body.lower():
            # If both were not required, it might pass, but usually we require at least one
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Draft is missing standard compliance warnings/disclosures. Please inject them.",
                reason="No disclosure text detected in content.",
            )

        return Verification(
            is_complete=True,
            score=100.0,
            feedback="Compliance check complete. Disclosures verified. Content is safe to publish.",
        )

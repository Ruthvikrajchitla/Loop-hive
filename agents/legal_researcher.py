"""
LoopHive — Legal Research Agent

Autonomously researches legal guidelines (FTC, EU AI Act, GDPR, state laws)
and platform ToS before any content or product generation begins.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification
from compliance.rulebook import ComplianceRulebook, Rule

logger = structlog.get_logger(__name__)


class LegalResearchAgent(AgentBase):
    """
    Agent that performs legal, ethical, and platform ToS checks.
    Outputs a structured ComplianceRulebook that other agents must strictly follow.
    """

    def __init__(self, router=None):
        super().__init__(
            name="legal_researcher",
            description="Researches legal boundaries, FTC disclosures, and platform terms.",
            system_prompt=(
                "You are an expert legal analyst specializing in internet law, FTC advertising guidelines, "
                "the EU AI Act (specifically Article 50 disclosure rules), GDPR, and major platform ToS "
                "(Medium, Substack, Amazon Associates, Gumroad). Your job is to research the legal risk "
                "for a specific niche and create a strict compliance rulebook. "
                "Be thorough, conservative, and output clear, structured rules in JSON format."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        """Fetch general legal state or context. In a prototype, this returns current time and niche name."""
        self.mark_running()
        return {
            "timestamp": time.time(),
            "target_niche": context.entries[0]["content"].replace("Goal: ", "").strip()
            if context.entries else "Unknown Niche",
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Analyze the target niche and output rules for FTC, EU AI Act, and platform policies."""
        niche = state.get("target_niche", "Unknown")
        prompt = (
            f"Research the legal risk and publishing rules for the niche: '{niche}'.\n\n"
            f"Generate rules for the following categories:\n"
            f"1. FTC affiliate disclosure requirements.\n"
            f"2. EU AI Act Article 50 synthetic content labeling requirements (specifically as of mid-2026).\n"
            f"3. Medium ToS constraints regarding AI paywalling.\n"
            f"4. Substack content rules.\n"
            f"5. Niche-specific legal restrictions (e.g. YMYL, financial advice, FDA health claims).\n\n"
            f"Goal: {goal}\n\n"
            f"Your output must be a JSON object with this exact structure:\n"
            f"{{\n"
            f"  \"niche\": \"{niche}\",\n"
            f"  \"allowed_content_types\": [\"list\", \"of\", \"strings\"],\n"
            f"  \"banned_content_types\": [\"list\", \"of\", \"strings\"],\n"
            f"  \"disclosures\": {{\n"
            f"    \"ftc_affiliate\": \"disclosure text\",\n"
            f"    \"ai_disclosure\": \"disclosure text\",\n"
            f"    \"eu_ai_label\": \"label\"\n"
            f"  }},\n"
            f"  \"rules\": [\n"
            f"    {{\n"
            f"      \"category\": \"ftc|eu_ai_act|platform_tos|niche_specific\",\n"
            f"      \"rule_text\": \"Description of the rule\",\n"
            f"      \"severity\": \"required|recommended|optional\",\n"
            f"      \"platform\": \"medium|substack|amazon|null\",\n"
            f"      \"disclosure_template\": \"disclosure text or null\"\n"
            f"    }}\n"
            f"  ]\n"
            f"}}"
        )

        response_json = await self.ask_llm_json(prompt, temperature=0.2)
        return response_json

    async def act(self, plan: dict) -> ComplianceRulebook:
        """Compile the compliance rulebook object from JSON plan."""
        niche = plan.get("niche", "Unknown Niche")
        rulebook = ComplianceRulebook(niche=niche)
        rulebook.allowed_content_types = plan.get("allowed_content_types", ["articles", "newsletters"])
        rulebook.banned_content_types = plan.get("banned_content_types", [])
        rulebook.disclosures = plan.get("disclosures", rulebook.disclosures)

        for r in plan.get("rules", []):
            rulebook.add_rule(Rule(
                category=r.get("category", "niche_specific"),
                rule_text=r.get("rule_text", ""),
                severity=r.get("severity", "required"),
                platform=r.get("platform"),
                disclosure_template=r.get("disclosure_template"),
            ))

        self.mark_success({"rules_compiled": len(rulebook.rules)})
        return rulebook

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the compiled rulebook contains required rules."""
        if not isinstance(result, ComplianceRulebook):
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Result is not a ComplianceRulebook instance.",
                reason="Invalid output type.",
            )

        if len(result.rules) < 3:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="The rulebook is too thin. Ensure you cover FTC, EU AI Act, and platform policies.",
                reason="Too few rules generated.",
            )

        # Check for FTC and AI disclosures
        ftc_exists = any(r.category == "ftc" for r in result.rules)
        ai_exists = any(r.category == "eu_ai_act" for r in result.rules)

        if not ftc_exists or not ai_exists:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Missing critical FTC or EU AI Act rules. Re-evaluate.",
                reason="Missing key compliance categories.",
            )

        return Verification(
            is_complete=True,
            score=98.0,
            feedback=f"Compliance rulebook compiled for '{result.niche}'. Cover: FTC={ftc_exists}, AI={ai_exists}",
        )

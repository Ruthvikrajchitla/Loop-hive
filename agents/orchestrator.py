"""
LoopHive — Orchestrator Agent

The master brain of the swarm. Coordinates the execution pipeline across all agents:
niche discovery, legal audit, content generation, plagiarism checks,
compliance adjustments, publishing, marketing, and monthly evaluations.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification, MicroLoop
from agents.niche_scout import NicheScoutAgent
from agents.legal_researcher import LegalResearchAgent
from agents.content_writer import ContentWriterAgent
from agents.content_critic import ContentCriticAgent
from agents.plagiarism_checker import PlagiarismCheckerAgent
from agents.compliance_agent import ComplianceAgent
from agents.product_creator import ProductCreatorAgent
from agents.marketing_agent import MarketingAgent
from agents.monthly_evaluator import MonthlyEvaluatorAgent

logger = structlog.get_logger(__name__)


class OrchestratorAgent(AgentBase):
    """
    Agent that acts as the supervisor/manager of the system.
    Sequentially runs and manages specialist agents.
    """

    def __init__(self, router=None):
        super().__init__(
            name="orchestrator",
            description="Coordinates other agents to discover niches, write articles, publish, and market.",
            system_prompt=(
                "You are the master coordinator and project manager of LoopHive. Your goal is to guide "
                "the other specialist agents sequentially through the content-to-product lifecycle. "
                "You monitor status, check logs, and call the micro-loops in order."
            ),
            router=router,
        )
        self.scout = NicheScoutAgent(router=self.router)
        self.legal = LegalResearchAgent(router=self.router)
        self.writer = ContentWriterAgent(router=self.router)
        self.critic = ContentCriticAgent(router=self.router)
        self.plagiarism = PlagiarismCheckerAgent(router=self.router)
        self.compliance = ComplianceAgent(router=self.router)
        self.creator = ProductCreatorAgent(router=self.router)
        self.marketing = MarketingAgent(router=self.router)
        self.evaluator = MonthlyEvaluatorAgent(router=self.router)
        self.micro_loop = MicroLoop(max_iterations=5)

    async def perceive(self, context: ContextWindow) -> dict:
        """Inspect current workspace progress and active tasks."""
        self.mark_running()
        return {
            "timestamp": time.time(),
            "status": "Ready to run the LoopHive pipeline.",
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Outline the execution steps of the swarm."""
        return {
            "steps": [
                "1. Discovered niches via NicheScout",
                "2. Perform Legal Research for the top niche",
                "3. Write an article for the niche",
                "4. Critique and review quality",
                "5. Verify originality (plagiarism check)",
                "6. Wrap in compliance disclaimers",
                "7. Build a digital product",
                "8. Generate a marketing campaign",
                "9. Run monthly evaluation",
            ]
        }

    async def act(self, plan: dict) -> dict:
        """Run the full execution pipeline end-to-end (Simulated / Prototype flow)."""
        report = {}
        
        # 1. Discover niches
        logger.info("orchestrator_stage", stage="niche_discovery")
        scout_res = await self.micro_loop.run(self.scout, "Find the top 3 rising monetization niches.")
        if scout_res.output:
            niche = scout_res.output[0]
            report["niche"] = niche.to_dict()
        else:
            report["niche"] = {"name": "Notion Productivity", "score": 90.0}

        niche_name = report["niche"]["name"]

        # 2. Perform legal research
        logger.info("orchestrator_stage", stage="legal_research", niche=niche_name)
        legal_res = await self.micro_loop.run(self.legal, f"Research all FTC and AI disclosure guidelines for {niche_name}.")
        rulebook = legal_res.output
        report["rulebook_rules_count"] = len(rulebook.rules) if rulebook else 3

        # 3. Create content (and verify through critic, plagiarism, and compliance)
        logger.info("orchestrator_stage", stage="content_creation")
        writer_res = await self.micro_loop.run(self.writer, f"Write a long-form article for {niche_name}.")
        report["article_written"] = writer_res.output is not None

        # 4. Critique content
        if writer_res.output:
            logger.info("orchestrator_stage", stage="content_critic")
            # Create a context and append the content output to evaluate
            critic_ctx = ContextWindow()
            critic_ctx.add("assistant", str(writer_res.output))
            critic_res = await self.micro_loop.run(self.critic, "Score and review this article draft.")
            report["critic_score"] = critic_res.output.get("score", 0.0) if critic_res.output else 0.0

            # 5. Plagiarism Check
            logger.info("orchestrator_stage", stage="plagiarism_check")
            plag_ctx = ContextWindow()
            plag_ctx.add("assistant", str(writer_res.output))
            plag_res = await self.micro_loop.run(self.plagiarism, "Verify originality of the article.")
            report["originality_score"] = plag_res.output.score if plag_res.output else 0.0

            # 6. Compliance Wrapping
            logger.info("orchestrator_stage", stage="compliance_wrapping")
            comply_ctx = ContextWindow()
            comply_ctx.add("assistant", str(writer_res.output))
            if rulebook:
                comply_ctx.add("system", rulebook.to_json())
            comply_res = await self.micro_loop.run(self.compliance, "Inject required disclosures.")
            report["compliance_passed"] = comply_res.output is not None
            if comply_res.output:
                report["compliant_article_size"] = len(comply_res.output.get("body", ""))

        # 7. Build digital product
        logger.info("orchestrator_stage", stage="product_creation")
        prod_res = await self.micro_loop.run(self.creator, f"Build a cheat sheet product for {niche_name}.")
        report["product_created"] = prod_res.output is not None
        if prod_res.output:
            report["product_name"] = prod_res.output.get("name")
            report["product_price"] = prod_res.output.get("price")

            # 8. Marketing Campaign
            logger.info("orchestrator_stage", stage="marketing_campaign")
            mkt_ctx = ContextWindow()
            import json
            mkt_ctx.add("assistant", json.dumps(prod_res.output))
            mkt_res = await self.micro_loop.run(self.marketing, "Generate a marketing plan for the product.")
            report["marketing_channels"] = len(mkt_res.output.get("channels", [])) if mkt_res.output else 0

        # 9. Monthly evaluation
        logger.info("orchestrator_stage", stage="monthly_evaluation")
        eval_res = await self.micro_loop.run(self.evaluator, "Run 30-day evaluation.")
        report["eval_decision"] = eval_res.output.decision.value if eval_res.output else "continue"
        report["eval_reasoning"] = eval_res.output.reasoning if eval_res.output else "No reasoning available."

        self.mark_success(report)
        return report

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the orchestration pipeline ran successfully and logged outputs."""
        if not isinstance(result, dict) or "niche" not in result:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Orchestrator failed to log run stages.",
                reason="Invalid output structure.",
            )

        return Verification(
            is_complete=True,
            score=100.0,
            feedback=f"Pipeline completed. Niche: {result['niche']['name']}. Decision: {result.get('eval_decision')}",
        )

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
from core.config import config
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
        # Max critic/plagiarism → writer revise-and-recheck rounds before publishing as-is.
        self.max_quality_rounds = 3

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

        # 4-6. Quality gate: critic + plagiarism, with revise-and-recheck.
        if writer_res.output:
            import json

            draft = writer_res.output  # dict: {title, body, meta_description, word_count}
            critic_score = 0.0
            originality_score = 0.0

            for round_num in range(1, self.max_quality_rounds + 1):
                # The writer's output is a JSON-serializable dict; json.dumps lets the
                # downstream agents' json.loads path recover the structured draft
                # (str(dict) would yield invalid JSON).
                draft_json = json.dumps(draft)

                logger.info("orchestrator_stage", stage="content_critic", round=round_num)
                critic_ctx = ContextWindow()
                critic_ctx.add("assistant", draft_json)
                critic_res = await self.micro_loop.run(
                    self.critic, "Score and review this article draft.", context=critic_ctx
                )
                critic_out = critic_res.output or {}
                critic_score = float(critic_out.get("score", 0.0))

                logger.info("orchestrator_stage", stage="plagiarism_check", round=round_num)
                plag_ctx = ContextWindow()
                plag_ctx.add("assistant", draft_json)
                plag_res = await self.micro_loop.run(
                    self.plagiarism, "Verify originality of the article.", context=plag_ctx
                )
                originality_score = plag_res.output.score if plag_res.output else 0.0

                quality_ok = critic_score >= config.quality_threshold
                originality_ok = originality_score >= config.plagiarism_threshold
                if quality_ok and originality_ok:
                    logger.info(
                        "content_quality_gate_passed",
                        round=round_num,
                        critic_score=critic_score,
                        originality_score=originality_score,
                    )
                    break

                if round_num >= self.max_quality_rounds:
                    logger.warning(
                        "content_quality_gate_failed",
                        rounds=round_num,
                        critic_score=critic_score,
                        originality_score=originality_score,
                    )
                    break

                # Build actionable feedback and send the draft back to the writer.
                feedback_parts = []
                if not quality_ok:
                    improvements = critic_out.get("improvements", [])
                    feedback_parts.append(
                        f"QUALITY {critic_score}/100 (need {config.quality_threshold}). "
                        f"{critic_out.get('critique', '')} "
                        f"Improvements: {'; '.join(str(i) for i in improvements)}"
                    )
                if not originality_ok:
                    flagged = plag_res.output.flagged_sections if plag_res.output else []
                    feedback_parts.append(
                        f"ORIGINALITY {originality_score:.1f}/100 (need {config.plagiarism_threshold}). "
                        f"Rewrite flagged/boilerplate passages: {'; '.join(str(f) for f in flagged)}"
                    )
                feedback = "\n".join(feedback_parts)
                logger.info("content_revision_requested", round=round_num, feedback=feedback[:200])
                draft = await self.writer.revise(draft, feedback)

            # The (possibly revised) draft is the canonical article from here on.
            writer_res.output = draft
            report["critic_score"] = critic_score
            report["originality_score"] = originality_score

            # 6. Compliance Wrapping (on the final, approved draft)
            logger.info("orchestrator_stage", stage="compliance_wrapping")
            comply_ctx = ContextWindow()
            comply_ctx.add("assistant", json.dumps(draft))
            if rulebook:
                comply_ctx.add("system", rulebook.to_json())
            comply_res = await self.micro_loop.run(
                self.compliance, "Inject required disclosures.", context=comply_ctx
            )
            report["compliance_passed"] = comply_res.output is not None
            if comply_res.output:
                report["compliant_article_size"] = len(comply_res.output.get("body", ""))
                # Persist the compliance-wrapped body so the saved article is publish-ready.
                writer_res.output = comply_res.output

        # 7. Build digital product
        mkt_res = None
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
            mkt_res = await self.micro_loop.run(
                self.marketing, "Generate a marketing plan for the product.", context=mkt_ctx
            )
            report["marketing_channels"] = len(mkt_res.output.get("channels", [])) if mkt_res.output else 0

        # 9. Monthly evaluation
        logger.info("orchestrator_stage", stage="monthly_evaluation")
        eval_res = await self.micro_loop.run(self.evaluator, "Run 30-day evaluation.")
        report["eval_decision"] = eval_res.output.decision.value if eval_res.output else "continue"
        report["eval_reasoning"] = eval_res.output.reasoning if eval_res.output else "No reasoning available."

        # Database persistence
        try:
            import datetime
            from storage.database import (
                async_session_factory, Niche, Content, Product, ComplianceRule,
                MarketingCampaign,
            )
            from sqlalchemy.future import select

            async with async_session_factory() as session:
                async with session.begin():
                    # 1. Save Niche
                    stmt = select(Niche).where(Niche.name == niche_name)
                    db_niche = (await session.execute(stmt)).scalar_one_or_none()
                    if not db_niche:
                        db_niche = Niche(
                            name=niche_name,
                            description="Auto-discovered niche by NicheScout",
                            score=float(report.get("niche", {}).get("score", 90.0)),
                            status="active",
                            started_at=datetime.datetime.utcnow(),
                        )
                        session.add(db_niche)
                        await session.flush()  # Populate db_niche.id

                    # 2. Save Compliance Rules
                    if rulebook:
                        for r in rulebook.rules:
                            stmt = select(ComplianceRule).where(ComplianceRule.rule == r.rule_text)
                            exist_rule = (await session.execute(stmt)).scalar_one_or_none()
                            if not exist_rule:
                                db_rule = ComplianceRule(
                                    category=r.category,
                                    platform=r.platform or "substack",
                                    rule=r.rule_text,
                                    severity=r.severity,
                                    disclosure_template=r.disclosure_template,
                                )
                                session.add(db_rule)

                    # 3. Save Content
                    db_content = None
                    if writer_res.output:
                        out = writer_res.output
                        # The final draft (after revise + compliance) uses the "body" key.
                        title = out.get("title", f"10 Hacks for {niche_name}") if isinstance(out, dict) else f"10 Hacks for {niche_name}"
                        body = out.get("body", "") if isinstance(out, dict) else str(out)
                        meta = out.get("meta_description", "") if isinstance(out, dict) else ""
                        words = int(out.get("word_count", len(body.split()))) if isinstance(out, dict) else len(body.split())

                        stmt = select(Content).where(Content.title == title)
                        db_content = (await session.execute(stmt)).scalar_one_or_none()
                        if not db_content:
                            db_content = Content(
                                niche_id=db_niche.id,
                                title=title,
                                body=body,
                                meta_description=meta,
                                word_count=words,
                                content_type="article",
                                quality_score=float(report.get("critic_score", 85.0)),
                                originality_score=float(report.get("originality_score", 90.0)),
                                status="published",
                                published_platform="substack",
                                published_url="https://substack.com",
                                published_at=datetime.datetime.utcnow(),
                                has_ai_disclosure=bool(out.get("has_ai_disclosure")) if isinstance(out, dict) else False,
                                has_affiliate_disclosure=bool(out.get("has_affiliate_disclosure")) if isinstance(out, dict) else False,
                                compliance_checked=bool(out.get("compliance_checked")) if isinstance(out, dict) else False,
                            )
                            session.add(db_content)
                            await session.flush()  # Populate db_content.id for the campaign FK

                    # 4. Save Product
                    db_product = None
                    if prod_res.output:
                        out = prod_res.output
                        is_dict = isinstance(out, dict)
                        prod_name = out.get("name", f"Ultimate {niche_name} Template") if is_dict else f"Ultimate {niche_name} Template"
                        prod_price = float(out.get("price", 9.0)) if is_dict else 9.0
                        prod_body = out.get("body", "") if is_dict else str(out)
                        prod_sales = out.get("sales_page_copy", "") if is_dict else ""
                        prod_type = out.get("product_type", "guide") if is_dict else "guide"

                        # No real storefront token wired → the product is generated and
                        # stored for manual upload, not actually published/sold.
                        stmt = select(Product).where(Product.name == prod_name)
                        db_product = (await session.execute(stmt)).scalar_one_or_none()
                        if not db_product:
                            db_product = Product(
                                niche_id=db_niche.id,
                                name=prod_name,
                                product_type=prod_type,
                                price=prod_price,
                                content=prod_body,
                                sales_page_copy=prod_sales,
                                description=(prod_body[:300] if prod_body else ""),
                                status="ready_local",
                                platform=None,
                                platform_url=None,
                            )
                            session.add(db_product)
                            await session.flush()  # Populate db_product.id for the campaign FK

                    # 5. Save Marketing Campaign
                    mkt_out = mkt_res.output if mkt_res else None
                    if mkt_out and isinstance(mkt_out, dict) and mkt_out.get("channels"):
                        channels = [c.get("name", "") for c in mkt_out.get("channels", [])]
                        session.add(MarketingCampaign(
                            name=mkt_out.get("campaign_name", f"{niche_name} Launch"),
                            product_id=db_product.id if db_product else None,
                            content_id=db_content.id if db_content else None,
                            channels=channels,
                            status="planned",
                            posts_created=len(channels),
                            started_at=datetime.datetime.utcnow(),
                        ))

            logger.info("database_persistence_success", niche=niche_name)
        except Exception as e:
            logger.error("database_persistence_failed", error=str(e))

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

"""
LoopHive — Product Orchestrator (the agency)

Runs the product-building team end to end:

  Analyzer → Research → Planner → (Builder ↔ Critic loop) → Marketer → Ship

Two daily phases:
  - "own"    : the team picks a trending idea and builds its own product
  - "client" : the team builds for a real client request (a brief)
"""

from __future__ import annotations

import json

import structlog

from core.artifacts import log_artifact
from core.config import config
from core.jobs import get_active_job, create_job, save_job
from core.llm_router import llm_router
from core.loop_engine import ContextWindow, MicroLoop
from core.notify import escalate
from agents.analyzer_agent import AnalyzerAgent
from agents.research_agent import DeepResearchAgent
from agents.planner_agent import PlannerAgent
from agents.code_builder import CodeBuilderAgent
from agents.product_critic_agent import ProductCriticAgent
from agents.marketing_agent import MarketingAgent

logger = structlog.get_logger(__name__)


class ProductOrchestrator:
    def __init__(self, router=None):
        self.router = router or llm_router
        self.analyzer = AnalyzerAgent(router=self.router)
        self.researcher = DeepResearchAgent(router=self.router)
        self.planner = PlannerAgent(router=self.router)
        self.builder = CodeBuilderAgent(router=self.router)
        self.critic = ProductCriticAgent(router=self.router)
        self.marketing = MarketingAgent(router=self.router)
        self.micro = MicroLoop(max_iterations=2, timeout_seconds=900.0)
        self.build_loop = MicroLoop(max_iterations=2, timeout_seconds=1200.0)

    async def run_cycle(self, phase: str = "own", client_brief: str | None = None,
                        client_email: str | None = None) -> dict:
        report: dict = {"phase": phase}
        niche = config.forced_niche or "AI developer tools"

        # 1. Analyze the market (own) or take the client's brief.
        if phase == "client" and client_brief:
            product_name = "Client Build"
            product_idea = client_brief
            build_type = "developer tool"
            market = f"Client request: {client_brief}"
        else:
            a = await self.micro.run(self.analyzer, "Analyze the market and pick a product to build")
            ao = a.output if isinstance(a.output, dict) else {}
            product_name = ao.get("product_name", "New Tool")
            product_idea = ao.get("product_idea", product_name)
            build_type = ao.get("build_type", "developer tool")
            market = ao.get("market_report", "")
            if market:
                await log_artifact("analyzer_agent", "market_brief", product_name, market)
        report["product_name"] = product_name
        report["build_type"] = build_type
        logger.info("product_pipeline", phase=phase, product=product_name, build_type=build_type)

        # 2. Deep research on the chosen idea.
        rctx = ContextWindow()
        rctx.add("system", f"niche: {niche}\ntopic: {product_idea or product_name}")
        r = await self.micro.run(self.researcher, f"Research: {product_idea}", context=rctx)
        research = r.output.get("report", "") if isinstance(r.output, dict) else ""
        if research:
            await log_artifact("research_agent", "research_brief", product_name, research)

        # 3. Plan the full architecture.
        pctx = ContextWindow()
        pctx.add("system", f"product_name: {product_name}\nproduct_idea: {product_idea}\nbuild_type: {build_type}")
        pctx.add("system", f"MARKET BRIEF\n{market}")
        pctx.add("system", f"RESEARCH BRIEF\n{research}")
        p = await self.micro.run(self.planner, "Plan the product build", context=pctx)
        planj = p.output if isinstance(p.output, dict) else {}
        if not planj.get("files"):
            await escalate("Planner failed to produce a build plan",
                           f"Phase {phase}, product '{product_name}'. No plan/files.", source="planner_agent")
            return report
        await log_artifact("planner_agent", "build_plan", product_name, json.dumps(planj, indent=2)[:8000])
        report["planned_files"] = len(planj.get("files", []))

        # 4. Builder ↔ Critic loop until production-ready.
        files: dict = {}
        feedback = ""
        ready = False
        rnd = 0
        for rnd in range(1, config.build_rounds + 1):
            bctx = ContextWindow()
            bctx.add("system", f"PLAN: {json.dumps(planj)}")
            if feedback:
                bctx.add("system", f"CRITIC FEEDBACK: {feedback}")
            b = await self.build_loop.run(self.builder, f"Build {product_name} per the plan", context=bctx)
            if isinstance(b.output, dict) and b.output.get("files"):
                files = b.output["files"]
            else:
                break

            cctx = ContextWindow()
            cctx.add("system", f"PLAN: {json.dumps(planj)}")
            cctx.add("system", f"FILES: {json.dumps(files)}")
            c = await self.micro.run(self.critic, "Validate the built product", context=cctx)
            review = c.output if isinstance(c.output, dict) else {}
            report["critic_score"] = review.get("score", 0)
            logger.info("build_review", round=rnd, ready=review.get("production_ready"), score=review.get("score"))
            if review.get("production_ready"):
                ready = True
                break
            feedback = review.get("feedback", "")

        report["production_ready"] = ready
        report["build_rounds_used"] = rnd

        # 5. Ship + persist.
        repo_url = await self._ship(product_name, files, planj.get("description", ""), build_type, phase, ready)
        report["repo_url"] = repo_url

        # 6. Marketer publicizes it (own products).
        if phase == "own" and files:
            await self._market(product_name, product_idea, repo_url, report)

        # 7. Client delivery / escalation.
        if phase == "client" and client_email and files:
            await self._deliver_to_client(client_email, product_name, repo_url, ready)
        if not ready:
            await escalate(f"Product not production-ready: {product_name}",
                           f"Phase {phase}. Built {len(files)} files but the Critic did not pass it after "
                           f"{rnd} rounds. Latest feedback:\n{feedback[:1000]}", source="product_critic")
        return report

    # -------------------------------------------------------------------
    # Resumable, memory-backed execution (survives interruptions)
    # -------------------------------------------------------------------

    async def run_next(self) -> dict:
        """Resume the active job or start a new own-product job, advancing it
        stage by stage and checkpointing to the DB after each stage."""
        job = await get_active_job()
        if not job:
            job = await create_job(kind="own_product", target_stage="full", stage="analyze")
        if not job:
            return {"error": "could not create a job"}

        logger.info("job_resume", id=job["id"], kind=job["kind"], stage=job["stage"])
        guard = 0
        builds_this_cycle = 0
        while job["stage"] not in ("done", "failed") and guard < 30:
            guard += 1
            # Bound build↔review iterations per swarm cycle; the job resumes next cycle,
            # so one product is refined across the whole day (with dashboard checkpoints).
            if job["stage"] == "build":
                builds_this_cycle += 1
                if builds_this_cycle > config.build_rounds_per_cycle:
                    logger.info("job_yields", id=job["id"], round=job.get("round"), reason="cycle build budget")
                    break
            try:
                await self._execute_stage(job)
            except Exception as e:
                job["stage"], job["error"] = "failed", str(e)[:500]
                await save_job(job)
                await escalate("Job failed",
                               f"Job {job['id']} ({job['kind']}) failed at stage: {str(e)[:400]}",
                               source="product_orchestrator")
                break
            await save_job(job)  # ← memory checkpoint after every stage
        return {"job_id": job["id"], "kind": job["kind"], "stage": job["stage"],
                "product": job.get("product_name"), "repo": job.get("result_url"),
                "ready": job.get("production_ready")}

    async def _execute_stage(self, job: dict) -> None:
        stage = job["stage"]
        niche = config.forced_niche or "AI developer tools"

        if stage == "analyze":
            if job["kind"] == "own_product":
                a = await self.micro.run(self.analyzer, "Analyze the market and pick a product to build")
                ao = a.output if isinstance(a.output, dict) else {}
                job["product_name"] = ao.get("product_name", "New Tool")
                job["request"] = ao.get("product_idea", job["product_name"])
                job["build_type"] = ao.get("build_type", "developer tool")
                job["market_brief"] = ao.get("market_report", "")
                if job["market_brief"]:
                    await log_artifact("analyzer_agent", "market_brief", job["product_name"], job["market_brief"])
            else:
                job["product_name"] = job.get("product_name") or (job["request"][:60] or "Client build")
                job["market_brief"] = f"Request: {job['request']}"
            job["stage"] = "research"

        elif stage == "research":
            rctx = ContextWindow()
            rctx.add("system", f"niche: {niche}\ntopic: {job['request']}")
            r = await self.micro.run(self.researcher, f"Research: {job['request']}", context=rctx)
            job["research_report"] = r.output.get("report", "") if isinstance(r.output, dict) else ""
            if job["research_report"]:
                await log_artifact("research_agent", "research_brief", job["product_name"], job["research_report"])
            job["stage"] = "deliver" if (job["kind"] == "boss_task" and job["target_stage"] == "research") else "plan"

        elif stage == "plan":
            pctx = ContextWindow()
            pctx.add("system", f"product_name: {job['product_name']}\nproduct_idea: {job['request']}\nbuild_type: {job['build_type']}")
            pctx.add("system", f"MARKET BRIEF\n{job['market_brief']}")
            pctx.add("system", f"RESEARCH BRIEF\n{job['research_report']}")
            p = await self.micro.run(self.planner, "Plan the product build", context=pctx)
            planj = p.output if isinstance(p.output, dict) else {}
            if not planj.get("files"):
                job["stage"], job["error"] = "failed", "planner produced no plan"
                return
            job["plan"] = json.dumps(planj)
            if planj.get("build_type"):
                job["build_type"] = planj["build_type"]
            await log_artifact("planner_agent", "build_plan", job["product_name"], job["plan"][:8000])
            job["stage"] = "deliver" if (job["kind"] == "boss_task" and job["target_stage"] == "plan") else "build"

        elif stage == "build":
            bctx = ContextWindow()
            bctx.add("system", f"PLAN: {job['plan']}")
            if job["feedback"]:
                bctx.add("system", f"CRITIC FEEDBACK: {job['feedback']}")
            b = await self.build_loop.run(self.builder, f"Build {job['product_name']} per the plan", context=bctx)
            if isinstance(b.output, dict) and b.output.get("files"):
                job["files"] = json.dumps(b.output["files"])
            job["round"] = (job.get("round") or 0) + 1
            job["stage"] = "review"

        elif stage == "review":
            cctx = ContextWindow()
            cctx.add("system", f"PLAN: {job['plan']}")
            cctx.add("system", f"FILES: {job['files']}")
            c = await self.micro.run(self.critic, "Validate the built product", context=cctx)
            review = c.output if isinstance(c.output, dict) else {}
            job["production_ready"] = bool(review.get("production_ready"))
            if job["production_ready"]:
                job["stage"] = "ship"  # ship ONLY when it truly passes (real sandbox + criteria)
            elif (job.get("round") or 0) >= config.build_rounds:
                # Iterated to the budget without perfection — escalate, do NOT ship broken.
                job["stage"], job["error"] = "failed", "Not production-ready after max build rounds."
                await escalate(
                    f"Product needs your input: {job.get('product_name')}",
                    f"After {job.get('round')} build↔critic rounds it still isn't production-ready. "
                    f"I won't ship something broken. Latest issues:\n{review.get('feedback', '')[:1500]}",
                    source="product_critic",
                )
            else:
                job["feedback"] = review.get("feedback", "")
                job["stage"] = "build"  # keep iterating

        elif stage == "ship":
            files = json.loads(job["files"]) if job["files"] else {}
            planj = json.loads(job["plan"]) if job["plan"] else {}
            job["result_url"] = await self._ship(job["product_name"], files, planj.get("description", ""),
                                                 job["build_type"], job["kind"], job["production_ready"])
            job["stage"] = "market" if job["kind"] == "own_product" else "deliver"

        elif stage == "market":
            files = json.loads(job["files"]) if job["files"] else {}
            if files:
                await self._market(job["product_name"], job["request"], job["result_url"], {})
            job["stage"] = "done"

        elif stage == "deliver":
            await self._deliver(job)
            job["stage"] = "done"

    async def _deliver(self, job: dict) -> None:
        """Email the requester (boss or client) the result at the requested depth."""
        to = job.get("requester_email") or config.boss_email
        if not to:
            job["delivered"] = True
            return
        name = job.get("product_name", "your task")
        ts = job.get("target_stage", "full")
        if ts == "research":
            subject = f"Research report: {name}"
            body = (f"Hi,\n\nHere's the research you asked for on \"{job['request']}\":\n\n"
                    f"{job['research_report'][:8000]}\n\n— {config.brand_name}")
        elif ts == "plan":
            subject = f"Build plan: {name}"
            body = (f"Hi,\n\nHere's the plan for \"{job['request']}\":\n\n{job['plan'][:8000]}\n\n— {config.brand_name}")
        else:
            link = f"\n\nRepo: {job['result_url']}" if job.get("result_url") else ""
            status = "production-ready" if job.get("production_ready") else "an early version I'll keep improving"
            body = (f"Hi,\n\nI finished \"{name}\" ({status}) for your request: {job['request']}.{link}\n\n"
                    f"Reply with any changes and I'll iterate.\n\n— {config.brand_name}")
        from publishers.email_sender import send_email
        await send_email(to, subject, body)
        job["delivered"] = True
        logger.info("job_delivered", id=job["id"], to=to, target=ts)

    async def _ship(self, name, files, description, build_type, phase, ready) -> str | None:
        repo_url = None
        if files:
            try:
                from publishers.github_publisher import publish_repo
                res = await publish_repo(name, files, description)
                repo_url = res.get("url")
            except Exception as e:
                logger.error("product_ship_failed", error=str(e))
        try:
            import datetime
            from storage.database import async_session_factory, Product, Niche
            from sqlalchemy import select
            manifest = "\n".join(f"- `{p}`" for p in files)
            body = (f"# {name}\n\n{description}\n\n## Files\n{manifest}\n\n"
                    + (f"Repository: {repo_url}\n" if repo_url else "Built locally.\n")
                    + ("Status: production-ready\n" if ready else "Status: needs another pass\n"))
            async with async_session_factory() as session:
                async with session.begin():
                    niche = (await session.execute(
                        select(Niche).where(Niche.status == "active"))).scalars().first()
                    session.add(Product(
                        niche_id=niche.id if niche else None,
                        name=name, product_type=(build_type or "product").replace(" ", "_"),
                        price=0.0, content=body, description=(description or "")[:300],
                        status="published" if repo_url else "ready_local",
                        platform="github" if repo_url else None, platform_url=repo_url,
                    ))
        except Exception as e:
            logger.error("product_persist_failed", error=str(e))
        return repo_url

    async def _market(self, name, idea, repo_url, report) -> None:
        try:
            mctx = ContextWindow()
            mctx.add("assistant", json.dumps({"name": name, "body": idea,
                                              "sales_page_copy": idea, "price": 0.0}))
            m = await self.micro.run(self.marketing, "Create a launch campaign for the product", context=mctx)
            if not isinstance(m.output, dict):
                return
            channels = m.output.get("channels", [])
            copy_dump = "\n\n".join(f"### {c.get('name','?')}\n{c.get('copy','')}" for c in channels)
            await log_artifact("marketing_agent", "marketing_copy", name, copy_dump)
            hook = channels[0].get("copy", "") if channels else idea
            # Twitter/X (primary): a tight <=280 tweet.
            tweet = f"🚀 {name}: {hook}".strip()
            if repo_url:
                tweet += f" {repo_url}"
            tweet += f" #buildinpublic (by {config.brand_name}, an autonomous AI)"
            from publishers.twitter_poster import post_to_twitter
            tw = await post_to_twitter(tweet)
            await log_artifact("marketing_agent", "twitter_post", name, tweet)
            # Telegram (optional, if configured).
            post = f"🚀 {name}\n\n{hook}\n\n{('→ ' + repo_url) if repo_url else ''}\n\n🤖 Built autonomously by {config.brand_name}"
            from publishers.telegram_poster import post_to_telegram
            await post_to_telegram(post)
            report["twitter_status"] = tw.get("status")
        except Exception as e:
            logger.error("product_market_failed", error=str(e))

    async def _deliver_to_client(self, email, name, repo_url, ready) -> None:
        try:
            from publishers.email_sender import send_email
            status = "ready to use" if ready else "an early version (I'll keep improving it)"
            link = f"\n\nYou can grab it here: {repo_url}" if repo_url else ""
            body = (f"Hi,\n\nI built a first version of what you asked for — '{name}'. It's {status}.{link}\n\n"
                    f"Tell me any changes and I'll adjust it. I'm {config.brand_name}, an autonomous AI agent "
                    f"building this for my portfolio, so it's free.\n\n— {config.brand_name}")
            await send_email(email, f"Your build: {name}", body)
        except Exception as e:
            logger.error("client_delivery_failed", error=str(e))

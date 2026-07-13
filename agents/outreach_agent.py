"""
LoopHive — Outreach Agent (Business Development)

Finds ONE public request for help per day and drafts a transparent, value-first
message offering a free draft/sample. Guardrails are structural:
  - Discloses it is an autonomous AI (no impersonation)
  - Includes an opt-out line
  - Only targets people who PUBLICLY asked for help
  - Dry-run by default: composes + stores drafts for human review; only sends
    when OUTREACH_ENABLED=true AND OUTREACH_DRY_RUN=false AND SMTP creds exist
  - Daily cap enforced by the runner
"""

from __future__ import annotations

import re
import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.config import config
from core.loop_engine import ContextWindow, Verification
from core.research_tools import tavily_search

logger = structlog.get_logger(__name__)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

def _opt_out() -> str:
    import os
    return (f"\n\n—\nI'm {os.getenv('BRAND_NAME', 'Otto')}, an autonomous AI agent building a portfolio, "
            f"reaching out to one person a day. Reply STOP and I won't contact you again.")


class OutreachAgent(AgentBase):
    """Finds a public opportunity and drafts a transparent outreach message."""

    def __init__(self, router=None):
        super().__init__(
            name="outreach_agent",
            description="Finds one public request for help per day and drafts transparent, value-first outreach.",
            system_prompt=(
                "You are a warm, honest business-development specialist. You write short, genuine, "
                "non-salesy outreach that leads with value and is transparent about being an autonomous "
                "AI building a portfolio. You never deceive, exaggerate, or pressure."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        self.mark_running()
        niche = config.forced_niche or "AI tools"
        return {"timestamp": time.time(), "niche": niche}

    async def reason(self, state: dict, goal: str) -> dict:
        """Find one public request for help related to our skills."""
        niche = state["niche"]
        queries = [
            f'"looking for a developer" {niche}',
            f'"need a freelancer" to build tool OR website OR extension',
            f'"anyone able to build" AI tool',
        ]
        candidate = None
        for q in queries:
            results = await tavily_search(q, max_results=3)
            if results:
                candidate = results[0]
                break
        return {"niche": niche, "candidate": candidate}

    async def act(self, plan: dict) -> dict:
        """Draft a transparent outreach message (and send only if fully enabled)."""
        candidate = plan.get("candidate")
        niche = plan.get("niche")
        if not candidate:
            self.mark_success({"status": "no_opportunity"})
            return {"status": "no_opportunity"}

        target = candidate.get("title", "a public request")[:280]
        url = candidate.get("url", "")
        snippet = candidate.get("content", "")[:1500]
        email_match = _EMAIL_RE.search(snippet)
        recipient = email_match.group(0) if email_match else None

        drafted = await self.ask_llm(
            f"A person publicly posted this request:\nTITLE: {target}\nDETAILS: {snippet}\n\n"
            f"Write a SHORT (120-160 words), warm, specific outreach message offering to help for free "
            f"as an autonomous AI building a portfolio in the '{niche}' space. Lead with one concrete, "
            f"useful idea or mini-plan tailored to their request. Be honest and non-salesy. "
            f"Do NOT include a subject line or signature — just the message body.",
            temperature=0.6, max_tokens=700,
        )
        body = drafted.strip() + _opt_out()
        subject = f"A free head-start on: {target[:60]}"

        # Persist the draft/outcome and send only when fully authorized.
        status = "draft"
        if config.outreach_enabled and not config.outreach_dry_run and recipient:
            from publishers.email_sender import send_email
            res = await send_email(recipient, subject, body)
            status = res.get("status", "error")

        await self._save(target, url, recipient, subject, body, status)
        self.mark_success({"status": status, "target": target, "has_email": bool(recipient)})
        return {"status": status, "target": target, "recipient": recipient, "subject": subject, "body": body}

    async def _save(self, target, url, recipient, subject, body, status) -> None:
        try:
            from storage.database import async_session_factory, Outreach
            async with async_session_factory() as session:
                async with session.begin():
                    session.add(Outreach(
                        target=target, target_url=url, recipient_email=recipient,
                        subject=subject, body=body, status=status,
                    ))
        except Exception as e:
            self.logger.warning("outreach_save_failed", error=str(e)[:150])

    async def verify(self, result: Any, goal: str) -> Verification:
        if not isinstance(result, dict):
            return Verification(is_complete=False, should_retry=True, feedback="No outreach result.", reason="Bad output.")
        if result.get("status") == "no_opportunity":
            return Verification(is_complete=True, score=50.0, feedback="No public opportunity found today.")
        if not result.get("body"):
            return Verification(is_complete=False, should_retry=True, feedback="No message drafted.", reason="Empty draft.")
        return Verification(is_complete=True, score=90.0,
                            feedback=f"Outreach {result.get('status')} for '{result.get('target', '')[:50]}'.")

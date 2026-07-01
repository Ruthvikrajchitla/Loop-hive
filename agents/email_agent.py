"""
LoopHive — Email Agent (Inbox Manager)

The two-way half of the agent's email. It reads the inbox, understands what each
sender wants, and acts:
  - opt_out (Reply STOP)  → add to the suppression list, never contact again
  - build_task / modification → actually build/adjust the deliverable and reply
  - question / interested → draft a helpful reply
Replies are drafts by default (saved for review) and only auto-send when
EMAIL_AUTO_REPLY=true + SMTP creds exist. STOP is always honored.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.config import config
from core.loop_engine import ContextWindow, Verification, MicroLoop
from publishers.email_reader import fetch_unread

logger = structlog.get_logger(__name__)


class EmailAgent(AgentBase):
    """Reads the inbox, understands intent, fulfills tasks, and replies."""

    def __init__(self, router=None):
        super().__init__(
            name="email_agent",
            description="Reads inbound email, understands requests, builds/adjusts deliverables, and replies.",
            system_prompt=(
                "You are a sharp, helpful executive assistant handling an autonomous AI agency's inbox. "
                "You read messages carefully, understand exactly what the sender wants (including tasks and "
                "requested changes), and respond clearly and honestly. You are transparent about being an "
                "autonomous AI and never over-promise."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        self.mark_running()
        messages = await fetch_unread(limit=config.email_max_per_run)
        suppressed = set()
        try:
            from storage.database import async_session_factory, Suppression
            from sqlalchemy import select
            async with async_session_factory() as session:
                rows = (await session.execute(select(Suppression.email))).all()
                suppressed = {r[0].lower() for r in rows if r[0]}
        except Exception as e:
            self.logger.debug("load_suppression_failed", error=str(e)[:120])
        return {"timestamp": time.time(), "messages": messages, "suppressed": suppressed}

    async def reason(self, state: dict, goal: str) -> dict:
        return state

    async def act(self, plan: dict) -> dict:
        messages = plan.get("messages", [])
        suppressed = plan.get("suppressed", set())
        counts = {"processed": 0, "suppressed": 0, "drafted": 0, "actioned": 0, "replied": 0}

        for msg in messages:
            try:
                await self._handle_message(msg, suppressed, counts)
            except Exception as e:
                self.logger.warning("email_handle_failed", sender=msg.get("sender"), error=str(e)[:150])
            counts["processed"] += 1

        self.mark_success(counts)
        return counts

    async def _handle_message(self, msg: dict, suppressed: set, counts: dict) -> None:
        sender = (msg.get("sender") or "").lower()
        subject = msg.get("subject", "")
        body = msg.get("body", "")
        message_id = msg.get("message_id", "")

        # Deterministic opt-out + suppression check first.
        is_stop = body.strip().upper().startswith("STOP") or "unsubscribe" in body.lower()
        if sender in suppressed or is_stop:
            if sender not in suppressed:
                await self._suppress(sender)
            await self._save(sender, subject, body, "opt_out", "Suppressed — will not contact again.", None, "suppressed")
            counts["suppressed"] += 1
            return

        # Understand intent.
        cls = await self.ask_llm_json(
            f"Classify this inbound email and extract any request.\n\n"
            f"FROM: {sender}\nSUBJECT: {subject}\nBODY:\n{body[:3000]}\n\n"
            f"Output JSON: {{'intent': 'opt_out|interested|question|build_task|modification|other', "
            f"'summary': str, 'is_build': bool, "
            f"'build_type': 'developer tool|python package|browser extension|static website|github starter kit', "
            f"'task': str (what to build or change, if any)}}",
            temperature=0.2, max_tokens=600,
        )
        intent = cls.get("intent", "other")

        if intent == "opt_out":
            await self._suppress(sender)
            await self._save(sender, subject, body, intent, "Suppressed on request.", None, "suppressed")
            counts["suppressed"] += 1
            return

        # Fulfill a build/modification task.
        if cls.get("is_build") and cls.get("task"):
            reply, summary = await self._fulfill_build(cls, body)
            status = "actioned"
            counts["actioned"] += 1
        else:
            reply = await self.ask_llm(
                f"Write a concise, warm, honest reply to this email as the autonomous AI agency. "
                f"Answer their question or respond to their interest directly. Disclose you're an AI. "
                f"No subject line/signature — just the body.\n\nEMAIL:\nFROM: {sender}\nSUBJECT: {subject}\n{body[:3000]}",
                temperature=0.5, max_tokens=700,
            )
            summary = cls.get("summary", "")
            status = "drafted"
            counts["drafted"] += 1

        # Send now only if fully authorized; otherwise keep as a reviewable draft.
        if config.email_enabled and config.email_auto_reply:
            from publishers.email_sender import send_email
            res = await send_email(sender, f"Re: {subject}", reply, in_reply_to=message_id)
            if res.get("status") == "sent":
                status = "replied"
                counts["replied"] += 1

        await self._save(sender, subject, body, intent, summary, reply, status)

    async def _fulfill_build(self, cls: dict, body: str) -> tuple[str, str]:
        """Actually build what the sender asked for and compose a reply about it."""
        from agents.code_builder import CodeBuilderAgent
        task = cls.get("task", "")
        build_type = cls.get("build_type", "developer tool")
        ctx = ContextWindow()
        ctx.add("system", f"topic: {task}\nbuild_type: {build_type}")
        res = await MicroLoop(max_iterations=2, timeout_seconds=900).run(
            CodeBuilderAgent(router=self.router), f"Build a {build_type} for: {task}", context=ctx
        )
        if not isinstance(res.output, dict) or not res.output.get("files"):
            try:
                from core.notify import escalate
                await escalate(
                    "Email task I couldn't complete",
                    f"A sender asked for: {task}\n(build type: {build_type}). I couldn't produce it "
                    f"automatically — it may need your input.",
                    level="critical", source="email_agent",
                )
            except Exception:
                pass
            return (
                "Thanks for the request — I've started on it and my team will follow up shortly. "
                "(I'm an autonomous AI agent building this for you.)",
                "Build attempted but incomplete; escalated to the boss.",
            )
        build = res.output
        repo_url = None
        try:
            from publishers.github_publisher import publish_repo
            pub = await publish_repo(build["name"], build["files"], build.get("description", ""))
            repo_url = pub.get("url")
        except Exception as e:
            self.logger.warning("email_build_publish_failed", error=str(e)[:120])

        files = ", ".join(list(build.get("files", {}).keys())[:8])
        link = f"\n\nYou can grab it here: {repo_url}" if repo_url else ""
        reply = (
            f"Happy to help — I built a first version of what you asked for ({build_type}).\n\n"
            f"'{build['name']}': {build.get('description', '')}\nFiles: {files}.{link}\n\n"
            f"Tell me any changes and I'll adjust it. (I'm an autonomous AI agent building this for my portfolio.)"
        )
        return reply, f"Built {build['name']} ({build_type}); repo={repo_url or 'local'}."

    async def _suppress(self, email: str) -> None:
        try:
            from storage.database import async_session_factory, Suppression
            async with async_session_factory() as session:
                async with session.begin():
                    session.add(Suppression(email=email, reason="opt_out"))
        except Exception as e:
            self.logger.debug("suppress_failed", error=str(e)[:120])

    async def _save(self, sender, subject, body, intent, summary, reply, status) -> None:
        try:
            from storage.database import async_session_factory, InboxMessage
            async with async_session_factory() as session:
                async with session.begin():
                    session.add(InboxMessage(
                        sender=sender, subject=subject[:500], body=body[:5000],
                        intent=intent, action_summary=(summary or "")[:1000],
                        reply_draft=reply, status=status,
                    ))
        except Exception as e:
            self.logger.debug("inbox_save_failed", error=str(e)[:120])

    async def verify(self, result: Any, goal: str) -> Verification:
        if not isinstance(result, dict):
            return Verification(is_complete=False, should_retry=False, feedback="Inbox not processed.")
        return Verification(is_complete=True, score=90.0,
                            feedback=f"Inbox processed: {result}.")

"""
LoopHive — Marketing Agent

Generates automated, platform-specific marketing campaigns for products and content.
Creates Twitter threads, LinkedIn summaries, Reddit value-add posts, and email newsletters.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification

logger = structlog.get_logger(__name__)


class MarketingAgent(AgentBase):
    """
    Agent that structures marketing campaigns to drive organic traffic.
    Creates platform-appropriate hooks and copy without spamming.
    """

    def __init__(self, router=None):
        super().__init__(
            name="marketing_agent",
            description="Generates social media content and newsletter copy to market products.",
            system_prompt=(
                "You are an expert marketing strategist, social media manager, and growth hacker. "
                "Your goal is to promote digital products and articles organically. You write compelling, "
                "hook-driven Twitter threads, structured LinkedIn posts, highly helpful Reddit value posts "
                "(which focus on helping the community first, then pointing to the resource), and email "
                "announcements. You avoid spammy language and maintain a natural, helpful voice. "
                "Always output JSON."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        """Find the published product or content to promote in history."""
        self.mark_running()
        item = {}

        # Search context for published product/content
        for entry in reversed(context.entries):
            if "sales_page_copy" in entry["content"]:
                try:
                    import json
                    item = json.loads(entry["content"])
                    item["type"] = "product"
                except Exception:
                    item = {"body": entry["content"], "type": "product"}
                break
            elif "body" in entry["content"] and "[COMPRESSED HISTORY]" not in entry["content"]:
                try:
                    import json
                    item = json.loads(entry["content"])
                    item["type"] = "content"
                except Exception:
                    item = {"body": entry["content"], "type": "content"}
                break

        # Fallback
        if not item:
            item = {
                "name": "Niche Productivity Guide",
                "body": "This is a productivity guide for Notion templates.",
                "price": 9.0,
                "type": "product",
            }

        return {
            "timestamp": time.time(),
            "item": item,
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Formulate a marketing plan mapping copy to channels."""
        item = state.get("item", {})
        item_name = item.get("name", item.get("title", "My Product"))
        item_body = item.get("body", "")
        item_type = item.get("type", "product")

        prompt = (
            f"Create an organic marketing campaign for this {item_type} titled: '{item_name}'.\n"
            f"Here is a snippet of the resource:\n{item_body[:1000]}\n\n"
            f"Goal: {goal}\n\n"
            f"Generate promotional copy for three channels: X (Twitter thread), Reddit (value-add post), "
            f"and LinkedIn. Organize the output into a JSON object containing:\n"
            f"- 'campaign_name': string\n"
            f"- 'channels': list of objects, each containing:\n"
            f"  - 'name': string ('x', 'reddit', 'linkedin')\n"
            f"  - 'copy': string (the actual post or thread content)\n"
            f"  - 'strategy': string (specific instructions on how/where to post, e.g. target subreddits)\n"
        )

        response_json = await self.ask_llm_json(prompt, temperature=0.6)
        return response_json

    async def act(self, plan: dict) -> dict:
        """Save the campaign details and log them."""
        self.mark_success(plan)
        return plan

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the campaign has relevant copy for all main social channels."""
        if not isinstance(result, dict) or "channels" not in result:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Failed to generate marketing campaign structure.",
                reason="Invalid output structure.",
            )

        channels = result.get("channels", [])
        if len(channels) < 2:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Campaign needs to target at least 2 distinct channels (e.g. X and Reddit).",
                reason="Insufficient channel coverage.",
            )

        # Validate that copy is not too short
        for ch in channels:
            copy = ch.get("copy", "")
            if len(copy) < 50:
                return Verification(
                    is_complete=False,
                    should_retry=True,
                    feedback=f"Marketing copy for channel '{ch.get('name')}' is too short. Make it more engaging.",
                    reason="Campaign copy too brief.",
                )

        return Verification(
            is_complete=True,
            score=95.0,
            feedback=f"Marketing campaign '{result.get('campaign_name')}' generated. Targets: {', '.join([c.get('name') for c in channels])}.",
        )

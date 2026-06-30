"""
LoopHive — Product Creator Agent

Researches, structures, and designs original, high-value digital products
(ebooks, templates, prompt packs, checklists, cheat sheets) for Gumroad/Payhip.
Also compiles sales page copywriting.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.loop_engine import ContextWindow, Verification

logger = structlog.get_logger(__name__)


class ProductCreatorAgent(AgentBase):
    """
    Agent that structures and generates sellable digital files and guides.
    Outputs the final product payload (PDF/Markdown) and sales copy.
    """

    def __init__(self, router=None):
        super().__init__(
            name="product_creator",
            description="Builds digital products (ebooks, templates) and compiles sales copy.",
            system_prompt=(
                "You are an elite product developer, instructional designer, and copywriter. Your goal "
                "is to create high-value, original educational products (Guides, Checklists, Cheat Sheets, "
                "Prompt packs) that solve real problems. You structure products clearly, make them actionable, "
                "and write compelling landing page sales copy that highlights benefits and features. "
                "Always output JSON."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        """Find the active niche and target product type from context."""
        self.mark_running()
        niche = "Notion Productivity"
        product_type = "checklist"

        # Search context for niche details
        for entry in reversed(context.entries):
            if "niche" in entry["content"].lower():
                # Extract niche name
                lines = entry["content"].split("\n")
                for line in lines:
                    if "niche" in line.lower():
                        parts = line.split(":")
                        if len(parts) > 1:
                            niche = parts[1].strip()
            if "product_type" in entry["content"].lower():
                lines = entry["content"].split("\n")
                for line in lines:
                    if "product_type" in line.lower():
                        parts = line.split(":")
                        if len(parts) > 1:
                            product_type = parts[1].strip()

        return {
            "timestamp": time.time(),
            "niche": niche,
            "product_type": product_type,
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Outline the digital product and structure the chapters or segments (Outline step)."""
        niche = state.get("niche", "General")
        product_type = state.get("product_type", "checklist")

        prompt = (
            f"Design a digital product for the niche '{niche}'.\n"
            f"Product Type: '{product_type}'.\n\n"
            f"Create a comprehensive outline of the product. Identify target audience pain points, "
            f"list core sections/chapters, and suggest a fair price ($2.00 - $19.00).\n\n"
            f"Goal: {goal}\n\n"
            f"Output a JSON object containing:\n"
            f"- 'product_name': string\n"
            f"- 'niche': string\n"
            f"- 'target_price': float\n"
            f"- 'outline': list of section dictionaries (each with 'title' and 'objectives')\n"
            f"- 'pain_points_solved': list of strings\n"
        )

        response_json = await self.ask_llm_json(prompt, temperature=0.5)
        return {
            "state": state,
            "outline": response_json,
        }

    async def act(self, plan: dict) -> dict:
        """Draft the complete product content and sales page copy (Drafting & Sales Copy steps)."""
        state = plan.get("state", {})
        outline = plan.get("outline", {})
        niche = state.get("niche", "General")
        product_type = state.get("product_type", "checklist")
        product_name = outline.get("product_name", f"Ultimate {niche} Guide")
        price = float(outline.get("target_price", 9.0))

        # Generate full product body
        sections_str = "\n".join([
            f"### {s.get('title')}\n- Objectives: {s.get('objectives')}"
            for s in outline.get("outline", [])
        ])

        product_prompt = (
            f"Write the complete content body for a digital product:\n"
            f"Name: {product_name}\n"
            f"Type: {product_type}\n"
            f"Niche: {niche}\n"
            f"Outline:\n{sections_str}\n\n"
            f"Instructions:\n"
            f"- Generate the complete, fully-written text of the product. Do not use placeholders.\n"
            f"- Ensure it is highly detailed, practical, and directly useful. Write in Markdown.\n"
            f"- Include actionable steps, tips, and exercises."
        )

        product_body = await self.ask_llm(product_prompt, temperature=0.6)

        # Generate Sales landing page copy
        sales_prompt = (
            f"Write high-converting sales landing page copy for the product:\n"
            f"Name: {product_name}\n"
            f"Price: ${price:.2f}\n"
            f"Niche: {niche}\n"
            f"Product Description Snippet:\n{product_body[:1000]}\n\n"
            f"Structure the copy with:\n"
            f"1. A hook headline\n"
            f"2. Pain points addressed\n"
            f"3. Core benefits/features (what they get)\n"
            f"4. Target buyer definition ('Who is this for?')\n"
            f"5. A strong call-to-action (CTA)\n\n"
            f"Output the sales copy in Markdown."
        )

        sales_copy = await self.ask_llm(sales_prompt, temperature=0.7)

        result = {
            "name": product_name,
            "product_type": product_type,
            "price": price,
            "body": product_body,
            "sales_page_copy": sales_copy,
        }
        self.mark_success(result)
        return result

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the product content has enough depth and has accompanying sales copy."""
        if not isinstance(result, dict) or "body" not in result:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Failed to generate product content.",
                reason="Invalid output structure.",
            )

        body = result.get("body", "")
        sales_copy = result.get("sales_page_copy", "")

        if len(body) < 1500:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback=f"Product content is too short ({len(body)} chars). Expand with more details.",
                reason="Product body too short.",
            )

        if len(sales_copy) < 300:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Sales page copy is too brief. Expand features and benefits.",
                reason="Sales copy insufficient.",
            )

        return Verification(
            is_complete=True,
            score=95.0,
            feedback=f"Product '{result.get('name')}' created successfully. Price: ${result.get('price')}. Content size: {len(body)} chars. Sales copy size: {len(sales_copy)} chars.",
        )

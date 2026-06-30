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
        """Read the niche, product type, and topic from context (no Notion default)."""
        self.mark_running()
        niche = ""
        product_type = "guide"
        topic = ""
        research = ""

        for entry in reversed(context.entries):
            content = entry["content"]
            if "RESEARCH BRIEF" in content and not research:
                research = content.split("RESEARCH BRIEF", 1)[1].lstrip(" :\n")
                continue
            for line in content.split("\n"):
                low = line.lower().strip()
                if low.startswith("niche:"):
                    niche = line.split(":", 1)[1].strip() or niche
                elif low.startswith("product_type:"):
                    product_type = line.split(":", 1)[1].strip() or product_type
                elif low.startswith("topic:"):
                    topic = line.split(":", 1)[1].strip() or topic

        if not niche:
            niche = "AI Tools & Workflows"

        return {
            "timestamp": time.time(),
            "niche": niche,
            "product_type": product_type,
            "topic": topic,
            "research": research,
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Outline the digital product and structure the chapters or segments (Outline step)."""
        niche = state.get("niche", "AI Tools & Workflows")
        product_type = state.get("product_type", "guide")
        topic = state.get("topic", "")
        research = state.get("research", "")
        focus = topic or goal
        research_block = (
            f"Base the product on this RESEARCH BRIEF (use its facts/tools/examples):\n"
            f"{research[:6000]}\n\n" if research else ""
        )

        prompt = (
            f"Design a digital product in the niche '{niche}'.\n"
            f"Product Type: '{product_type}'.\n"
            f"Specific topic/angle: '{focus}'.\n\n"
            f"{research_block}"
            f"The product MUST be strictly about '{focus}' within the '{niche}' niche — do not "
            f"introduce unrelated tools or topics. Identify the target audience's pain points, "
            f"list core sections/chapters, and suggest a fair price ($5.00 - $29.00).\n\n"
            f"Output a JSON object containing:\n"
            f"- 'product_name': string (must reflect the topic '{focus}')\n"
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

        research = state.get("research", "")
        research_block = (
            f"RESEARCH (use these concrete facts, tools, and examples):\n{research[:9000]}\n\n"
            if research else ""
        )
        product_prompt = (
            f"Write the COMPLETE, finished content of this digital product so a buyer could "
            f"use it immediately:\n"
            f"Name: {product_name}\n"
            f"Type: {product_type}\n"
            f"Niche: {niche}\n"
            f"Outline:\n{sections_str}\n\n"
            f"{research_block}"
            f"STRICT OUTPUT RULES:\n"
            f"- Output ONLY the finished document as clean, readable Markdown prose.\n"
            f"- Use '#'/'##'/'###' headings, short paragraphs, bullet lists and numbered steps.\n"
            f"- DO NOT output JSON, key/value data, or any ``` code fences around the document.\n"
            f"- No placeholders — write the real, detailed, practical content with concrete examples, "
            f"steps, and tips. Aim for a polished, sellable deliverable."
        )

        # Mixture-of-Agents fusion for the core deliverable (the sellable body).
        product_body = self._strip_code_fence(await self.ask_llm_fused(product_prompt, temperature=0.6))

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

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """Remove a wrapping ``` / ```json code fence if the model added one."""
        t = (text or "").strip()
        if t.startswith("```"):
            first_nl = t.find("\n")
            if first_nl != -1:
                t = t[first_nl + 1:]
            if t.rstrip().endswith("```"):
                t = t.rstrip()[:-3]
        return t.strip()

    @staticmethod
    def _looks_like_json(body: str) -> bool:
        """Heuristic: did the model dump JSON/data instead of writing a document?"""
        s = (body or "").strip()
        if s.startswith("{") or s.startswith("["):
            return True
        if s.startswith("```json"):
            return True
        # JSON-ish: lots of quoted keys, no markdown headings.
        return s.count('":') >= 3 and "#" not in s

    async def verify(self, result: Any, goal: str) -> Verification:
        """Verify the product is a finished Markdown document with sales copy."""
        if not isinstance(result, dict) or "body" not in result:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback="Failed to generate product content.",
                reason="Invalid output structure.",
            )

        body = result.get("body", "")
        sales_copy = result.get("sales_page_copy", "")

        if self._looks_like_json(body) or "#" not in body:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback=(
                    "The product body must be a FINISHED Markdown document with #/## headings and "
                    "readable prose — not JSON, raw data, or a code block. Rewrite it as a real guide."
                ),
                reason="Product body is not Markdown prose.",
            )

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

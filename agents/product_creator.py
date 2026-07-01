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
from core.config import config
from core.loop_engine import ContextWindow, Verification
from core.text_clean import strip_ai_artifacts, EDITORIAL_RULES

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
                "You are a top-tier practitioner and instructional designer writing PREMIUM, production-ready "
                "products that professionals pay for. You write as the primary domain expert — never citing "
                "'sources' or leaving bracket artifacts. You are prescriptive and concrete: real steps, real "
                "code/config, real tools, real trade-offs. You avoid filler, boilerplate, and beginner fluff."
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

    # Product types that warrant a long, multi-chapter ebook.
    LONG_FORM = {"ebook", "guide", "playbook", "master book", "master kit", "handbook", "course", "setup guide"}

    def _is_long_form(self, product_type: str) -> bool:
        pt = (product_type or "").lower()
        return any(t in pt for t in self.LONG_FORM)

    async def reason(self, state: dict, goal: str) -> dict:
        """Outline the product. Long-form types get many chapters for a full ebook."""
        niche = state.get("niche", "AI Tools & Workflows")
        product_type = state.get("product_type", "guide")
        topic = state.get("topic", "")
        research = state.get("research", "")
        focus = topic or goal
        research_block = (
            f"Base the product on this RESEARCH BRIEF (use its facts/tools/examples):\n"
            f"{research[:6000]}\n\n" if research else ""
        )

        long_form = self._is_long_form(product_type)
        n_sections = config.ebook_min_sections if long_form else 6
        size_hint = (
            f"This is a full-length ebook — produce a comprehensive outline of AT LEAST {n_sections} "
            f"substantial chapters (intro, multiple deep-dive chapters, practical/how-to chapters, "
            f"examples/case studies, pitfalls, and a conclusion)."
            if long_form else
            f"Produce a focused outline of about {n_sections} sections."
        )

        prompt = (
            f"Design a digital product in the niche '{niche}'.\n"
            f"Product Type: '{product_type}'.\n"
            f"Specific topic/angle: '{focus}'.\n\n"
            f"{research_block}"
            f"The product MUST be strictly about '{focus}' within the '{niche}' niche — do not "
            f"introduce unrelated tools or topics. {size_hint} Identify audience pain points and "
            f"suggest a fair price (${'15.00 - $39.00' if long_form else '5.00 - $19.00'}).\n\n"
            f"Output a JSON object containing:\n"
            f"- 'product_name': string (must reflect the topic '{focus}')\n"
            f"- 'niche': string\n"
            f"- 'target_price': float\n"
            f"- 'outline': list of {n_sections}+ section dictionaries (each with 'title' and 'objectives')\n"
            f"- 'pain_points_solved': list of strings\n"
        )

        response_json = await self.ask_llm_json(prompt, temperature=0.5, max_tokens=3000)
        return {
            "state": state,
            "outline": response_json,
            "long_form": long_form,
        }

    async def act(self, plan: dict) -> dict:
        """Write the product chapter-by-chapter (for length), then the sales copy."""
        state = plan.get("state", {})
        outline = plan.get("outline", {})
        long_form = plan.get("long_form", False)
        niche = state.get("niche", "General")
        product_type = state.get("product_type", "checklist")
        topic = state.get("topic", "")
        focus = topic or product_type
        product_name = outline.get("product_name", f"Ultimate {niche} Guide")
        price = float(outline.get("target_price", 9.0))
        research = state.get("research", "")
        research_block = (
            f"RESEARCH (use these concrete facts, tools, examples — cite real tools):\n{research[:7000]}\n\n"
            if research else ""
        )

        sections = outline.get("outline", []) or [{"title": product_name, "objectives": focus}]
        target_words = config.ebook_section_words if long_form else max(350, config.ebook_section_words // 2)

        # Generate each chapter in its own call so the book can run to many pages
        # (a single call caps at ~5-6 pages of output).
        parts: list[str] = []
        covered: list[str] = []
        for i, sec in enumerate(sections, 1):
            sec_title = sec.get("title", f"Chapter {i}")
            sec_obj = sec.get("objectives", "")
            sec_prompt = (
                f"You are writing chapter {i} of {len(sections)} of the {product_type} "
                f"'{product_name}' (niche: {niche}; topic: {focus}).\n\n"
                f"CHAPTER: {sec_title}\n"
                f"What this chapter must cover: {sec_obj}\n\n"
                f"{research_block}"
                f"{EDITORIAL_RULES}\n\n"
                f"Already covered in earlier chapters (do NOT repeat): {', '.join(covered) or 'none yet'}.\n\n"
                f"Write ~{target_words} words for THIS chapter only, starting with a '## {sec_title}' heading. "
                f"Do not write a conclusion unless this is the final chapter. Output only the chapter Markdown."
            )
            try:
                sec_text = strip_ai_artifacts(self._strip_code_fence(
                    await self.ask_llm(sec_prompt, temperature=0.6, max_tokens=4096)
                ))
            except Exception as e:
                self.logger.warning("section_generation_failed", chapter=sec_title, error=str(e)[:120])
                continue
            if not sec_text:
                continue
            # Final editorial pass with the premium model (e.g. Nemotron-Ultra-550B).
            sec_text = await self._finalize_chapter(sec_text, sec_title, product_name, product_type)
            if not sec_text.lstrip().startswith("#"):
                sec_text = f"## {sec_title}\n\n{sec_text}"
            parts.append(sec_text)
            covered.append(sec_title)
            self.logger.info("chapter_done", chapter=sec_title, index=i, total=len(sections))

        product_body = "\n\n".join(parts)

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

        word_count = len(product_body.split())
        result = {
            "name": product_name,
            "product_type": product_type,
            "price": price,
            "body": product_body,
            "sales_page_copy": sales_copy,
            "word_count": word_count,
            "long_form": long_form,
            "chapters": len(parts),
        }
        self.logger.info("product_built", name=product_name, words=word_count, chapters=len(parts))
        self.mark_success(result)
        return result

    async def _finalize_chapter(self, chapter_md: str, sec_title: str, product_name: str, product_type: str) -> str:
        """Elite editorial pass — the premium model produces the FINAL chapter draft."""
        provider = config.finalize_provider
        available = provider in {p.name for p in self.router.providers}
        if not config.finalize_enabled or not available:
            return chapter_md
        prompt = (
            f"You are the elite editor finalizing a chapter of the premium {product_type} '{product_name}'. "
            f"Rewrite the chapter below to production quality a professional would happily pay for:\n"
            f"- Remove EVERY AI footprint: bracket citations ([1], [2]) and any phrase referencing 'sources', "
            f"'context', or 'the research'. Speak as the primary expert.\n"
            f"- Deepen it — make each point prescriptive with the exact how and why and trade-offs. Add at "
            f"least one real, correct code block/config or a clean comparison table where it adds value.\n"
            f"- Fix all formatting; keep the '## {sec_title}' heading. No 'Proceed to Chapter' lines.\n"
            f"- Output ONLY the finished chapter Markdown.\n\nCHAPTER:\n{chapter_md}"
        )
        try:
            result = await self.router.generate(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=4096,
                task_type=self.name,
                only_provider=provider,
            )
            self.state.total_tokens_used += result.get("tokens_used", 0)
            finalized = strip_ai_artifacts(self._strip_code_fence(result.get("content") or ""))
            if len(finalized) > 200:
                return finalized
        except Exception as e:
            self.logger.warning("chapter_finalize_failed", chapter=sec_title, provider=provider, error=str(e)[:150])
        return chapter_md

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

        # Long-form ebooks must actually be book-length; short products just substantial.
        min_words = max(1, config.ebook_min_sections * config.ebook_section_words // 2) if result.get("long_form") else 250
        words = result.get("word_count", len(body.split()))
        if words < min_words or len(body) < 1500:
            return Verification(
                is_complete=False,
                should_retry=True,
                feedback=f"Product is too short ({words} words). A full ebook needs more chapters/depth.",
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

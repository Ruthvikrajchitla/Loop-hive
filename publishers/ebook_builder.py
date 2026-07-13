"""
LoopHive — Ebook Builder

Renders a product's Markdown content into a styled, sellable PDF ebook:
a cover page (with a royalty-free Pexels image), clean typography, headings,
tables, and page breaks. Pure-Python (xhtml2pdf) — no system packages needed,
so it runs on Windows and the Oracle VM identically.
"""

from __future__ import annotations

import base64
import io
import os

import httpx
import markdown as md
import structlog

logger = structlog.get_logger(__name__)


async def pexels_cover_data_uri(query: str) -> str | None:
    """Fetch a royalty-free cover image from Pexels and return it as a data URI."""
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key or "your_" in api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": api_key},
                params={"query": query, "per_page": 1, "orientation": "landscape"},
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if not photos:
                return None
            img_url = photos[0]["src"].get("large") or photos[0]["src"].get("medium")
            img_resp = await client.get(img_url)
            img_resp.raise_for_status()
            b64 = base64.b64encode(img_resp.content).decode("ascii")
            return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning("pexels_fetch_failed", query=query[:60], error=str(e)[:150])
        return None


_CSS = """
@page { size: A4; margin: 2.2cm 2cm; @frame footer { -pdf-frame-content: footerContent;
        bottom: 1cm; margin-left: 2cm; margin-right: 2cm; height: 1cm; } }
body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; color: #1a1a2e; line-height: 1.5; }
h1 { font-size: 22pt; color: #4c1d95; margin: 0 0 6pt 0; }
h2 { font-size: 16pt; color: #5b21b6; border-bottom: 1px solid #ddd; padding-bottom: 3pt; margin-top: 18pt; }
h3 { font-size: 13pt; color: #6d28d9; margin-top: 12pt; }
p, li { font-size: 11pt; }
ul, ol { margin-left: 14pt; }
code { font-family: Courier; background: #f3f0fa; font-size: 9.5pt; }
pre { background: #f3f0fa; padding: 8pt; font-family: Courier; font-size: 9pt; }
table { width: 100%; border-collapse: collapse; margin: 8pt 0; }
th, td { border: 1px solid #ccc; padding: 5pt; font-size: 10pt; text-align: left; }
th { background: #ede9fe; }
.cover { text-align: center; }
.cover-img { width: 17cm; height: 9cm; }
.cover-title { font-size: 30pt; color: #4c1d95; margin-top: 28pt; }
.cover-sub { font-size: 13pt; color: #555; margin-top: 10pt; }
.cover-badge { font-size: 12pt; color: #fff; background: #6d28d9; padding: 6pt 14pt; }
.brand { font-size: 10pt; color: #888; margin-top: 40pt; }
"""


def _render_pdf(html: str) -> bytes | None:
    from xhtml2pdf import pisa
    out = io.BytesIO()
    result = pisa.CreatePDF(src=html, dest=out, encoding="utf-8")
    if result.err:
        logger.error("pdf_render_failed", errors=result.err)
        return None
    return out.getvalue()


async def build_ebook_pdf(
    title: str,
    content_md: str,
    subtitle: str = "",
    price: float | None = None,
    cover_query: str | None = None,
) -> bytes | None:
    """Build a styled PDF ebook from Markdown. Returns PDF bytes (or None on failure)."""
    cover_uri = await pexels_cover_data_uri(cover_query or title)
    body_html = md.markdown(content_md or "", extensions=["tables", "fenced_code", "sane_lists"])

    price_badge = f'<div><span class="cover-badge">${price:.2f}</span></div>' if price else ""
    cover_img = f'<img src="{cover_uri}" class="cover-img" />' if cover_uri else ""
    subtitle_html = f'<div class="cover-sub">{subtitle}</div>' if subtitle else ""

    html = f"""<html><head><meta charset="utf-8"><style>{_CSS}</style></head><body>
    <div id="footerContent" style="text-align:center;color:#999;font-size:8pt;">
        {title} &middot; <pdf:pagenumber>
    </div>
    <div class="cover">
        {cover_img}
        <div class="cover-title">{title}</div>
        {subtitle_html}
        {price_badge}
        <div class="brand">Created by {os.getenv("BRAND_NAME", "Otto")}</div>
    </div>
    <pdf:nextpage />
    {body_html}
    </body></html>"""

    return _render_pdf(html)

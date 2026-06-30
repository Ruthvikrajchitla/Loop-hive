"""
LoopHive — Research Tools

Web + academic research sources for the Deep Research Agent.

- Tavily (https://tavily.com): LLM-ready web search that returns clean, extracted
  page content (no fragile scraping). Needs TAVILY_API_KEY.
- arXiv (export.arxiv.org): free academic papers, no key required — great for the
  technical side of the AI niche. Used as a no-key fallback / supplement.

Each source returns a list of {"title", "url", "content", "source"} dicts.
"""

from __future__ import annotations

import os

import httpx
import structlog

logger = structlog.get_logger(__name__)


async def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Web search via Tavily — returns extracted content per result."""
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key or "your_" in api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        results = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("content") or r.get("raw_content") or "")[:4000],
                "source": "web",
            })
        logger.info("tavily_search_done", query=query[:80], results=len(results))
        return results
    except Exception as e:
        logger.warning("tavily_search_failed", query=query[:80], error=str(e)[:150])
        return []


async def arxiv_search(query: str, max_results: int = 3) -> list[dict]:
    """Academic paper search via the free arXiv API (no key)."""
    try:
        import feedparser  # ships with the project deps
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": f"all:{query}",
                    "start": 0,
                    "max_results": max_results,
                    "sortBy": "relevance",
                },
            )
            resp.raise_for_status()
            text = resp.text
        feed = feedparser.parse(text)
        results = []
        for entry in feed.entries[:max_results]:
            results.append({
                "title": entry.get("title", "").replace("\n", " ").strip(),
                "url": entry.get("link", ""),
                "content": entry.get("summary", "").replace("\n", " ").strip()[:3000],
                "source": "arxiv",
            })
        logger.info("arxiv_search_done", query=query[:80], results=len(results))
        return results
    except Exception as e:
        logger.warning("arxiv_search_failed", query=query[:80], error=str(e)[:150])
        return []


async def gather_sources(query: str, max_sources: int = 8, include_arxiv: bool = True) -> list[dict]:
    """Collect sources for a query from all available providers, de-duplicated."""
    sources: list[dict] = []
    sources.extend(await tavily_search(query, max_results=max_sources))
    if include_arxiv:
        sources.extend(await arxiv_search(query, max_results=3))

    # De-dup by URL / title and cap.
    seen: set[str] = set()
    deduped: list[dict] = []
    for s in sources:
        key = (s.get("url") or s.get("title") or "").strip().lower()
        if key and key not in seen and s.get("content"):
            seen.add(key)
            deduped.append(s)
    return deduped[:max_sources]

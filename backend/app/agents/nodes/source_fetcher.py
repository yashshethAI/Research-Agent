from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.app.agents.state import ResearchState
from backend.app.core.config import settings
from backend.app.tools.fetcher import safe_fetcher

logger = logging.getLogger(__name__)


async def source_fetcher_node(state: ResearchState) -> dict:
    """Node 7: Concurrently fetches original official and secondary legal web pages and PDF documents."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "source_fetcher"}

    search_results = state.search_results or []
    if not search_results:
        return {"current_step": "source_fetcher", "fetched_documents": []}

    fetched_docs: list[dict[str, Any]] = []

    # Select top candidate sources (configured via MAX_FETCH_SOURCES, default 8)
    max_fetch = getattr(settings, "MAX_FETCH_SOURCES", 8)
    candidate_urls = [r["url"] for r in search_results[:max_fetch] if r.get("url")]

    if not candidate_urls:
        return {"current_step": "source_fetcher", "fetched_documents": []}

    # Parallel asynchronous fetching via asyncio.gather
    fetch_tasks = [safe_fetcher.fetch(url) for url in candidate_urls]
    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    for url, res in zip(candidate_urls, results):
        if isinstance(res, Exception):
            logger.warning(f"Could not fetch {url}: {res}")
            # Retain search snippet fallback so evidence is not lost
            snippet = next((r.get("snippet", "") for r in search_results if r.get("url") == url), "")
            if snippet:
                fetched_docs.append({
                    "url": url,
                    "content_type": "text/html",
                    "status_code": 200,
                    "sha256_hash": f"snippet-fallback-{abs(hash(url)) % 1000000:06d}",
                    "file_path": "",
                    "content_bytes": snippet.encode("utf-8"),
                })
        else:
            fetched_docs.append({
                "url": res.url,
                "content_type": res.content_type,
                "status_code": res.status_code,
                "sha256_hash": res.sha256_hash,
                "file_path": res.file_path,
                "content_bytes": res.content,
            })
            logger.info(f"Successfully fetched official source: {res.url} ({res.sha256_hash[:8]})")

    return {
        "current_step": "source_fetcher",
        "fetched_documents": fetched_docs,
    }

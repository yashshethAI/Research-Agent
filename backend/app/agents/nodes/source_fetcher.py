from __future__ import annotations

import logging
from typing import Any

from backend.app.agents.state import ResearchState
from backend.app.tools.fetcher import safe_fetcher

logger = logging.getLogger(__name__)


async def source_fetcher_node(state: ResearchState) -> dict:
    """Node 7: Safely fetches original official web pages and PDF documents."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "source_fetcher"}

    search_results = state.search_results or []
    if not search_results:
        return {"current_step": "source_fetcher", "fetched_documents": []}

    fetched_docs: list[dict[str, Any]] = []

    # Limit to top 4 official sources to balance depth and network latency
    candidate_urls = [r["url"] for r in search_results[:4] if r.get("url")]

    for url in candidate_urls:
        try:
            doc = await safe_fetcher.fetch(url)
            fetched_docs.append({
                "url": doc.url,
                "content_type": doc.content_type,
                "status_code": doc.status_code,
                "sha256_hash": doc.sha256_hash,
                "file_path": doc.file_path,
                "content_bytes": doc.content,
            })
            logger.info(f"Successfully fetched official source: {url} ({doc.sha256_hash[:8]})")
        except Exception as e:
            logger.warning(f"Could not fetch {url}: {e}")

    return {
        "current_step": "source_fetcher",
        "fetched_documents": fetched_docs,
    }

from __future__ import annotations

import logging

from backend.app.agents.state import ResearchState
from backend.app.core.config import settings
from backend.app.tools.search.base import SearchNotConfiguredError, SearchResult
from backend.app.tools.search.mock_adapter import MockSearchAdapter
from backend.app.tools.search.tavily_adapter import TavilySearchAdapter
from backend.app.tools.source_validator import source_validator

logger = logging.getLogger(__name__)


async def official_source_search_node(state: ResearchState) -> dict:
    """Node 6: Executes domain-restricted search on official GST portals."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "official_source_search"}

    queries = state.search_queries
    if not queries:
        return {"current_step": "official_source_search", "search_results": []}

    # Instantiate adapter
    if settings.SEARCH_PROVIDER == "mock":
        adapter = MockSearchAdapter()
    else:
        adapter = TavilySearchAdapter()

    # Determine automated recency filter
    q_lower = (state.query or "").lower()
    recency_keywords = ["latest", "recent", "amendment", "amendments", "new", "update", "updates", "current"]
    time_range = "year" if any(w in q_lower for w in recency_keywords) else None

    aggregated_results: list[SearchResult] = []
    seen_urls = set()

    for q in queries:
        try:
            results = await adapter.search(
                query=q,
                domains=settings.allowed_domains,
                max_results=settings.MAX_SEARCH_RESULTS,
                time_range=time_range,
            )
            for r in results:
                # Filter through source validator
                is_valid, _ = source_validator.validate_url(r.url)
                if is_valid and r.url not in seen_urls:
                    seen_urls.add(r.url)
                    aggregated_results.append(r)
        except SearchNotConfiguredError as e:
            logger.warning(f"Search not configured: {e}")
            return {
                "current_step": "official_source_search",
                "error_message": str(e),
                "search_results": [],
            }
        except Exception as e:
            logger.error(f"Error querying search adapter for '{q}': {e}")

    # Convert to serializable dicts
    results_data = [r.model_dump() for r in aggregated_results]

    return {
        "current_step": "official_source_search",
        "search_results": results_data,
    }

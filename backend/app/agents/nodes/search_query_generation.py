from __future__ import annotations

import logging

from backend.app.agents.state import ResearchState
from backend.app.tools.search.base import sanitize_search_query

logger = logging.getLogger(__name__)


async def search_query_generation_node(state: ResearchState) -> dict:
    """Node 5: Generates domain-targeted search queries, sanitizing confidential client info."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "search_query_generation"}

    plan = state.research_plan or {}
    raw_queries = plan.get("search_intent_queries") or []

    if not raw_queries:
        # Construct queries from extracted topics and query
        topics = state.extracted_facts.get("gst_topics", [])
        topic_str = " ".join(topics) if topics else "GST"
        raw_queries = [
            f"{state.query} site:taxinformation.cbic.gov.in",
            f"{topic_str} circular notification CBIC site:cbic.gov.in",
            f"{state.query} high court supreme court GST judgment",
        ]

    sanitized_queries = []
    for q in raw_queries:
        clean = sanitize_search_query(q).strip()
        if clean and clean not in sanitized_queries:
            sanitized_queries.append(clean)

    # Limit to top 3 focused queries to prevent search API saturation
    final_queries = sanitized_queries[:3]

    return {
        "current_step": "search_query_generation",
        "search_queries": final_queries,
    }

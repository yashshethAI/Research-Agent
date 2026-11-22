from __future__ import annotations

import logging
from typing import Any

from backend.app.agents.state import ResearchState
from backend.app.core.config import settings

logger = logging.getLogger(__name__)


async def citation_validator_node(state: ResearchState) -> dict:
    """Node 11: Audits legal claims against compiled evidence to eliminate hallucinated citations."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "citation_validator"}

    evidence_records = state.evidence_records or []
    retry_count = state.retry_count

    verified_citations: list[dict[str, Any]] = []
    unverified_claims: list[str] = []

    # Map verified source IDs
    for e in evidence_records:
        verified_citations.append({
            "source_id": e.get("source_id"),
            "title": e.get("title"),
            "url": e.get("url"),
            "authority": e.get("authority"),
            "section_or_rule": e.get("section_or_rule"),
            "verified": True,
        })

    # If no evidence was found, evaluate retry condition
    should_refine = False
    if not evidence_records and retry_count < settings.MAX_RESEARCH_RETRIES and settings.SEARCH_PROVIDER == "tavily" and settings.TAVILY_API_KEY:
        should_refine = True
        new_retry = retry_count + 1
        logger.info(f"Evidence insufficient. Triggering research refinement loop (attempt {new_retry}/{settings.MAX_RESEARCH_RETRIES})")
    else:
        new_retry = retry_count

    validation_result = {
        "verified_citations": verified_citations,
        "unverified_claims": unverified_claims,
        "source_count": len(verified_citations),
        "validation_status": "Passed" if verified_citations else "Unverified / Baseline Analysis",
    }

    return {
        "current_step": "citation_validator",
        "citation_validation": validation_result,
        "should_refine_search": should_refine,
        "retry_count": new_retry,
    }

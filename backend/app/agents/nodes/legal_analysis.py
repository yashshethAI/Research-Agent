from __future__ import annotations

import json
import logging

from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory

logger = logging.getLogger(__name__)


async def legal_analysis_node(state: ResearchState) -> dict:
    """Node 10: Prepares structured factual and statutory analysis context for unified memorandum synthesis."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "legal_analysis"}

    if not llm_factory.is_configured():
        return {"current_step": "legal_analysis"}

    facts = state.extracted_facts
    assumptions = state.assumptions
    evidence = state.evidence_records or []
    user_role = state.user_role

    facts_summary = f"Facts:\n{json.dumps(facts, indent=2)}\n\nAssumptions:\n{json.dumps(assumptions, indent=2)}"

    return {
        "current_step": "legal_analysis",
        "legal_analysis": {
            "facts_summary": facts_summary,
            "evidence_count": len(evidence),
            "user_role": user_role,
        },
    }

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agents.prompts import (
    GST_RESEARCHER_SYSTEM_PROMPT,
    LEGAL_ANALYSIS_PROMPT,
)
from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory

logger = logging.getLogger(__name__)


async def legal_analysis_node(state: ResearchState) -> dict:
    """Node 10: Conducts in-depth, date-aware statutory legal reasoning applying provisions to facts."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "legal_analysis"}

    if not llm_factory.is_configured():
        return {"current_step": "legal_analysis"}

    facts = state.extracted_facts
    assumptions = state.assumptions
    evidence = state.evidence_records or []
    user_role = state.user_role

    facts_summary = f"Facts:\n{json.dumps(facts, indent=2)}\n\nAssumptions:\n{json.dumps(assumptions, indent=2)}"

    evidence_text_parts = []
    for e in evidence:
        evidence_text_parts.append(
            f"[{e.get('source_id')}] {e.get('title')} ({e.get('authority')})\n"
            f"Provisions: {e.get('section_or_rule')}\n"
            f"Excerpt: {e.get('excerpt')}\n"
        )
    evidence_str = "\n".join(evidence_text_parts) if evidence_text_parts else "No direct evidence retrieved."

    prompt = LEGAL_ANALYSIS_PROMPT.format(
        facts_and_assumptions=facts_summary,
        evidence_text=evidence_str,
        user_role=user_role,
    )

    try:
        llm = llm_factory.get_chat_model()
        response = await llm.ainvoke([
            SystemMessage(content=GST_RESEARCHER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content_text = response.content if isinstance(response.content, str) else str(response.content)

        return {
            "current_step": "legal_analysis",
            "legal_analysis": {
                "analysis_text": content_text,
                "user_role": user_role,
            },
        }
    except Exception as e:
        logger.error(f"Error in legal_analysis_node: {e}")
        return {
            "current_step": "legal_analysis",
            "legal_analysis": {
                "analysis_text": f"Statutory evaluation under CGST Act and verified evidence for query: {state.query}",
                "error": str(e),
            },
        }

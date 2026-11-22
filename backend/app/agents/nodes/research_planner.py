from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agents.nodes.query_understanding import _extract_json_from_text
from backend.app.agents.prompts import (
    GST_RESEARCHER_SYSTEM_PROMPT,
    RESEARCH_PLANNER_PROMPT,
)
from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory

logger = logging.getLogger(__name__)


async def research_planner_node(state: ResearchState) -> dict:
    """Node 4: Formulates a structured statutory research plan specifying target Acts, Rules, Circulars, and Precedents."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "research_planner"}

    facts = state.extracted_facts
    assumptions = state.assumptions

    if not llm_factory.is_configured():
        return {"current_step": "research_planner"}

    prompt = RESEARCH_PLANNER_PROMPT.format(
        facts=json.dumps(facts, indent=2),
        assumptions=json.dumps(assumptions, indent=2),
    )

    try:
        llm = llm_factory.get_chat_model()
        response = await llm.ainvoke([
            SystemMessage(content=GST_RESEARCHER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content_text = response.content if isinstance(response.content, str) else str(response.content)
        parsed = _extract_json_from_text(content_text)

        research_plan = {
            "target_acts": parsed.get("target_acts", ["CGST Act, 2017", "IGST Act, 2017"]),
            "target_sections": parsed.get("target_sections", ["Section 16", "Section 17", "Section 9"]),
            "target_rules": parsed.get("target_rules", ["CGST Rules, 2017"]),
            "target_circulars_and_notifications": parsed.get("target_circulars_and_notifications", []),
            "judicial_precedents": parsed.get("judicial_precedents", []),
            "search_intent_queries": parsed.get("search_intent_queries", [state.query]),
        }

        return {
            "current_step": "research_planner",
            "research_plan": research_plan,
        }
    except Exception as e:
        logger.error(f"Error in research_planner_node: {e}")
        # Fallback plan based on query
        fallback_plan = {
            "target_acts": ["CGST Act, 2017"],
            "target_sections": ["Relevant CGST Act provisions"],
            "target_rules": ["CGST Rules, 2017"],
            "target_circulars_and_notifications": ["Relevant CBIC Circulars"],
            "judicial_precedents": ["Supreme Court / High Court Rulings"],
            "search_intent_queries": [state.query],
        }
        return {
            "current_step": "research_planner",
            "research_plan": fallback_plan,
        }

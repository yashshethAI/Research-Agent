from __future__ import annotations

import logging
import re
from typing import Any

from backend.app.agents.state import ResearchState

logger = logging.getLogger(__name__)


def _build_deterministic_research_plan(query: str, facts: dict[str, Any]) -> dict[str, Any]:
    """Formulates a fast, deterministic statutory research plan from extracted facts and query."""
    topics = facts.get("gst_topics", [])
    combined_text = f"{query} {' '.join(topics)}"

    # Detect sections (e.g. Section 16, Sec 16(4))
    section_matches = re.findall(
        r"(?:Section|Sec\.?)\s*(\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))*)",
        combined_text,
        re.IGNORECASE,
    )
    sections = [f"Section {s}" for s in dict.fromkeys(section_matches)]
    if not sections:
        sections = ["Relevant CGST Act provisions"]

    # Detect rules (e.g. Rule 36, Rule 37A)
    rule_matches = re.findall(
        r"(?:Rule|R\.)\s*(\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))*)",
        combined_text,
        re.IGNORECASE,
    )
    rules = [f"Rule {r}" for r in dict.fromkeys(rule_matches)]
    if not rules:
        rules = ["CGST Rules, 2017"]

    # Detect acts
    acts = ["CGST Act, 2017"]
    if re.search(r"\bIGST\b|cross[- ]border|inter[- ]state|import|export|place of supply", combined_text, re.IGNORECASE):
        acts.append("IGST Act, 2017")

    # Formulate high-relevance search intent queries
    primary_topic = topics[0] if topics else (sections[0] if sections else "GST")
    intent_queries = [
        f"{query} site:taxinformation.cbic.gov.in",
        f"{primary_topic} circular notification CBIC site:cbic.gov.in",
        f"{primary_topic} Supreme Court High Court GST judgment",
    ]

    return {
        "target_acts": acts,
        "target_sections": sections,
        "target_rules": rules,
        "target_circulars_and_notifications": ["Relevant CBIC Circulars & Instructions"],
        "judicial_precedents": ["Supreme Court of India / High Court Decisions"],
        "search_intent_queries": intent_queries,
    }


async def research_planner_node(state: ResearchState) -> dict:
    """Node 4: Formulates a structured statutory research plan specifying target Acts, Rules, Circulars, and Precedents."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "research_planner"}

    facts = state.extracted_facts
    plan = _build_deterministic_research_plan(state.query, facts)

    return {
        "current_step": "research_planner",
        "research_plan": plan,
    }

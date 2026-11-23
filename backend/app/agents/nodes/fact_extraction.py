from __future__ import annotations

import logging

from backend.app.agents.state import ResearchState

logger = logging.getLogger(__name__)


async def fact_extraction_node(state: ResearchState) -> dict:
    """Node 3: Consolidates material facts, evaluates attachments, and finalizes assumptions."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "fact_extraction"}

    facts = dict(state.extracted_facts)
    assumptions = list(state.assumptions)
    missing_facts = list(state.missing_facts)

    # If financial year is unspecified, adopt standard assumption
    if not facts.get("financial_year") or facts.get("financial_year") == "Not Specified":
        assumptions.append("Transaction assumed to pertain to the current Financial Year under active GST law.")

    if not facts.get("taxpayer_type") or facts.get("taxpayer_type") == "Not Specified":
        assumptions.append("Taxpayer assumed to be a regular registered taxable person under Section 22/24 of the CGST Act, 2017.")

    # Deduplicate assumptions
    cleaned_assumptions = list(dict.fromkeys(assumptions))

    return {
        "current_step": "fact_extraction",
        "extracted_facts": facts,
        "assumptions": cleaned_assumptions,
        "missing_facts": missing_facts,
    }

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agents.prompts import (
    GST_RESEARCHER_SYSTEM_PROMPT,
    UNIFIED_GST_LEGAL_REASONING_PROMPT,
)
from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory

logger = logging.getLogger(__name__)


async def answer_generator_node(state: ResearchState) -> dict:
    """Node 12: Executes unified legal reasoning, synthesizes a comprehensive GST legal explanation with inline clickable source links."""
    # 1. If LLM endpoint is unconfigured, return setup instructions
    if state.llm_unconfigured_guidance:
        return {
            "current_step": "answer_generator",
            "final_report": state.llm_unconfigured_guidance,
        }

    # 2. If missing facts require clarification
    if state.needs_clarification and state.clarification_prompt:
        clarification_response = (
            "### ⚖️ GST PRACTICE COPILOT — FACTUAL CLARIFICATION REQUIRED\n\n"
            "To provide a definite, legally binding research memorandum on your GST query, "
            "additional material facts are required:\n\n"
            f"> **Required Clarification:**\n> {state.clarification_prompt}\n\n"
            "#### Missing Material Facts Identified:\n"
            + "\n".join(f"- {f}" for f in state.missing_facts)
            + "\n\n"
            "Please provide these details so we can verify the applicable tax period, notification status, and jurisdictional provisions."
        )
        return {
            "current_step": "answer_generator",
            "final_report": clarification_response,
        }

    # 3. If LLM is not configured
    if not llm_factory.is_configured():
        return {
            "current_step": "answer_generator",
            "final_report": "Error: LLM endpoint is not configured. Please check your `.env` configuration.",
        }

    # 4. Generate unified legal explanation with integrated inline clickable citations
    facts = state.extracted_facts
    evidence = state.evidence_records or []
    user_role = state.user_role

    evidence_summary_list = []
    for e in evidence:
        evidence_summary_list.append(
            f"- Source ID: [{e.get('source_id')}]\n"
            f"  Title: {e.get('title')}\n"
            f"  Authority: {e.get('authority')}\n"
            f"  Provisions: {e.get('section_or_rule')}\n"
            f"  Official Source Link: {e.get('url')}\n"
            f"  Statutory Excerpt:\n  \"\"\"{e.get('excerpt')}\"\"\"\n"
        )
    evidence_str = "\n".join(evidence_summary_list) if evidence_summary_list else "General GST Statutory Framework under CGST Act, 2017."

    facts_summary = (
        f"Supplied Facts:\n{json.dumps(facts, indent=2)}\n\n"
        f"Adopted Assumptions:\n{json.dumps(state.assumptions, indent=2)}"
    )

    # Compute live Indian tax calendar context
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_tz)
    current_date_str = now.strftime("%d %B %Y")
    current_year = now.year
    current_fy = f"FY {current_year}-{str(current_year + 1)[-2:]}" if now.month >= 4 else f"FY {current_year - 1}-{str(current_year)[-2:]}"
    preceding_fy = f"FY {current_year - 1}-{str(current_year)[-2:]}" if now.month >= 4 else f"FY {current_year - 2}-{str(current_year - 1)[-2:]}"

    prompt = UNIFIED_GST_LEGAL_REASONING_PROMPT.format(
        current_date=current_date_str,
        current_fy=current_fy,
        preceding_fy=preceding_fy,
        query=state.query,
        facts=facts_summary,
        evidence=evidence_str,
        user_role=user_role,
    )

    try:
        llm = llm_factory.get_chat_model()
        response = await llm.ainvoke([
            SystemMessage(content=GST_RESEARCHER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content_text = response.content if isinstance(response.content, str) else str(response.content)

        # Post-generation guard: Intercept any prompt-leak of Circular 183 if ungrounded in evidence
        if "183/15/2022" in content_text and "183/15/2022" not in evidence_str:
            logger.warning("Intercepted prompt-leak of Circular 183/15/2022-GST not present in retrieved evidence.")
            content_text = re.sub(
                r"\[Circular\s+No\.?\s*183/15/2022-GST\]\([^)]+\)",
                "applicable CBIC rate notification",
                content_text,
                flags=re.IGNORECASE,
            )
            content_text = re.sub(
                r"Circular\s+No\.?\s*183/15/2022-GST",
                "applicable CBIC rate notification",
                content_text,
                flags=re.IGNORECASE,
            )

        return {
            "current_step": "answer_generator",
            "final_report": content_text,
        }
    except Exception as e:
        logger.error(f"Error in answer_generator_node: {e}")
        error_report = (
            f"### Error Generating GST Memorandum\n\n"
            f"An error occurred while contacting the LLM inference server:\n`{e!s}`\n\n"
            f"Please verify your model server is active and accessible."
        )
        return {
            "current_step": "answer_generator",
            "final_report": error_report,
            "error_message": str(e),
        }

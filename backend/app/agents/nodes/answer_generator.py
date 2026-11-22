from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agents.prompts import (
    GST_RESEARCHER_SYSTEM_PROMPT,
    UNIFIED_GST_LEGAL_REASONING_PROMPT,
)
from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory

logger = logging.getLogger(__name__)


async def answer_generator_node(state: ResearchState) -> dict:
    """Node 12: Executes unified legal reasoning, synthesizes the 12-section GST memorandum with clickable source links."""
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

    # 4. Generate unified 12-section memorandum with integrated clickable citations
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

    prompt = UNIFIED_GST_LEGAL_REASONING_PROMPT.format(
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

        # Ensure Section L Sources Table is present with verified official clickable links
        if evidence and "AUTHORITATIVE SOURCES" not in content_text.upper() and "LEGAL REFERENCES" not in content_text.upper():
            table_lines = [
                "\n\n---\n\n## L. AUTHORITATIVE SOURCES & REFERENCES REFERRED\n",
                "| Source ID | Authority | Legal Reference / Topic | Official Verified Link |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for e in evidence:
                sid = e.get("source_id", "SRC")
                auth = e.get("authority", "Official Authority")
                ref = e.get("section_or_rule", e.get("title", "Statutory Provision"))
                url = e.get("url", "")
                link_md = f"[{e.get('title', 'View Official Document')}]({url})" if url else "Official CBIC Record"
                table_lines.append(f"| [{sid}] | {auth} | {ref} | {link_md} |")
            content_text += "\n" + "\n".join(table_lines) + "\n"

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

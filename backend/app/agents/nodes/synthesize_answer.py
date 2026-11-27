from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agents.prompts import GST_RESEARCHER_SYSTEM_PROMPT, UNIFIED_GST_LEGAL_REASONING_PROMPT
from backend.app.agents.state import ResearchState
from backend.app.core.config import settings
from backend.app.core.logging_utils import (
    make_node_error,
    make_trace_entry,
    reset_log_context,
    set_log_context,
    strip_thinking_tags,
)
from backend.app.llm.factory import llm_factory

logger = logging.getLogger(__name__)


def _prioritize_evidence_for_llm(evidence: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    tier_rank = {"official": 0, "verified_secondary": 1, "unverified_fallback": 2}
    fetch_rank = {"fetched": 0, "spa_shell": 1, "snippet_only": 2}
    ordered = sorted(
        evidence,
        key=lambda e: (
            fetch_rank.get(e.get("fetch_status", "snippet_only"), 3),
            tier_rank.get(e.get("source_tier", "unverified_fallback"), 3),
        ),
    )
    return ordered[:limit]


async def synthesize_answer_node(state: ResearchState) -> dict[str, Any]:
    """Node 3: Formats setup/clarification responses or synthesizes plain-English bulleted advisory (LLM Call #2)."""
    t0 = time.perf_counter()
    tokens = set_log_context(
        conversation_id=state.conversation_id,
        research_id=state.research_id,
        node="synthesize_answer",
        tier=state.search_tier,
    )
    errors = list(state.node_errors)
    trace = list(state.execution_trace)

    try:
        if state.llm_unconfigured_guidance:
            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry("synthesize_answer", state.search_tier, "unconfigured", dur))
            return {
                "current_step": "synthesize_answer",
                "final_report": state.llm_unconfigured_guidance,
                "execution_trace": trace,
            }

        if state.needs_clarification and state.clarification_prompt:
            missing_block = "\n".join(f"- {m}" for m in state.missing_facts) if state.missing_facts else ""
            clarification_response = (
                "### Clarification Needed Before Final GST Advisory\n\n"
                "To give you an accurate answer under the right statutory provision, please confirm:\n\n"
                f"{state.clarification_prompt}\n"
                + (f"\n**Missing details identified:**\n{missing_block}\n" if missing_block else "")
            ).strip()
            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry("synthesize_answer", state.search_tier, "clarification", dur))
            return {
                "current_step": "synthesize_answer",
                "final_report": clarification_response,
                "execution_trace": trace,
            }

        if not llm_factory.is_configured():
            msg = "Error: LLM endpoint is not configured. Please check your `.env` configuration."
            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry("synthesize_answer", state.search_tier, "error", dur, error=msg))
            return {
                "current_step": "synthesize_answer",
                "final_report": msg,
                "execution_trace": trace,
            }

        # Cap evidence to protect <26B model attention window
        selected_evidence = _prioritize_evidence_for_llm(
            state.evidence_records or [],
            limit=settings.MAX_EVIDENCE_SOURCES_FOR_LLM,
        )

        evidence_blocks: list[str] = []
        for e in selected_evidence:
            evidence_blocks.append(
                f"- Source ID: {e.get('source_id')}\n"
                f"  Tier: {e.get('source_tier')} | Fetch Status: {e.get('fetch_status')} | Verified: {e.get('verified')}\n"
                f"  Title: {e.get('title')}\n"
                f"  Authority: {e.get('authority')}\n"
                f"  Provisions: {e.get('section_or_rule')}\n"
                f"  URL: {e.get('url')}\n"
                f"  Excerpt:\n  \"\"\"{e.get('excerpt')}\"\"\"\n"
            )

        evidence_str = (
            "\n".join(evidence_blocks)
            if evidence_blocks
            else "No external sources could be retrieved. State clearly what statutory provisions require verification."
        )

        facts_summary = (
            f"Facts:\n{json.dumps(state.extracted_facts, indent=2)}\n\n"
            f"Assumptions:\n{json.dumps(state.assumptions, indent=2)}"
        )

        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(ist_tz)
        current_date_str = now.strftime("%d %B %Y")
        current_year = now.year
        current_fy = f"FY {current_year}-{str(current_year + 1)[-2:]}" if now.month >= 4 else f"FY {current_year - 1}-{str(current_year)[-2:]}"
        preceding_fy = f"FY {current_year - 1}-{str(current_year)[-2:]}" if now.month >= 4 else f"FY {current_year - 2}-{str(current_year - 1)[-2:]}"

        effective_query = (state.extracted_facts or {}).get("effective_query") or state.query
        prompt = UNIFIED_GST_LEGAL_REASONING_PROMPT.format(
            current_date=current_date_str,
            current_fy=current_fy,
            preceding_fy=preceding_fy,
            query=effective_query,
            facts=facts_summary,
            evidence=evidence_str,
            user_role=state.user_role,
        )

        try:
            llm = llm_factory.get_chat_model(max_tokens=2000)
            response = await llm.ainvoke([
                SystemMessage(content=GST_RESEARCHER_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            raw_content = response.content if isinstance(response.content, str) else str(response.content)
            content_text, think_chars = strip_thinking_tags(raw_content)
            if think_chars:
                logger.info(f"Stripped {think_chars} chars of <think> tags from Call #2 response")

            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry(
                "synthesize_answer",
                state.search_tier,
                "ok",
                dur,
                {"llm_sources": len(selected_evidence), "output_chars": len(content_text)},
            ))
            return {
                "current_step": "synthesize_answer",
                "final_report": content_text,
                "execution_trace": trace,
                "node_errors": errors,
            }
        except Exception as e:
            logger.error(f"LLM Call #2 inference failed: {e}", exc_info=True)
            errors.append(make_node_error("synthesize_answer", "llm_call", e, llm_factory.base_url or ""))
            error_report = (
                "### Error Generating GST Advisory\n\n"
                f"Failed contacting LLM endpoint (`{llm_factory.model_name}` at `{llm_factory.base_url}`):\n"
                f"- `{type(e).__name__}: {e!s}`\n\n"
                "Check backend logs or `research_sessions/{id}/metadata.json` for exact details."
            )
            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry("synthesize_answer", state.search_tier, "error", dur, error=str(e)))
            return {
                "current_step": "synthesize_answer",
                "final_report": error_report,
                "error_message": str(e),
                "execution_trace": trace,
                "node_errors": errors,
            }
    finally:
        reset_log_context(tokens)

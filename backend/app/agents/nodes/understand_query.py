from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.app.agents.prompts import QUERY_UNDERSTANDING_PROMPT
from backend.app.agents.state import ResearchState
from backend.app.core.logging_utils import (
    make_node_error,
    make_trace_entry,
    reset_log_context,
    set_log_context,
    strip_thinking_tags,
)
from backend.app.llm.factory import llm_factory
from backend.app.storage.conversations import conversation_storage
from backend.app.tools.evidence_extractor import normalize_llm_search_queries

logger = logging.getLogger(__name__)


class _QueryPlanSchema(BaseModel):
    gst_topics: list[str] = Field(default_factory=list)
    financial_year: str = ""
    taxpayer_type: str = "Regular Registered Taxable Person"
    target_sections: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str = ""
    missing_facts: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    time_range: str | None = None


def _current_ist_calendar() -> tuple[str, str]:
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_tz)
    date_str = now.strftime("%d %B %Y")
    fy = f"FY {now.year}-{str(now.year + 1)[-2:]}" if now.month >= 4 else f"FY {now.year - 1}-{str(now.year)[-2:]}"
    return date_str, fy


def _extract_json_from_text(text: str) -> dict[str, Any]:
    cleaned, _ = strip_thinking_tags(text)
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError("No JSON object found in LLM response")


def _heuristic_fallback(query: str, current_fy: str) -> _QueryPlanSchema:
    """Fallback extraction when LLM JSON fails or transport errors occur."""
    sections = re.findall(r"(?:Section|Sec\.?)\s*(\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))*)", query, re.IGNORECASE)
    rules = re.findall(r"(?:Rule|R\.)\s*(\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))*)", query, re.IGNORECASE)
    targets = [f"Section {s}" for s in dict.fromkeys(sections)] + [f"Rule {r}" for r in dict.fromkeys(rules)]

    fy_match = re.search(r"\b(?:FY\s*)?20\d{2}[-–/]\d{2,4}\b", query, re.IGNORECASE)
    fy = fy_match.group(0) if fy_match else current_fy

    q_clean = re.sub(r"[^\w\s()\-/]", " ", query).strip()
    keywords = " ".join(q_clean.split()[:8])
    queries = [
        f"{keywords} CGST IGST statutory provision",
        f"{' '.join(targets[:2]) or keywords} CBIC circular notification",
        f"{' '.join(targets[:2]) or keywords} High Court Supreme Court GSTAT GST",
    ]

    return _QueryPlanSchema(
        gst_topics=targets[:3] or ["GST Statutory Provision"],
        financial_year=fy,
        target_sections=targets,
        search_queries=normalize_llm_search_queries(queries, max_queries=4),
    )


def _format_history_context(messages: list[dict[str, Any]], max_turns: int = 6) -> str:
    if not messages:
        return "None (New conversation)"
    lines: list[str] = []
    for msg in messages[-max_turns:]:
        role = (msg.get("role") or "user").upper()
        content = (msg.get("content") or "").strip().replace("\n", " ")
        if content:
            lines.append(f"{role}: {content[:400]}")
    return "\n".join(lines) if lines else "None"


async def understand_query_node(state: ResearchState) -> dict[str, Any]:
    """Node 1: Loads conversation history and executes dynamic LLM query understanding + planning."""
    t0 = time.perf_counter()
    tokens = set_log_context(
        conversation_id=state.conversation_id,
        research_id=state.research_id,
        node="understand_query",
        tier=state.search_tier,
    )
    errors = list(state.node_errors)
    trace = list(state.execution_trace)

    try:
        # 1. Load persisted conversation history
        messages = list(state.messages)
        if state.conversation_id and not messages:
            try:
                messages = conversation_storage.get_conversation(state.conversation_id)
            except Exception as e:
                logger.warning(f"Failed loading conversation history: {e}")
                errors.append(make_node_error("understand_query", "load_history", e, state.conversation_id))

        # 2. Short-circuit cleanly if LLM is unconfigured
        if not llm_factory.is_configured():
            guidance = (
                "### ⚖️ GST PRACTICE COPILOT — INFERENCE SETUP REQUIRED\n\n"
                "The legal research agent is running, but no active OpenAI-compatible LLM endpoint is configured.\n\n"
                "1. Open `.env` in the project root and set `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` (or Basic Auth if needed).\n"
                "2. Restart the backend or resend your query once your model server is running."
            )
            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry("understand_query", state.search_tier, "unconfigured", dur, {"history_len": len(messages)}))
            return {
                "current_step": "understand_query",
                "messages": messages,
                "llm_unconfigured_guidance": guidance,
                "final_report": guidance,
                "execution_trace": trace,
                "node_errors": errors,
            }

        date_str, current_fy = _current_ist_calendar()
        history_ctx = _format_history_context(messages)
        logger.info(f"Entering understand_query (query_len={len(state.query)}, history_msgs={len(messages)})")

        # 3. Call LLM #1 with compact JSON prompt and bounded max_tokens
        parsed_plan: _QueryPlanSchema | None = None
        prompt = QUERY_UNDERSTANDING_PROMPT.format(
            current_date=date_str,
            current_fy=current_fy,
            context=history_ctx,
            query=state.query,
        )

        try:
            llm = llm_factory.get_chat_model(max_tokens=700)
            resp = await llm.ainvoke([
                SystemMessage(content="Return valid JSON only. No explanations outside JSON."),
                HumanMessage(content=prompt),
            ])
            raw_text = resp.content if isinstance(resp.content, str) else str(resp.content)
            cleaned_text, think_chars = strip_thinking_tags(raw_text)
            if think_chars:
                logger.info(f"Stripped {think_chars} chars of <think> tags from Call #1 response")

            try:
                raw_json = _extract_json_from_text(cleaned_text)
                parsed_plan = _QueryPlanSchema.model_validate(raw_json)
            except Exception as parse_err:
                logger.warning(f"LLM Call #1 JSON parse failed; falling back to heuristics: {parse_err}")
                errors.append(make_node_error("understand_query", "json_parse", parse_err))
        except Exception as llm_err:
            logger.error(f"LLM Call #1 transport/inference error: {llm_err}", exc_info=True)
            errors.append(make_node_error("understand_query", "llm_call", llm_err, llm_factory.base_url or ""))

        if parsed_plan is None:
            parsed_plan = _heuristic_fallback(state.query, current_fy)

        # Normalize queries deterministically (strip site: tokens, PII, filler words)
        clean_queries = normalize_llm_search_queries(parsed_plan.search_queries, max_queries=4)
        if not clean_queries:
            clean_queries = _heuristic_fallback(state.query, current_fy).search_queries

        time_range = parsed_plan.time_range if parsed_plan.time_range in ("day", "week", "month", "year") else None

        # Combine prior user query if this turn answered a clarification follow-up
        effective_query = state.query
        if messages and len(messages) >= 2 and messages[-1].get("metadata", {}).get("needs_clarification"):
            prev_user = next((m.get("content", "") for m in reversed(messages[:-1]) if m.get("role") == "user"), "")
            if prev_user:
                effective_query = f"{prev_user} | Follow-up details: {state.query}"

        extracted_facts = {
            "gst_topics": parsed_plan.gst_topics or ["General GST Law"],
            "financial_year": parsed_plan.financial_year or current_fy,
            "taxpayer_type": parsed_plan.taxpayer_type or "Regular Registered Taxable Person",
            "effective_query": effective_query,
        }
        assumptions = [
            f"Evaluated for {extracted_facts['financial_year']} under active Indian GST law.",
            f"Assumed taxpayer status: {extracted_facts['taxpayer_type']}.",
        ]
        research_plan = {
            "target_acts": ["CGST Act, 2017", "IGST Act, 2017"],
            "target_sections": parsed_plan.target_sections,
            "target_rules": [s for s in parsed_plan.target_sections if "rule" in s.lower()],
            "search_intent_queries": clean_queries,
        }

        dur = int((time.perf_counter() - t0) * 1000)
        summary = {
            "topics": extracted_facts["gst_topics"],
            "needs_clarification": parsed_plan.needs_clarification,
            "queries_count": len(clean_queries),
            "time_range": time_range,
        }
        trace.append(make_trace_entry("understand_query", state.search_tier, "ok", dur, summary))
        logger.info(f"Completed understand_query in {dur}ms: {summary}")

        return {
            "current_step": "understand_query",
            "messages": messages,
            "extracted_facts": extracted_facts,
            "assumptions": assumptions,
            "missing_facts": parsed_plan.missing_facts,
            "needs_clarification": parsed_plan.needs_clarification,
            "clarification_prompt": parsed_plan.clarification_question or None,
            "research_plan": research_plan,
            "search_queries": clean_queries,
            "search_time_range": time_range,
            "execution_trace": trace,
            "node_errors": errors,
        }
    finally:
        reset_log_context(tokens)

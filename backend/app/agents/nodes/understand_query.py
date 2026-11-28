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
from backend.app.llm.factory import invoke_llm_with_streaming, llm_factory, research_llm_factory
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
    time_range = "year" if re.search(r"\b(?:latest|recent|this\s+year|2026)\b", query, re.IGNORECASE) else None

    return _QueryPlanSchema(
        gst_topics=targets[:3] or ["GST Statutory Provision"],
        financial_year=fy,
        target_sections=targets,
        search_queries=normalize_llm_search_queries(queries, max_queries=3),
        time_range=time_range,
    )


def _extract_active_exchange(messages: list[dict[str, Any]], current_query: str) -> tuple[str, str, bool]:
    """Isolates only the active clarification chain (preventing prior unrelated topics from bleeding in).

    Returns (context_text, effective_query, already_clarified).
    """
    if not messages:
        return "None (New conversation)", current_query, False

    last_msg = messages[-1]
    if last_msg.get("role") == "assistant" and last_msg.get("metadata", {}).get("needs_clarification"):
        # Walk backwards across the contiguous clarification chain until we hit a non-clarification assistant answer
        chain: list[dict[str, Any]] = []
        for msg in reversed(messages):
            role = msg.get("role")
            is_clar = bool(msg.get("metadata", {}).get("needs_clarification"))
            if role == "assistant" and not is_clar:
                break
            chain.append(msg)
        chain.reverse()

        user_parts = [m.get("content", "").strip() for m in chain if m.get("role") == "user" and m.get("content")]
        root_query = user_parts[0] if user_parts else ""
        followups = [*user_parts[1:], current_query.strip()]
        effective_query = (
            f"{root_query} (Clarification details: {'; '.join(p for p in followups if p)})"
            if root_query
            else current_query
        )

        lines = [
            f"{(m.get('role') or 'user').upper()}: {(m.get('content') or '').strip().replace(chr(10), ' ')[:400]}"
            for m in chain[-6:]
        ]
        return "\n".join(lines), effective_query, True

    # New independent question: pass only minimal context if the query looks like a short follow-up
    if len(current_query.split()) <= 7 and len(messages) >= 2:
        recent = messages[-2:]
        lines = [
            f"{(m.get('role') or 'user').upper()}: {(m.get('content') or '').strip().replace(chr(10), ' ')[:250]}"
            for m in recent
        ]
        return "\n".join(lines), current_query, False

    return "None (Treat as independent new GST query)", current_query, False


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
        if not llm_factory.is_configured() or not research_llm_factory.is_configured():
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
        history_ctx, effective_query, already_clarified = _extract_active_exchange(messages, state.query)
        logger.info(
            f"Entering understand_query (query_len={len(state.query)}, history_msgs={len(messages)}, already_clarified={already_clarified})"
        )

        # 3. Call LLM #1 via research_llm_factory (disabling heavy <think> overhead on qwen3 planners)
        parsed_plan: _QueryPlanSchema | None = None
        prompt = QUERY_UNDERSTANDING_PROMPT.format(
            current_date=date_str,
            current_fy=current_fy,
            context=history_ctx,
            query=effective_query,
        )
        if "qwen3" in (research_llm_factory.model_name or "").lower():
            prompt = f"/no_think\n{prompt}"

        try:
            llm = research_llm_factory.get_chat_model()
            raw_text = await invoke_llm_with_streaming(
                llm,
                [
                    SystemMessage(content="Return valid JSON only. No explanations outside JSON."),
                    HumanMessage(content=prompt),
                ],
            )
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
            errors.append(make_node_error("understand_query", "llm_call", llm_err, research_llm_factory.base_url or ""))

        if parsed_plan is None:
            parsed_plan = _heuristic_fallback(effective_query, current_fy)

        # Enforce one-shot clarification guard: never trap the user in repeated clarification loops
        needs_clarification = bool(parsed_plan.needs_clarification) and not already_clarified
        clarification_prompt = parsed_plan.clarification_question if needs_clarification else ""
        missing_facts = parsed_plan.missing_facts if needs_clarification else []

        # Strip hallucinated Notification/Circular numbers from target_sections if absent from query
        query_lower = effective_query.lower()
        filtered_targets: list[str] = []
        for t in parsed_plan.target_sections:
            t_clean = t.strip()
            if not t_clean:
                continue
            if ("notification" in t_clean.lower() or "circular" in t_clean.lower()) and not any(
                num in query_lower for num in re.findall(r"\d+/\d{4}", t_clean)
            ):
                continue
            filtered_targets.append(t_clean)

        # Normalize queries deterministically (cap at 3 to prevent SearXNG upstream bursts)
        clean_queries = normalize_llm_search_queries(parsed_plan.search_queries, max_queries=3)
        if not clean_queries:
            clean_queries = _heuristic_fallback(effective_query, current_fy).search_queries[:3]

        time_range = parsed_plan.time_range if parsed_plan.time_range in ("day", "week", "month", "year") else None

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
            "target_sections": filtered_targets,
            "target_rules": [s for s in filtered_targets if "rule" in s.lower()],
            "search_intent_queries": clean_queries,
        }

        dur = int((time.perf_counter() - t0) * 1000)
        summary = {
            "topics": extracted_facts["gst_topics"],
            "needs_clarification": needs_clarification,
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
            "missing_facts": missing_facts,
            "needs_clarification": needs_clarification,
            "clarification_prompt": clarification_prompt or None,
            "research_plan": research_plan,
            "search_queries": clean_queries,
            "search_time_range": time_range,
            "execution_trace": trace,
            "node_errors": errors,
        }
    finally:
        reset_log_context(tokens)

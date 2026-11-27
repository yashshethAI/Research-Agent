from __future__ import annotations

import logging
import time
from typing import Any

from backend.app.agents.state import ResearchState
from backend.app.core.logging_utils import (
    make_node_error,
    make_trace_entry,
    reset_log_context,
    set_log_context,
)
from backend.app.storage.conversations import conversation_storage
from backend.app.storage.research import research_storage

logger = logging.getLogger(__name__)


async def save_session_node(state: ResearchState) -> dict[str, Any]:
    """Node 5: Persists conversation turns and full diagnostic research artifacts to local storage."""
    t0 = time.perf_counter()
    tokens = set_log_context(
        conversation_id=state.conversation_id,
        research_id=state.research_id,
        node="save_session",
        tier=state.search_tier,
    )
    errors = list(state.node_errors)
    trace = list(state.execution_trace)

    try:
        conv_id = state.conversation_id
        res_id = state.research_id

        if conv_id and state.query:
            conversation_storage.append_message(
                conversation_id=conv_id,
                role="user",
                content=state.query,
                metadata={"user_role": state.user_role},
            )
            conversation_storage.append_message(
                conversation_id=conv_id,
                role="assistant",
                content=state.final_report,
                metadata={
                    "research_id": res_id,
                    "evidence_count": len(state.evidence_records),
                    "needs_clarification": state.needs_clarification,
                },
            )

        dur = int((time.perf_counter() - t0) * 1000)
        trace.append(make_trace_entry("save_session", state.search_tier, "ok", dur, {"persisted": True}))

        if res_id:
            research_storage.save_research_session(
                research_id=res_id,
                conversation_id=conv_id,
                query=state.query,
                research_plan={
                    **(state.research_plan or {}),
                    "attempted_queries": state.attempted_queries,
                    "attempted_tiers": state.attempted_tiers,
                    "search_time_range": state.search_time_range,
                },
                search_results=state.search_results,
                evidence=state.evidence_records,
                answer_md=state.final_report,
                metadata={
                    "user_role": state.user_role,
                    "gst_topics": state.extracted_facts.get("gst_topics", []),
                    "financial_year": state.extracted_facts.get("financial_year"),
                    "evidence_count": len(state.evidence_records),
                    "needs_clarification": state.needs_clarification,
                    "citation_validation": state.citation_validation,
                    "execution_trace": trace,
                    "node_errors": errors,
                },
            )

        logger.info(f"Persisted session {res_id} (errors={len(errors)})")
        return {
            "current_step": "save_session",
            "persisted": True,
            "execution_trace": trace,
            "node_errors": errors,
        }
    except Exception as e:
        logger.error(f"Error persisting session {state.research_id}: {e}", exc_info=True)
        errors.append(make_node_error("save_session", "persist", e, state.research_id))
        dur = int((time.perf_counter() - t0) * 1000)
        trace.append(make_trace_entry("save_session", state.search_tier, "error", dur, error=str(e)))
        return {
            "current_step": "save_session",
            "persisted": False,
            "execution_trace": trace,
            "node_errors": errors,
        }
    finally:
        reset_log_context(tokens)

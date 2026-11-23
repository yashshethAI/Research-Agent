from __future__ import annotations

import logging

from backend.app.agents.state import ResearchState
from backend.app.storage.conversations import conversation_storage
from backend.app.storage.research import research_storage

logger = logging.getLogger(__name__)


async def persistence_node(state: ResearchState) -> dict:
    """Node 13: Persists conversation message and research session artifacts to filesystem storage."""
    conv_id = state.conversation_id
    res_id = state.research_id
    query = state.query
    final_report = state.final_report

    try:
        # 1. Save user query and assistant answer to conversation JSONL
        if conv_id and query:
            conversation_storage.append_message(
                conversation_id=conv_id,
                role="user",
                content=query,
                metadata={"user_role": state.user_role},
            )
            conversation_storage.append_message(
                conversation_id=conv_id,
                role="assistant",
                content=final_report,
                metadata={
                    "research_id": res_id,
                    "evidence_count": len(state.evidence_records),
                    "needs_clarification": state.needs_clarification,
                },
            )

        # 2. Save structured research artifacts
        if res_id:
            research_storage.save_research_session(
                research_id=res_id,
                conversation_id=conv_id,
                query=query,
                research_plan=state.research_plan,
                search_results=state.search_results,
                evidence=state.evidence_records,
                answer_md=final_report,
                metadata={
                    "user_role": state.user_role,
                    "gst_topics": state.extracted_facts.get("gst_topics", []),
                    "financial_year": state.extracted_facts.get("financial_year"),
                    "jurisdiction": state.extracted_facts.get("jurisdiction"),
                    "evidence_count": len(state.evidence_records),
                    "needs_clarification": state.needs_clarification,
                },
            )

        logger.info(f"Successfully persisted conversation {conv_id} and research session {res_id}")
        return {
            "current_step": "persistence_node",
            "persisted": True,
        }
    except Exception as e:
        logger.error(f"Error persisting research session {res_id}: {e}")
        return {
            "current_step": "persistence_node",
            "persisted": False,
        }

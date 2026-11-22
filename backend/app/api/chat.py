from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.app.agents.graph import gst_research_graph
from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory
from backend.app.schemas.api import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


NODE_STEP_LABELS: dict[str, str] = {
    "load_conversation": "Loaded conversation history",
    "query_understanding": "Parsed GST topics, tax periods, and material facts",
    "fact_extraction": "Consolidated material facts and assumptions",
    "research_planner": "Formulated statutory lookup & authority plan",
    "search_query_generation": "Generated sanitized official search queries",
    "official_source_search": "Queried official CBIC / GST portal registries",
    "source_fetcher": "Safely retrieved official statutory documents",
    "document_extractor": "Extracted statutory provisions and circular texts",
    "evidence_compiler": "Indexed and structured legal evidence records",
    "legal_analysis": "Completed date-aware statutory legal analysis",
    "citation_validator": "Audited citations against official sources",
    "answer_generator": "Synthesized 12-section GST Research Memorandum",
    "persistence_node": "Persisted session artifacts to local storage",
}


@router.post("", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """Executes a GST legal research session synchronously through LangGraph."""
    conv_id = request.conversation_id or str(uuid.uuid4())
    res_id = str(uuid.uuid4())

    initial_state = ResearchState(
        conversation_id=conv_id,
        research_id=res_id,
        query=request.query,
        user_role=request.user_role,
        attachment_ids=request.attachment_ids or [],
    )

    try:
        final_state = await gst_research_graph.ainvoke(initial_state)
        # Handle dict or ResearchState return from graph
        state_dict = final_state if isinstance(final_state, dict) else final_state.model_dump()

        return ChatResponse(
            research_id=res_id,
            conversation_id=conv_id,
            answer=state_dict.get("final_report", ""),
            evidence=state_dict.get("evidence_records", []),
            citations=state_dict.get("citation_validation", {}).get("verified_citations", []),
            needs_clarification=state_dict.get("needs_clarification", False),
            clarification_prompt=state_dict.get("clarification_prompt"),
            llm_configured=llm_factory.is_configured(),
            status="completed",
        )
    except Exception as e:
        logger.error(f"Error executing research graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Research graph execution failed: {e!s}")


@router.post("/stream")
async def chat_stream_endpoint(request: ChatRequest) -> StreamingResponse:
    """Streams research progress events and final answer via Server-Sent Events (SSE)."""
    conv_id = request.conversation_id or str(uuid.uuid4())
    res_id = str(uuid.uuid4())

    initial_state = ResearchState(
        conversation_id=conv_id,
        research_id=res_id,
        query=request.query,
        user_role=request.user_role,
        attachment_ids=request.attachment_ids or [],
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Emit start event
            yield f"data: {json.dumps({'event': 'started', 'conversation_id': conv_id, 'research_id': res_id})}\n\n"

            # Stream intermediate node steps and track accumulated outputs
            final_report = ""
            evidence_records: list[dict[str, Any]] = []
            citations: list[dict[str, Any]] = []
            needs_clarification = False

            async for event in gst_research_graph.astream(initial_state, stream_mode="updates"):
                for node_name, node_output in event.items():
                    if isinstance(node_output, dict):
                        if node_output.get("final_report"):
                            final_report = node_output["final_report"]
                        if node_output.get("evidence_records"):
                            evidence_records = node_output["evidence_records"]
                        if node_output.get("citation_validation"):
                            citations = node_output["citation_validation"].get("verified_citations", [])
                        if "needs_clarification" in node_output:
                            needs_clarification = node_output["needs_clarification"]

                    step_label = NODE_STEP_LABELS.get(node_name, f"Completed node: {node_name}")
                    step_event = {
                        "event": "step",
                        "node": node_name,
                        "label": step_label,
                        "status": "completed",
                    }
                    yield f"data: {json.dumps(step_event)}\n\n"

            # After full graph execution, emit complete event with full response
            complete_event = {
                "event": "complete",
                "conversation_id": conv_id,
                "research_id": res_id,
                "answer": final_report,
                "evidence": evidence_records,
                "citations": citations,
                "needs_clarification": needs_clarification,
            }
            yield f"data: {json.dumps(complete_event)}\n\n"

        except Exception as e:
            logger.error(f"Error during SSE streaming: {e}", exc_info=True)
            error_event = {
                "event": "error",
                "detail": str(e),
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

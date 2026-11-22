from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.app.agents.graph import gst_research_graph
from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory
from backend.app.schemas.api import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


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

            # Stream intermediate node steps
            final_output = None
            async for event in gst_research_graph.astream(initial_state, stream_mode="updates"):
                for node_name, node_output in event.items():
                    step_event = {
                        "event": "step",
                        "node": node_name,
                        "status": "completed",
                    }
                    yield f"data: {json.dumps(step_event)}\n\n"
                    final_output = node_output

            # After full graph execution, retrieve full state
            # Run persistence check
            complete_event = {
                "event": "complete",
                "conversation_id": conv_id,
                "research_id": res_id,
                "answer": final_output.get("final_report") if isinstance(final_output, dict) else "",
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

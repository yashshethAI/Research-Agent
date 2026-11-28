from __future__ import annotations

import asyncio
import json
import logging
import time
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

_SSE_HEARTBEAT_INTERVAL_S = 15.0


NODE_STEP_LABELS: dict[str, str] = {
    "understand_query": "Analyzed query, conversation history & research plan",
    "retrieve_evidence": "Searched sources & extracted query-relevant passages",
    "synthesize_answer": "Drafted plain-English bulleted GST advisory",
    "validate_citations": "Audited inline links and statutory citations",
    "save_session": "Persisted conversation and diagnostic trace",
}


@router.post("", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """Executes a GST legal research session synchronously through the 5-node LangGraph."""
    conv_id = request.conversation_id or str(uuid.uuid4())
    res_id = str(uuid.uuid4())

    initial_state = ResearchState(
        conversation_id=conv_id,
        research_id=res_id,
        query=request.query,
        user_role=request.user_role,
    )

    try:
        final_state = await gst_research_graph.ainvoke(initial_state)
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
            search_tiers_used=state_dict.get("attempted_tiers", []),
            node_errors=state_dict.get("node_errors", []),
            status="completed",
        )
    except Exception as e:
        logger.error(f"Error executing research graph (conv={conv_id[:8]} res={res_id[:8]}): {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Research graph execution failed (research_id={res_id}): {type(e).__name__}: {e!s}",
        )


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
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield f"data: {json.dumps({'event': 'started', 'conversation_id': conv_id, 'research_id': res_id})}\n\n"

            final_report = ""
            evidence_records: list[dict[str, Any]] = []
            citations: list[dict[str, Any]] = []
            needs_clarification = False
            attempted_tiers: list[str] = []
            node_errors: list[dict[str, Any]] = []

            queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

            async def _produce_graph_events() -> None:
                try:
                    async for ev in gst_research_graph.astream(initial_state, stream_mode="updates"):
                        await queue.put(("update", ev))
                    await queue.put(("done", None))
                except Exception as exc:
                    await queue.put(("error", exc))

            producer_task = asyncio.create_task(_produce_graph_events())
            t_start = time.monotonic()

            try:
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(
                            queue.get(),
                            timeout=_SSE_HEARTBEAT_INTERVAL_S,
                        )
                    except asyncio.TimeoutError:
                        hb_event = {
                            "event": "heartbeat",
                            "elapsed_s": int(time.monotonic() - t_start),
                        }
                        yield f"data: {json.dumps(hb_event)}\n\n"
                        continue

                    if kind == "done":
                        break
                    if kind == "error":
                        raise payload

                    event = payload
                    for node_name, node_output in event.items():
                        tier_label = ""
                        if isinstance(node_output, dict):
                            if node_output.get("final_report"):
                                final_report = node_output["final_report"]
                            if node_output.get("evidence_records") is not None:
                                evidence_records = node_output["evidence_records"]
                            if node_output.get("citation_validation"):
                                citations = node_output["citation_validation"].get("verified_citations", [])
                            if "needs_clarification" in node_output:
                                needs_clarification = node_output["needs_clarification"]
                            if node_output.get("attempted_tiers"):
                                attempted_tiers = node_output["attempted_tiers"]
                                tier_label = attempted_tiers[-1]
                            if node_output.get("node_errors"):
                                node_errors = node_output["node_errors"]

                        step_label = NODE_STEP_LABELS.get(node_name, f"Completed node: {node_name}")
                        if node_name == "retrieve_evidence" and tier_label:
                            step_label = f"{step_label} (Tier: {tier_label})"

                        step_event = {
                            "event": "step",
                            "node": node_name,
                            "tier": tier_label or None,
                            "label": step_label,
                            "status": "completed",
                        }
                        yield f"data: {json.dumps(step_event)}\n\n"
            finally:
                if not producer_task.done():
                    producer_task.cancel()
                    try:
                        await producer_task
                    except asyncio.CancelledError:
                        pass

            if not (final_report or "").strip() and not needs_clarification:
                logger.warning(f"Stream completed with empty answer (conv={conv_id[:8]} res={res_id[:8]})")
                final_report = (
                    "### Error Generating GST Advisory\n\n"
                    "The research pipeline completed without generating text. "
                    "Please retry your query or check `LLM_MAX_TOKENS` / `LLM_REASONING_EFFORT` in `.env`."
                )

            complete_event = {
                "event": "complete",
                "conversation_id": conv_id,
                "research_id": res_id,
                "answer": final_report,
                "evidence": evidence_records,
                "citations": citations,
                "needs_clarification": needs_clarification,
                "search_tiers_used": attempted_tiers,
                "node_errors": node_errors,
            }
            yield f"data: {json.dumps(complete_event)}\n\n"

        except Exception as e:
            logger.error(f"Error during SSE streaming (conv={conv_id[:8]} res={res_id[:8]}): {e}", exc_info=True)
            error_event = {
                "event": "error",
                "research_id": res_id,
                "detail": f"{type(e).__name__}: {e!s}",
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

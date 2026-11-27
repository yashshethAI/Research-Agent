from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from backend.app.agents.nodes.retrieve_evidence import retrieve_evidence_node
from backend.app.agents.nodes.save_session import save_session_node
from backend.app.agents.nodes.synthesize_answer import synthesize_answer_node
from backend.app.agents.nodes.understand_query import understand_query_node
from backend.app.agents.nodes.validate_citations import validate_citations_node
from backend.app.agents.state import ResearchState

logger = logging.getLogger(__name__)


def route_after_understanding(state: ResearchState) -> str:
    """Routes directly to synthesize_answer if unconfigured or clarification is needed."""
    if state.llm_unconfigured_guidance or state.needs_clarification:
        return "clarify_or_unconfigured"
    return "retrieve"


def route_after_retrieval(state: ResearchState) -> str:
    """Escalates to next source tier via retrieve_evidence if evidence is insufficient."""
    if state.should_refine_search:
        return "escalate_tier"
    return "synthesize"


def create_gst_research_graph() -> StateGraph:
    """Constructs the clean 5-node LangGraph for tiered GST legal research."""
    builder = StateGraph(ResearchState)

    builder.add_node("understand_query", understand_query_node)
    builder.add_node("retrieve_evidence", retrieve_evidence_node)
    builder.add_node("synthesize_answer", synthesize_answer_node)
    builder.add_node("validate_citations", validate_citations_node)
    builder.add_node("save_session", save_session_node)

    builder.add_edge(START, "understand_query")
    builder.add_conditional_edges(
        "understand_query",
        route_after_understanding,
        {
            "clarify_or_unconfigured": "synthesize_answer",
            "retrieve": "retrieve_evidence",
        },
    )
    builder.add_conditional_edges(
        "retrieve_evidence",
        route_after_retrieval,
        {
            "escalate_tier": "retrieve_evidence",
            "synthesize": "synthesize_answer",
        },
    )
    builder.add_edge("synthesize_answer", "validate_citations")
    builder.add_edge("validate_citations", "save_session")
    builder.add_edge("save_session", END)

    return builder.compile()


# Compiled singleton graph
gst_research_graph = create_gst_research_graph()

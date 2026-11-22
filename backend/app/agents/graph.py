from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from backend.app.agents.nodes.answer_generator import answer_generator_node
from backend.app.agents.nodes.citation_validator import citation_validator_node
from backend.app.agents.nodes.document_extractor import document_extractor_node
from backend.app.agents.nodes.evidence_compiler import evidence_compiler_node
from backend.app.agents.nodes.fact_extraction import fact_extraction_node
from backend.app.agents.nodes.legal_analysis import legal_analysis_node
from backend.app.agents.nodes.load_conversation import load_conversation_node
from backend.app.agents.nodes.official_source_search import official_source_search_node
from backend.app.agents.nodes.persistence_node import persistence_node
from backend.app.agents.nodes.query_understanding import query_understanding_node
from backend.app.agents.nodes.research_planner import research_planner_node
from backend.app.agents.nodes.search_query_generation import (
    search_query_generation_node,
)
from backend.app.agents.nodes.source_fetcher import source_fetcher_node
from backend.app.agents.state import ResearchState

logger = logging.getLogger(__name__)


def route_after_fact_extraction(state: ResearchState) -> str:
    """Routes to answer_generator if clarification needed or LLM unconfigured, else continues to research_planner."""
    if state.llm_unconfigured_guidance or state.needs_clarification:
        return "clarify_or_unconfigured"
    return "plan_research"


def route_after_citation_validator(state: ResearchState) -> str:
    """Routes back to search_query_generation if refinement needed and retry limit not reached, else answer_generator."""
    if state.should_refine_search:
        return "refine_search"
    return "generate_answer"


def create_gst_research_graph() -> StateGraph:
    """Constructs the coordinated 13-node LangGraph for GST Legal Research."""
    builder = StateGraph(ResearchState)

    # 1. Register all 13 nodes
    builder.add_node("load_conversation", load_conversation_node)
    builder.add_node("query_understanding", query_understanding_node)
    builder.add_node("fact_extraction", fact_extraction_node)
    builder.add_node("research_planner", research_planner_node)
    builder.add_node("search_query_generation", search_query_generation_node)
    builder.add_node("official_source_search", official_source_search_node)
    builder.add_node("source_fetcher", source_fetcher_node)
    builder.add_node("document_extractor", document_extractor_node)
    builder.add_node("evidence_compiler", evidence_compiler_node)
    builder.add_node("legal_analysis", legal_analysis_node)
    builder.add_node("citation_validator", citation_validator_node)
    builder.add_node("answer_generator", answer_generator_node)
    builder.add_node("persistence_node", persistence_node)

    # 2. Add sequential and conditional edges
    builder.add_edge(START, "load_conversation")
    builder.add_edge("load_conversation", "query_understanding")
    builder.add_edge("query_understanding", "fact_extraction")

    # Conditional edge after fact extraction
    builder.add_conditional_edges(
        "fact_extraction",
        route_after_fact_extraction,
        {
            "clarify_or_unconfigured": "answer_generator",
            "plan_research": "research_planner",
        },
    )

    builder.add_edge("research_planner", "search_query_generation")
    builder.add_edge("search_query_generation", "official_source_search")
    builder.add_edge("official_source_search", "source_fetcher")
    builder.add_edge("source_fetcher", "document_extractor")
    builder.add_edge("document_extractor", "evidence_compiler")
    builder.add_edge("evidence_compiler", "legal_analysis")
    builder.add_edge("legal_analysis", "citation_validator")

    # Conditional edge after citation validator (refinement loop)
    builder.add_conditional_edges(
        "citation_validator",
        route_after_citation_validator,
        {
            "refine_search": "search_query_generation",
            "generate_answer": "answer_generator",
        },
    )

    builder.add_edge("answer_generator", "persistence_node")
    builder.add_edge("persistence_node", END)

    return builder.compile()


# Compiled singleton graph
gst_research_graph = create_gst_research_graph()

from __future__ import annotations

import pytest

from backend.app.agents.graph import (
    gst_research_graph,
    route_after_citation_validator,
    route_after_fact_extraction,
)
from backend.app.agents.state import ResearchState


def test_routing_after_fact_extraction():
    state1 = ResearchState(needs_clarification=True)
    assert route_after_fact_extraction(state1) == "clarify_or_unconfigured"

    state2 = ResearchState(llm_unconfigured_guidance="Setup required")
    assert route_after_fact_extraction(state2) == "clarify_or_unconfigured"

    state3 = ResearchState(needs_clarification=False, llm_unconfigured_guidance=None)
    assert route_after_fact_extraction(state3) == "plan_research"


def test_routing_after_citation_validator():
    state1 = ResearchState(should_refine_search=True)
    assert route_after_citation_validator(state1) == "refine_search"

    state2 = ResearchState(should_refine_search=False)
    assert route_after_citation_validator(state2) == "generate_answer"


@pytest.mark.asyncio
async def test_graph_execution_unconfigured_llm():
    # When LLM is unconfigured, graph must complete smoothly and return guidance
    state = ResearchState(
        conversation_id="conv-unconfig-test",
        research_id="res-unconfig-test",
        query="What is the place of supply for freight forwarding?",
        user_role="Professional",
    )

    result = await gst_research_graph.ainvoke(state)
    result_dict = result if isinstance(result, dict) else result.model_dump()

    assert "INFERENCE SETUP REQUIRED" in result_dict.get("final_report", "")
    assert result_dict.get("persisted") is True

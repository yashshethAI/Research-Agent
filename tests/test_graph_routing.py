from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.agents.graph import (
    gst_research_graph,
    route_after_retrieval,
    route_after_understanding,
)
from backend.app.agents.nodes.understand_query import understand_query_node
from backend.app.agents.nodes.validate_citations import validate_citations_node
from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory


def test_routing_after_understanding():
    state1 = ResearchState(needs_clarification=True)
    assert route_after_understanding(state1) == "clarify_or_unconfigured"

    state2 = ResearchState(llm_unconfigured_guidance="Setup required")
    assert route_after_understanding(state2) == "clarify_or_unconfigured"

    state3 = ResearchState(needs_clarification=False, llm_unconfigured_guidance=None)
    assert route_after_understanding(state3) == "retrieve"


def test_routing_after_retrieval():
    state1 = ResearchState(should_refine_search=True)
    assert route_after_retrieval(state1) == "escalate_tier"

    state2 = ResearchState(should_refine_search=False)
    assert route_after_retrieval(state2) == "synthesize"


@pytest.mark.asyncio
async def test_understand_query_strips_think_tags_and_triggers_clarification(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: True)

    class _FakeLLM:
        async def ainvoke(self, messages):
            return SimpleNamespace(
                content=(
                    "<think>User did not mention filing date for FY 2019-20.</think>\n"
                    '{"gst_topics": ["Input Tax Credit", "Section 16(4)"], '
                    '"financial_year": "FY 2019-20", '
                    '"taxpayer_type": "Regular Registered Taxable Person", '
                    '"target_sections": ["Section 16(4)", "Section 16(5)"], '
                    '"needs_clarification": true, '
                    '"clarification_question": "- Did you file GSTR-3B on or before 30 Nov 2021?", '
                    '"missing_facts": ["GSTR-3B filing date"], '
                    '"search_queries": ["Section 16(5) CGST Act site:cbic.gov.in"], '
                    '"time_range": null}'
                )
            )

    monkeypatch.setattr(llm_factory, "get_chat_model", lambda max_tokens=None: _FakeLLM())

    state = ResearchState(
        conversation_id="conv-clarify-test",
        research_id="res-clarify-test",
        query="Is my ITC for FY 2019-20 valid?",
    )
    out = await understand_query_node(state)
    assert out["needs_clarification"] is True
    assert "30 Nov 2021" in (out["clarification_prompt"] or "")
    # site: token stripped deterministically
    assert all("site:" not in q for q in out["search_queries"])
    assert out["execution_trace"][0]["node"] == "understand_query"


@pytest.mark.asyncio
async def test_understand_query_records_node_error_on_malformed_json(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: True)

    class _BadJsonLLM:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="Here is my analysis without JSON")

    monkeypatch.setattr(llm_factory, "get_chat_model", lambda max_tokens=None: _BadJsonLLM())

    state = ResearchState(
        conversation_id="conv-badjson-test",
        research_id="res-badjson-test",
        query="What is Section 16(4) ITC limit?",
    )
    out = await understand_query_node(state)
    assert out["needs_clarification"] is False
    assert len(out["search_queries"]) >= 1
    assert any(err["substep"] == "json_parse" for err in out["node_errors"])


@pytest.mark.asyncio
async def test_validate_citations_resolves_src_ids_and_audits_ungrounded_claims():
    state = ResearchState(
        query="Explain Section 16(5) retrospective ITC relief",
        evidence_records=[
            {
                "source_id": "SRC-001",
                "title": "Circular No. 211/5/2024-GST",
                "url": "https://www.cbic.gov.in/circular-211.pdf",
                "authority": "CBIC",
                "source_tier": "official",
                "fetch_status": "fetched",
                "section_or_rule": "Section 16(5)",
                "excerpt": "Circular No. 211/5/2024 clarifies Section 16(5) retrospective relief.",
                "verified": True,
            }
        ],
        final_report=(
            "- [PERMITTED] Under [Section 16(5)](SRC-001) and [Circular 211/5/2024](SRC-001).\n"
            "- See also [Fake Blog](https://hallucinated.example/fake) and Circular No. 999/99/2025-GST."
        ),
    )

    out = await validate_citations_node(state)
    report = out["final_report"]
    validation = out["citation_validation"]

    assert "https://www.cbic.gov.in/circular-211.pdf" in report
    assert "https://hallucinated.example/fake" not in report
    assert validation["links_resolved"] == 2
    assert validation["links_stripped"] == 1
    assert any("999/99/2025" in c for c in validation["unverified_claims"])


@pytest.mark.asyncio
async def test_graph_execution_unconfigured_llm(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: False)
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
    assert len(result_dict.get("execution_trace", [])) >= 3

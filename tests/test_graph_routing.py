from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.agents.graph import (
    gst_research_graph,
    route_after_retrieval,
    route_after_understanding,
)
from backend.app.agents.nodes.synthesize_answer import synthesize_answer_node
from backend.app.agents.nodes.understand_query import understand_query_node
from backend.app.agents.nodes.validate_citations import validate_citations_node
from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory, research_llm_factory


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
    monkeypatch.setattr(research_llm_factory, "is_configured", lambda: True)

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

    monkeypatch.setattr(research_llm_factory, "get_chat_model", lambda max_tokens=None: _FakeLLM())

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
    monkeypatch.setattr(research_llm_factory, "is_configured", lambda: True)

    class _BadJsonLLM:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="Here is my analysis without JSON")

    monkeypatch.setattr(research_llm_factory, "get_chat_model", lambda max_tokens=None: _BadJsonLLM())

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
async def test_validate_citations_resolves_bare_and_parenthetical_src_refs():
    state = ResearchState(
        query="DRC-01A procedure under Rule 142",
        evidence_records=[
            {
                "source_id": "SRC-002",
                "title": "Circular 185/17/2022-GST",
                "url": "https://gstcouncil.gov.in/cir-185.pdf",
                "authority": "CBIC",
                "source_tier": "official",
                "fetch_status": "fetched",
                "section_or_rule": "Section 73",
                "excerpt": "Section 73(2) timeline.",
                "verified": True,
            },
            {
                "source_id": "SRC-004",
                "title": "Rule 142",
                "url": "https://taxinformation.cbic.gov.in/rule142.html",
                "authority": "CBIC",
                "source_tier": "official",
                "fetch_status": "fetched",
                "section_or_rule": "Rule 142",
                "excerpt": "Part B of FORM GST DRC-01A.",
                "verified": True,
            },
        ],
        final_report="- Timeline applies (SRC-002).\n- Reply via DRC-01A [SRC-004] or [SRC-002, SRC-004].",
    )

    out = await validate_citations_node(state)
    report = out["final_report"]
    assert "([SRC-002](https://gstcouncil.gov.in/cir-185.pdf))" in report
    assert "[SRC-004](https://taxinformation.cbic.gov.in/rule142.html)" in report
    assert out["citation_validation"]["links_resolved"] == 4


@pytest.mark.asyncio
async def test_understand_query_enforces_one_shot_clarification_and_isolates_history(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: True)
    monkeypatch.setattr(research_llm_factory, "is_configured", lambda: True)
    captured_prompts: list[str] = []

    class _LoopingClarifyLLM:
        async def ainvoke(self, messages):
            captured_prompts.append(messages[1].content)
            return SimpleNamespace(
                content=(
                    '{"gst_topics": ["Motor Vehicle ITC"], '
                    '"financial_year": "FY 2026-27", '
                    '"taxpayer_type": "Regular Registered Taxable Person", '
                    '"target_sections": ["Section 17(5)", "Notification No. 12/2026"], '
                    '"needs_clarification": true, '
                    '"clarification_question": "Ask again?", '
                    '"missing_facts": ["Extra detail"], '
                    '"search_queries": ["Section 17(5) goods transport truck ITC repair insurance"], '
                    '"time_range": null}'
                )
            )

    monkeypatch.setattr(research_llm_factory, "get_chat_model", lambda max_tokens=None: _LoopingClarifyLLM())

    history = [
        {"role": "user", "content": "Old FY 2017-18 textile refund question", "metadata": {}},
        {"role": "assistant", "content": "Old textile refund answer", "metadata": {"needs_clarification": False}},
        {"role": "user", "content": "Can my client claim ITC on motor vehicle repair and insurance?", "metadata": {}},
        {"role": "assistant", "content": "What type of vehicle is it?", "metadata": {"needs_clarification": True}},
    ]
    state = ResearchState(
        conversation_id="conv-one-shot",
        research_id="res-one-shot",
        query="It is a goods transport truck for business deliveries",
        messages=history,
    )
    out = await understand_query_node(state)
    # One-shot clarification prevents looping again
    assert out["needs_clarification"] is False
    # Old unrelated FY 2017-18 textile question must not leak into active context
    assert "textile refund" not in captured_prompts[0]
    # Root vehicle question + follow-up preserved together
    assert "motor vehicle repair and insurance" in out["extracted_facts"]["effective_query"]
    assert "goods transport truck" in out["extracted_facts"]["effective_query"]
    # Hallucinated Notification No. 12/2026 stripped from target_sections
    assert "Notification No. 12/2026" not in out["research_plan"]["target_sections"]


@pytest.mark.asyncio
async def test_synthesize_answer_blocks_llm_hallucination_on_zero_evidence(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: True)

    def _should_not_be_called(max_tokens=None):
        raise AssertionError("LLM must not be called when evidence_records is empty")

    monkeypatch.setattr(llm_factory, "get_chat_model", _should_not_be_called)

    state = ResearchState(
        query="Is GST payable on corporate guarantee under Rule 28(2)?",
        evidence_records=[],
        attempted_tiers=["official", "verified_secondary"],
        node_errors=[
            {
                "node": "retrieve_evidence",
                "substep": "search",
                "target": "corporate guarantee",
                "error_type": "SearchEngineRateLimitError",
                "detail": "SearXNG upstream engines blocked/rate-limited (duckduckgo: CAPTCHA)",
            }
        ],
    )
    out = await synthesize_answer_node(state)
    assert "[FURTHER VERIFICATION REQUIRED]" in out["final_report"]
    assert "CAPTCHA" in out["final_report"]


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


@pytest.mark.asyncio
async def test_synthesize_answer_caps_prompt_evidence_budget(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: True)
    captured_prompts: list[str] = []

    class _StreamingAnswerLLM:
        async def astream(self, messages):
            captured_prompts.append(messages[1].content)
            yield SimpleNamespace(content="- [PERMITTED] Exempt under [SRC-001].")

    monkeypatch.setattr(llm_factory, "get_chat_model", lambda max_tokens=None: _StreamingAnswerLLM())

    oversized_records = [
        {
            "source_id": f"SRC-00{i}",
            "title": f"CBIC Source {i}",
            "url": f"https://www.cbic.gov.in/doc-{i}.pdf",
            "authority": "CBIC",
            "source_tier": "official",
            "fetch_status": "fetched",
            "section_or_rule": "Section 22",
            "excerpt": "X" * 2200,
            "verified": True,
        }
        for i in range(1, 6)
    ]
    state = ResearchState(
        query="Is GST registration mandatory for Rs 18 lakh turnover in Gujarat?",
        evidence_records=oversized_records,
    )
    out = await synthesize_answer_node(state)
    assert "[PERMITTED]" in out["final_report"]
    assert len(captured_prompts) == 1
    assert captured_prompts[0].count("X") <= 5500


@pytest.mark.asyncio
async def test_synthesize_answer_retries_with_none_on_empty_reasoning_output(monkeypatch):
    from backend.app.core.config import settings

    monkeypatch.setattr(llm_factory, "is_configured", lambda: True)
    monkeypatch.setattr(settings, "LLM_REASONING_EFFORT", "low")
    calls: list[str | None] = []

    class _EmptyReasoningLLM:
        async def astream(self, messages):
            yield SimpleNamespace(content="", additional_kwargs={"reasoning_content": "thinking..."})

    class _DirectAnswerLLM:
        async def astream(self, messages):
            yield SimpleNamespace(content="- [PERMITTED] Covered under [SRC-001].")

    def fake_get_chat_model(max_tokens=None, reasoning_effort=None):
        calls.append(reasoning_effort)
        if reasoning_effort == "none":
            return _DirectAnswerLLM()
        return _EmptyReasoningLLM()

    monkeypatch.setattr(llm_factory, "get_chat_model", fake_get_chat_model)

    state = ResearchState(
        query="Is e-invoicing applicable?",
        evidence_records=[
            {
                "source_id": "SRC-001",
                "title": "CBIC Rule 48(4)",
                "url": "https://www.cbic.gov.in/rule48.html",
                "authority": "CBIC",
                "source_tier": "official",
                "fetch_status": "fetched",
                "section_or_rule": "Rule 48(4)",
                "excerpt": "E-invoicing threshold rules.",
                "verified": True,
            }
        ],
    )

    out = await synthesize_answer_node(state)
    assert calls == [None, "none"]
    assert "[PERMITTED]" in out["final_report"]

    # If even fallback returns empty, returns explicit error report instead of blank string
    monkeypatch.setattr(llm_factory, "get_chat_model", lambda max_tokens=None, reasoning_effort=None: _EmptyReasoningLLM())
    err_out = await synthesize_answer_node(state)
    assert "Error Generating GST Advisory" in err_out["final_report"]
    assert any(e["node"] == "synthesize_answer" for e in err_out["node_errors"])

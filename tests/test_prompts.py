from __future__ import annotations

from pathlib import Path

from backend.app.agents.prompts import (
    FINAL_ANSWER_MEMORANDUM_PROMPT,
    QUERY_UNDERSTANDING_PROMPT,
    UNIFIED_GST_LEGAL_REASONING_PROMPT,
)


def test_query_understanding_prompt_for_small_models():
    assert "{current_date}" in QUERY_UNDERSTANDING_PROMPT
    assert "{current_fy}" in QUERY_UNDERSTANDING_PROMPT
    assert "{context}" in QUERY_UNDERSTANDING_PROMPT
    assert "{query}" in QUERY_UNDERSTANDING_PROMPT
    assert "needs_clarification" in QUERY_UNDERSTANDING_PROMPT
    assert "search_queries" in QUERY_UNDERSTANDING_PROMPT
    assert "time_range" in QUERY_UNDERSTANDING_PROMPT


def test_unified_gst_legal_reasoning_prompt_structure():
    """Verify flexible plain-English bullet instructions, temporal anchors, and SRC-ID linking."""
    assert "clean bullet points" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "Do NOT pad answers or force a fixed number of bullets" in UNIFIED_GST_LEGAL_REASONING_PROMPT

    assert "{current_date}" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "{current_fy}" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "{preceding_fy}" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "TEMPORAL REFERENCE BASELINE" in UNIFIED_GST_LEGAL_REASONING_PROMPT

    assert "STATUTORY SUBJECT ALIGNMENT" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "Article 279A" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "ERP VS PORTAL JURISDICTION" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "SRC-001" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "unverified_fallback" in UNIFIED_GST_LEGAL_REASONING_PROMPT

    assert "Section 9(1) vs 15(5)" not in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "183/15/2022" not in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert FINAL_ANSWER_MEMORANDUM_PROMPT == UNIFIED_GST_LEGAL_REASONING_PROMPT


def test_workspace_rules_updated():
    format_rule = Path(__file__).resolve().parent.parent / ".agents" / "rules" / "gst-advisory-format.md"
    assert format_rule.exists()
    format_content = format_rule.read_text(encoding="utf-8")
    assert "Flexible Structure" in format_content
    assert "Plain-English Bulleted Clarity" in format_content

    search_rule = Path(__file__).resolve().parent.parent / ".agents" / "rules" / "search-provider-policy.md"
    assert search_rule.exists()
    search_content = search_rule.read_text(encoding="utf-8")
    assert "3-Tier Official-First Search & Fallback Policy" in search_content
    assert "ALLOW_UNVERIFIED_FALLBACK" in search_content

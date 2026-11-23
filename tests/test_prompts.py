from __future__ import annotations

from pathlib import Path

from backend.app.agents.prompts import (
    FINAL_ANSWER_MEMORANDUM_PROMPT,
    UNIFIED_GST_LEGAL_REASONING_PROMPT,
)


def test_unified_gst_legal_reasoning_prompt_structure():
    """Verify Section 2 prompt contains the required simplified, to-the-point bullet format."""
    # Heading check
    assert "## 2. Legal and Statutory Explanation" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "## 2. Legal Explanation & Statutory Reasoning" not in UNIFIED_GST_LEGAL_REASONING_PROMPT

    # Bullet format instruction checks
    assert "clean, simplified, to-the-point bullet format" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "strictly concise (1 to 2 sentences per bullet)" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "Governing Statutory Provision" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "Date & Retrospective Applicability" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "CBIC Circular & Judicial Position" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "Direct Impact on Taxpayer" in UNIFIED_GST_LEGAL_REASONING_PROMPT

    # Temporal baseline checks
    assert "{current_date}" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "{current_fy}" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "{preceding_fy}" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "TEMPORAL REFERENCE BASELINE" in UNIFIED_GST_LEGAL_REASONING_PROMPT
    assert "CRITICAL LEGAL REASONING INVARIANTS" in UNIFIED_GST_LEGAL_REASONING_PROMPT

    # Alias check
    assert FINAL_ANSWER_MEMORANDUM_PROMPT == UNIFIED_GST_LEGAL_REASONING_PROMPT


def test_workspace_formatting_rule_exists():
    """Verify the persistent workspace rule exists and enforces Section 2 bullet format."""
    rule_path = Path(__file__).resolve().parent.parent / ".agents" / "rules" / "gst-advisory-format.md"
    assert rule_path.exists(), "Workspace rule file .agents/rules/gst-advisory-format.md must exist."

    content = rule_path.read_text(encoding="utf-8")
    assert "## 2. Legal and Statutory Explanation" in content
    assert "Thematic Organization" in content
    assert "Punchy & To the Point" in content

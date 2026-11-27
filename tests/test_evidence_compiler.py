from __future__ import annotations

from backend.app.tools.evidence_extractor import (
    compile_relevant_evidence,
    detect_spa_shell,
    normalize_llm_search_queries,
    rerank_search_results,
)
from backend.app.tools.search.base import SearchResult


def test_normalize_llm_search_queries_strips_site_and_pii():
    raw = [
        "Section 16(4) ITC time limit for 27AABCU9603R1ZN site:taxinformation.cbic.gov.in",
        "Can a registered taxpayer in India claim input tax credit on motor vehicle repair services under Section 17(5)?",
    ]
    cleaned = normalize_llm_search_queries(raw, max_queries=4, max_words=8)
    assert len(cleaned) == 2
    assert "site:" not in cleaned[0].lower()
    assert "27AABCU9603R1ZN" not in cleaned[0]
    assert "[REDACTED_GSTIN]" in cleaned[0]
    assert len(cleaned[1].split()) <= 8


def test_compile_relevant_evidence_finds_deep_passages_past_1500_chars():
    preamble = "MINISTRY OF FINANCE GAZETTE HEADER BOILERPLATE. " * 60  # > 2900 chars
    deep_clause = (
        "Vide Notification No. 19/2025-Central Tax (Rate) dated 31 December 2025, "
        "Section 15(5) of the CGST Act, 2017 and Rule 31D govern Retail Sale Price valuation."
    )
    trailing = " Additional procedural annexure text." * 40
    full_text = f"{preamble}\n\n{deep_clause}\n\n{trailing}"

    records = compile_relevant_evidence(
        parsed_docs=[
            {
                "url": "https://taxinformation.cbic.gov.in/notifications/rates",
                "title": "Rate Rationalization Notification",
                "text": full_text,
                "doc_type": "Official Notification",
                "fetch_status": "fetched",
                "sha256_hash": "abc123456",
            }
        ],
        query="Explain Rule 31D and Section 15(5) valuation changes",
        research_plan={"target_sections": ["Section 15(5)", "Rule 31D"]},
        tier="official",
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["verified"] is True
    assert rec["source_tier"] == "official"
    assert "Notification No. 19/2025-Central Tax (Rate)" in rec["excerpt"]
    assert "Rule 31D" in rec["excerpt"]
    assert rec["document_date"] == "31 December 2025"


def test_compile_relevant_evidence_marks_snippet_and_unverified_false():
    records = compile_relevant_evidence(
        parsed_docs=[
            {
                "url": "https://www.cbic.gov.in/doc.pdf",
                "title": "CBIC Circular",
                "text": "Section 16(2) conditions apply.",
                "fetch_status": "snippet_only",
                "sha256_hash": "snip123",
            },
            {
                "url": "https://randomblog.example/gst",
                "title": "Blog explainer",
                "text": "Section 16(2) explanation on blog.",
                "fetch_status": "fetched",
                "sha256_hash": "blog123",
            },
        ],
        query="Section 16(2) conditions",
        tier="unverified_fallback",
    )
    assert records[0]["verified"] is False
    assert records[1]["verified"] is False


def test_detect_spa_shell_and_rerank():
    assert detect_spa_shell("<html><body><app-root></app-root>Enable JavaScript</body></html>", "Enable JavaScript") is True
    assert detect_spa_shell("<html><body><p>Full statutory text...</p></body></html>", "Full statutory text " * 30) is False

    hits = [
        SearchResult(
            title="Blog post on GST",
            url="https://cleartax.in/s/gst-blog",
            snippet="General summary",
            domain="cleartax.in",
            score=9.0,
        ),
        SearchResult(
            title="CBIC Circular 211/5/2024 on Section 16(5)",
            url="https://www.cbic.gov.in/circular-211.pdf",
            snippet="Clarification on Section 16(5) time limit",
            domain="www.cbic.gov.in",
            score=4.0,
        ),
    ]
    ranked = rerank_search_results(hits, query="Section 16(5) Circular 211", target_terms=["Section 16(5)"])
    assert ranked[0].domain == "www.cbic.gov.in"

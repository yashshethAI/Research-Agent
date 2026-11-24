from __future__ import annotations

import pytest

from backend.app.agents.nodes.evidence_compiler import evidence_compiler_node
from backend.app.agents.state import ResearchState


@pytest.mark.asyncio
async def test_evidence_compiler_extracts_gazette_notifications_priority():
    """Verify evidence_compiler extracts Gazette Notifications and prioritizes them over random section mentions."""
    state = ResearchState(
        query="Explain recent changes in GST rates for tobacco",
        parsed_documents=[
            {
                "url": "https://taxinformation.cbic.gov.in/notifications/rates",
                "title": "Rate Rationalization for Pan Masala and Tobacco",
                "text": (
                    "Vide Notification No. 19/2025-Central Tax (Rate) dated 31 December 2025, the Central Government "
                    "amended Schedule III. For valuation of these goods on Retail Sale Price basis, Section 15(5) "
                    "of the CGST Act, 2017 is invoked under Rule 31D."
                ),
                "doc_type": "Official Notification",
                "sha256_hash": "abc123456",
            }
        ],
    )

    result = await evidence_compiler_node(state)
    records = result.get("evidence_records", [])
    assert len(records) == 1
    record = records[0]

    # Gazette notification must be primary
    assert "Notification No. 19/2025-Central Tax (Rate)" in record["section_or_rule"]
    assert "Section 15(5)" in record["section_or_rule"]
    assert record["section_or_rule"].startswith("Notification No. 19/2025-Central Tax (Rate)")


@pytest.mark.asyncio
async def test_evidence_compiler_fallback_to_sections():
    """Verify evidence_compiler extracts sections when no notification is present."""
    state = ResearchState(
        query="ITC eligibility under Section 16(2)",
        parsed_documents=[
            {
                "url": "https://cbic.gov.in/cgst-act",
                "title": "Eligibility and conditions for taking input tax credit",
                "text": "Every registered person shall be entitled to take credit of input tax under Section 16(2) and Section 16(4).",
                "doc_type": "Statute",
                "sha256_hash": "def789",
            }
        ],
    )

    result = await evidence_compiler_node(state)
    records = result.get("evidence_records", [])
    assert len(records) == 1
    assert "Section 16(2)" in records[0]["section_or_rule"]
    assert "Section 16(4)" in records[0]["section_or_rule"]

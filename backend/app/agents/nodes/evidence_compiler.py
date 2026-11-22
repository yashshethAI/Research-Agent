from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from backend.app.agents.state import ResearchState

logger = logging.getLogger(__name__)


def _identify_authority(domain: str) -> str:
    d = domain.lower()
    if "taxinformation.cbic.gov.in" in d or "cbic.gov.in" in d:
        return "Central Board of Indirect Taxes and Customs (CBIC)"
    if "gst.gov.in" in d:
        return "Goods and Services Tax Network (GSTN)"
    if "gstcouncil.gov.in" in d:
        return "GST Council Secretariat"
    if "sci.gov.in" in d:
        return "Supreme Court of India"
    if "court" in d or "judiciary" in d:
        return "High Court / Appellate Tribunal"
    return "Official GST Authority"


async def evidence_compiler_node(state: ResearchState) -> dict:
    """Node 9: Synthesizes extracted text into structured, indexed evidence records."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "evidence_compiler"}

    parsed_docs = state.parsed_documents or []
    evidence_records: list[dict[str, Any]] = []

    for idx, doc in enumerate(parsed_docs, start=1):
        url = doc.get("url", "")
        domain = urlparse(url).hostname or ""
        text = doc.get("text", "")
        title = doc.get("title") or f"Official GST Document {idx}"
        authority = _identify_authority(domain)
        sha_hash = doc.get("sha256_hash", "")

        # Detect statutory references in text
        sections_found = re.findall(r"Section\s+\d+(?:\([0-9a-zA-Z]+\))*", text, flags=re.IGNORECASE)
        rules_found = re.findall(r"Rule\s+\d+[A-Z]?(?:\([0-9a-zA-Z]+\))*", text, flags=re.IGNORECASE)
        circulars_found = re.findall(r"Circular\s+No\.?\s*[\d/]+(?:\-GST)?", text, flags=re.IGNORECASE)

        legal_ref = ""
        if sections_found:
            legal_ref = ", ".join(dict.fromkeys(sections_found[:3]))
        elif rules_found:
            legal_ref = ", ".join(dict.fromkeys(rules_found[:3]))
        elif circulars_found:
            legal_ref = ", ".join(dict.fromkeys(circulars_found[:2]))
        else:
            legal_ref = "General Statutory Framework"

        # Create concise, high-value excerpt (up to 1500 chars)
        excerpt = text[:1500].strip()

        evidence_records.append({
            "source_id": f"SRC-{idx:03d}",
            "title": title,
            "url": url,
            "authority": authority,
            "document_type": doc.get("doc_type", "Statutory Source"),
            "section_or_rule": legal_ref,
            "excerpt": excerpt,
            "retrieval_date": "Current Session",
            "effective_date": "Applicable Tax Period",
            "sha256_hash": sha_hash,
            "verified": True,
        })

    return {
        "current_step": "evidence_compiler",
        "evidence_records": evidence_records,
    }

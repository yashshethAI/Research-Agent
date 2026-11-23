from __future__ import annotations

import logging
from typing import Any

from backend.app.agents.state import ResearchState
from backend.app.tools.html_parser import HTMLParser
from backend.app.tools.pdf_parser import PDFParser

logger = logging.getLogger(__name__)


async def document_extractor_node(state: ResearchState) -> dict:
    """Node 8: Extracts structured text, headings, and tables from HTML and PDF documents."""
    if state.llm_unconfigured_guidance:
        return {"current_step": "document_extractor"}

    fetched = state.fetched_documents or []
    parsed_docs: list[dict[str, Any]] = []

    for item in fetched:
        content_type = item.get("content_type", "")
        content_bytes = item.get("content_bytes", b"")
        url = item.get("url", "")
        sha_hash = item.get("sha256_hash", "")

        try:
            if "pdf" in content_type or url.lower().endswith(".pdf"):
                extracted = PDFParser.parse_pdf_bytes(content_bytes)
                doc_type = "PDF Notification / Circular / Order"
            else:
                html_text = content_bytes.decode("utf-8", errors="replace")
                extracted = HTMLParser.parse_html(html_text, base_url=url)
                doc_type = "Statutory Portal HTML Page"

            parsed_docs.append({
                "url": url,
                "title": extracted.get("title") or url,
                "text": (extracted.get("text") or "")[:40000],  # Guard against massive token overflow
                "doc_type": doc_type,
                "sha256_hash": sha_hash,
                "page_count": extracted.get("page_count", 1),
            })
        except Exception as e:
            logger.error(f"Error parsing document from {url}: {e}")

    # If no documents could be fetched live (e.g. offline/testing), preserve snippets from search_results
    if not parsed_docs and state.search_results:
        for idx, res in enumerate(state.search_results[:3]):
            parsed_docs.append({
                "url": res.get("url", ""),
                "title": res.get("title", ""),
                "text": res.get("snippet") or "",
                "doc_type": "Official Search Record",
                "sha256_hash": f"snippet-hash-{idx}",
                "page_count": 1,
            })

    return {
        "current_step": "document_extractor",
        "parsed_documents": parsed_docs,
        # Clear large raw bytes from state to avoid memory bloat
        "fetched_documents": [
            {k: v for k, v in doc.items() if k != "content_bytes"} for doc in fetched
        ],
    }

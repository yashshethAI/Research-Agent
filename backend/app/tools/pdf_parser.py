from __future__ import annotations

import re
from typing import Any

import pymupdf


class PDFParser:
    """Extracts text and metadata from official GST notifications, circulars, and orders in PDF."""

    @staticmethod
    def parse_pdf_bytes(pdf_bytes: bytes) -> dict[str, Any]:
        if not pdf_bytes:
            return {"title": "", "text": "", "page_count": 0, "pages": []}

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        meta = doc.metadata or {}
        title = meta.get("title") or ""

        pages: list[dict[str, Any]] = []
        full_text_chunks: list[str] = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_text = page.get_text("text") or ""
            # Normalize whitespace
            cleaned_page = re.sub(r"[ \t]+", " ", page_text).strip()
            pages.append({
                "page_number": page_idx + 1,
                "text": cleaned_page,
            })
            full_text_chunks.append(f"\n--- [Page {page_idx + 1}] ---\n{cleaned_page}")

        full_text = "\n".join(full_text_chunks).strip()

        return {
            "title": title,
            "page_count": len(doc),
            "text": full_text,
            "pages": pages,
            "metadata": {
                "author": meta.get("author", ""),
                "creation_date": meta.get("creationDate", ""),
                "producer": meta.get("producer", ""),
            },
        }

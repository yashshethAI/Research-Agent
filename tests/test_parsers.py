from __future__ import annotations

import pymupdf

from backend.app.storage.source_cache import source_cache_storage
from backend.app.tools.html_parser import HTMLParser
from backend.app.tools.pdf_parser import PDFParser


def test_html_parser_removes_scripts_and_extracts_content():
    raw_html = """
    <html>
        <head><title>Central Goods and Services Tax Act - Section 16</title></head>
        <body>
            <script>alert('malicious script');</script>
            <style>body { color: red; }</style>
            <nav><a href="/home">Home</a></nav>
            <h1>Section 16: Eligibility for Input Tax Credit</h1>
            <p>Every registered person shall be entitled to take credit of input tax.</p>
            <table>
                <tr><th>Sub-section</th><th>Provision</th></tr>
                <tr><td>(1)</td><td>Conditions</td></tr>
            </table>
        </body>
    </html>
    """
    parsed = HTMLParser.parse_html(raw_html)
    assert parsed["title"] == "Central Goods and Services Tax Act - Section 16"
    assert "malicious script" not in parsed["text"]
    assert "Section 16: Eligibility for Input Tax Credit" in parsed["text"]
    assert "Every registered person shall be entitled" in parsed["text"]
    assert parsed["table_count"] == 1


def test_pdf_parser_with_in_memory_pdf():
    # Create an in-memory PDF using pymupdf
    doc = pymupdf.open()
    page1 = doc.new_page()
    page1.insert_text((50, 72), "Circular No. 211/5/2024-GST - Central Board of Indirect Taxes")
    page2 = doc.new_page()
    page2.insert_text((50, 72), "Section 16(5) provides retrospective relaxation up to 30th November 2021.")
    pdf_bytes = doc.tobytes()
    doc.close()

    parsed = PDFParser.parse_pdf_bytes(pdf_bytes)
    assert parsed["page_count"] == 2
    assert "Circular No. 211/5/2024-GST" in parsed["text"]
    assert "retrospective relaxation" in parsed["text"]
    assert len(parsed["pages"]) == 2

    # Check sha256 calculation
    sha = source_cache_storage.compute_hash(pdf_bytes)
    assert len(sha) == 64

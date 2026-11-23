from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag


class HTMLParser:
    """Extracts statutory and legal text from official government HTML web pages."""

    @staticmethod
    def parse_html(html_content: str, base_url: str = "") -> dict[str, Any]:
        if not html_content:
            return {"title": "", "text": "", "tables": []}

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Extract title
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # 2. Decompose non-content elements
        for element in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe"]):
            element.decompose()

        # 3. Extract and format tables
        extracted_tables = []
        for table in soup.find_all("table"):
            table_rows = []
            for tr in table.find_all("tr"):
                cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
                if cells:
                    table_rows.append(cells)
            if table_rows:
                extracted_tables.append(table_rows)

        # 4. Extract body text preserving structure
        body = soup.find("body") or soup
        text_lines = []
        for child in body.descendants:
            if isinstance(child, Tag):
                if child.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                    heading_text = child.get_text(strip=True)
                    if heading_text:
                        text_lines.append(f"\n\n### {heading_text}\n")
                elif child.name in ["p", "li", "tr"]:
                    p_text = child.get_text(strip=True)
                    if p_text:
                        text_lines.append(p_text)

        raw_text = "\n".join(text_lines) if text_lines else body.get_text(separator="\n", strip=True)

        # Normalize multiple line breaks
        cleaned_text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()

        return {
            "title": title,
            "text": cleaned_text,
            "table_count": len(extracted_tables),
            "tables": extracted_tables,
        }

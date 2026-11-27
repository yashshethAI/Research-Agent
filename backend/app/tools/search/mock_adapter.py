from __future__ import annotations

from backend.app.tools.search.base import (
    BaseSearchProvider,
    SearchResult,
    sanitize_search_query,
)


class MockSearchAdapter(BaseSearchProvider):
    """Deterministic tier-aware mock search adapter for offline testing."""

    SAMPLE_DATA = [
        {
            "query_keywords": ["16(4)", "itc", "time limit", "retrospective", "16(5)", "16(6)"],
            "title": "Section 16 of CGST Act, 2017 - Eligibility and Conditions for Taking Input Tax Credit",
            "url": "https://taxinformation.cbic.gov.in/content-page/guidelines/cgst-act-sec-16",
            "snippet": "Section 16(4) mandates that a registered person shall not be entitled to take input tax credit in respect of any invoice or debit note after 30th November following the end of financial year. Finance (No. 2) Act, 2024 inserted sub-sections (5) and (6) providing retrospective relief for FY 2017-18 to 2020-21.",
            "domain": "taxinformation.cbic.gov.in",
        },
        {
            "query_keywords": ["circular 211", "itc", "amendment", "special procedure", "16(5)"],
            "title": "Circular No. 211/5/2024-GST - Clarification on time limit under Section 16(4)",
            "url": "https://www.cbic.gov.in/resources//htdocs-cbec/gst/circular-211-05-2024-gst.pdf",
            "snippet": "Circular clarifies the application of newly inserted Section 16(5) and 16(6) of the CGST Act, 2017 retrospectively extending the time limit to avail ITC for financial years 2017-18, 2018-19, 2019-20, and 2020-21 up to 30th November 2021.",
            "domain": "www.cbic.gov.in",
        },
        {
            "query_keywords": ["rcm", "reverse charge", "director", "remuneration", "circular 140"],
            "title": "Circular No. 140/10/2020-GST - GST on Director's Remuneration",
            "url": "https://www.cbic.gov.in/resources//htdocs-cbec/gst/circular-140-10-2020-gst.pdf",
            "snippet": "Clarification on leviability of GST on remuneration paid by companies to independent directors and whole-time directors under Entry 6 of Notification No. 13/2017-Central Tax (Rate).",
            "domain": "www.cbic.gov.in",
        },
        {
            "query_keywords": ["notification 13/2017", "reverse charge", "services"],
            "title": "Notification No. 13/2017-Central Tax (Rate) - Reverse Charge on Services",
            "url": "https://taxinformation.cbic.gov.in/content-page/guidelines/notfn-13-2017-ct-rate",
            "snippet": "Notification specifying categories of services the tax on which shall be paid on reverse charge basis by the recipient under section 9(3) of the CGST Act, 2017.",
            "domain": "taxinformation.cbic.gov.in",
        },
        {
            "query_keywords": ["place of supply", "igst", "section 10", "section 12", "section 13"],
            "title": "IGST Act, 2017 - Sections 10, 12 and 13 - Determination of Place of Supply",
            "url": "https://taxinformation.cbic.gov.in/content-page/guidelines/igst-act-sec-10",
            "snippet": "Provisions governing place of supply of goods and cross-border services under Sections 10, 12, and 13 of the IGST Act, 2017.",
            "domain": "taxinformation.cbic.gov.in",
        },
        {
            "query_keywords": ["corporate guarantee", "valuation", "taxmann", "rule 28", "secondary"],
            "title": "Taxmann Analysis: Valuation of Corporate Guarantee under Rule 28(2) CGST Rules",
            "url": "https://www.taxmann.com/post/blog/corporate-guarantee-gst-rule-28-2",
            "snippet": "Detailed commentary on GST valuation of corporate guarantees between related persons under Rule 28(2) and CBIC clarifications.",
            "domain": "www.taxmann.com",
        },
        {
            "query_keywords": ["livelaw", "writ", "high court", "itc", "16(4)"],
            "title": "LiveLaw: High Court Upholds Retrospective Relief under Section 16(5) CGST Act",
            "url": "https://www.livelaw.in/tax-cases/gst-section-16-5-retrospective-relief",
            "snippet": "High Court ruling examining constitutional validity and retrospective operation of Section 16(5) of the CGST Act.",
            "domain": "www.livelaw.in",
        },
    ]

    @staticmethod
    def _domain_allowed(domain: str, domains: list[str] | None) -> bool:
        if not domains:
            return True
        d = domain.lower()
        return any(d == allowed.lower() or d.endswith("." + allowed.lower()) for allowed in domains)

    async def search(
        self,
        query: str,
        domains: list[str] | None = None,
        max_results: int = 10,
        time_range: str | None = None,
    ) -> list[SearchResult]:
        sanitized = sanitize_search_query(query).lower()
        results: list[SearchResult] = []

        for item in self.SAMPLE_DATA:
            if not self._domain_allowed(item["domain"], domains):
                continue
            matches = any(k in sanitized for k in item["query_keywords"])
            if matches:
                results.append(
                    SearchResult(
                        title=item["title"],
                        url=item["url"],
                        snippet=item["snippet"],
                        domain=item["domain"],
                        score=1.0,
                    )
                )

        if not results:
            for item in self.SAMPLE_DATA:
                if self._domain_allowed(item["domain"], domains):
                    results.append(
                        SearchResult(
                            title=item["title"],
                            url=item["url"],
                            snippet=item["snippet"],
                            domain=item["domain"],
                            score=0.8,
                        )
                    )
                    break

        return results[:max_results]

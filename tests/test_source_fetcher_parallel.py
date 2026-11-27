from __future__ import annotations

import pytest

from backend.app.agents.nodes.retrieve_evidence import retrieve_evidence_node
from backend.app.agents.state import ResearchState
from backend.app.core.config import settings
from backend.app.tools.fetcher import FetchedDocument, safe_fetcher
from backend.app.tools.search.base import SearchResult
from backend.app.tools.search.searxng_adapter import SearXNGSearchAdapter
from backend.app.tools.source_validator import source_validator


@pytest.mark.asyncio
async def test_source_fetcher_parallel_success(monkeypatch):
    """Verify retrieve_evidence fetches up to MAX_FETCH_SOURCES URLs concurrently."""
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")
    fetched_urls: list[str] = []

    async def mock_search(self, query, domains=None, max_results=10, time_range=None):
        return [
            SearchResult(
                title=f"Section 16 Doc {i}",
                url=f"https://taxinformation.cbic.gov.in/sec{i}",
                snippet=f"Section 16 statutory snippet {i}",
                domain="taxinformation.cbic.gov.in",
                score=5.0,
            )
            for i in range(1, 10)
        ]

    async def mock_fetch(url: str, allow_unverified: bool = False):
        fetched_urls.append(url)
        return FetchedDocument(
            url=url,
            content=b"<html><body><h1>Section 16</h1><p>Statutory input tax credit provision under CGST Act 2017.</p></body></html>",
            content_type="text/html",
            status_code=200,
            sha256_hash="mockhash123456789",
            file_path="",
        )

    monkeypatch.setattr(SearXNGSearchAdapter, "search", mock_search)
    monkeypatch.setattr(source_validator, "validate_url", lambda url, allow_unverified=False: (True, "ok"))
    monkeypatch.setattr(safe_fetcher, "fetch", mock_fetch)

    state = ResearchState(query="Section 16 ITC", search_queries=["Section 16 CGST Act"])
    result = await retrieve_evidence_node(state)
    assert result["current_step"] == "retrieve_evidence"
    assert len(fetched_urls) == settings.MAX_FETCH_SOURCES
    assert len(result["evidence_records"]) == settings.MAX_FETCH_SOURCES


@pytest.mark.asyncio
async def test_source_fetcher_partial_failure_records_node_error_and_snippet(monkeypatch):
    """Verify failed URL falls back to snippet, sets verified=False, and logs pinpoint node_error."""
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")

    async def mock_search(self, query, domains=None, max_results=10, time_range=None):
        return [
            SearchResult(
                title="Good CBIC Page",
                url="https://taxinformation.cbic.gov.in/good",
                snippet="Good official snippet",
                domain="taxinformation.cbic.gov.in",
                score=6.0,
            ),
            SearchResult(
                title="Slow CBIC Page",
                url="https://taxinformation.cbic.gov.in/fail",
                snippet="Fallback snippet for failed URL",
                domain="taxinformation.cbic.gov.in",
                score=5.0,
            ),
        ]

    async def mock_fetch(url: str, allow_unverified: bool = False):
        if "fail" in url:
            raise TimeoutError("Connection to slow government portal timed out")
        return FetchedDocument(
            url=url,
            content=b"<html><body><h1>Section 16</h1><p>Good official content on Section 16 CGST Act.</p></body></html>",
            content_type="text/html",
            status_code=200,
            sha256_hash="goodhash123",
            file_path="",
        )

    monkeypatch.setattr(SearXNGSearchAdapter, "search", mock_search)
    monkeypatch.setattr(source_validator, "validate_url", lambda url, allow_unverified=False: (True, "ok"))
    monkeypatch.setattr(safe_fetcher, "fetch", mock_fetch)

    state = ResearchState(query="Section 16", search_queries=["Section 16 CGST Act"])
    result = await retrieve_evidence_node(state)
    records = result["evidence_records"]
    assert len(records) == 2

    good_rec = next(r for r in records if r["url"].endswith("/good"))
    fail_rec = next(r for r in records if r["url"].endswith("/fail"))

    assert good_rec["fetch_status"] == "fetched"
    assert good_rec["verified"] is True
    assert fail_rec["fetch_status"] == "snippet_only"
    assert fail_rec["verified"] is False
    assert "Fallback snippet" in fail_rec["excerpt"]
    assert any(err["substep"] == "fetch" and err["error_type"] == "TimeoutError" for err in result["node_errors"])


@pytest.mark.asyncio
async def test_spa_shell_triggers_playwright_fallback_for_tier1(monkeypatch):
    """Verify detect_spa_shell() triggers safe_fetcher.fetch_rendered_html() and upgrades status to fetched."""
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")
    playwright_called: list[str] = []

    async def mock_search(self, query, domains=None, max_results=10, time_range=None):
        return [
            SearchResult(
                title="CBIC Portal SPA",
                url="https://taxinformation.cbic.gov.in/spa-page",
                snippet="Short SPA snippet",
                domain="taxinformation.cbic.gov.in",
                score=7.0,
            )
        ]

    async def mock_fetch(url: str, allow_unverified: bool = False):
        return FetchedDocument(
            url=url,
            content=b"<html><body><app-root></app-root>Loading...</body></html>",
            content_type="text/html",
            status_code=200,
            sha256_hash="spahash123",
            file_path="",
        )

    async def mock_fetch_rendered_html(url: str):
        playwright_called.append(url)
        rendered_body = (
            "<html><head><title>CBIC Notification 12/2025</title></head><body><main>"
            "<h1>Notification No. 12/2025-Central Tax</h1>"
            "<p>The Central Board of Indirect Taxes and Customs hereby notifies the due date extension "
            "for furnishing annual return in FORM GSTR-9 and reconciliation statement in FORM GSTR-9C "
            "for the financial year 2025-26 under Section 44 of the CGST Act, 2017.</p>"
            "</main></body></html>"
        ).encode("utf-8")
        return FetchedDocument(
            url=url,
            content=rendered_body,
            content_type="text/html",
            status_code=200,
            sha256_hash="renderedhash456",
            file_path="",
        )

    monkeypatch.setattr(SearXNGSearchAdapter, "search", mock_search)
    monkeypatch.setattr(source_validator, "validate_url", lambda url, allow_unverified=False: (True, "ok"))
    monkeypatch.setattr(safe_fetcher, "fetch", mock_fetch)
    monkeypatch.setattr(safe_fetcher, "fetch_rendered_html", mock_fetch_rendered_html)

    state = ResearchState(query="GSTR-9 due date", search_queries=["GSTR-9 due date"], search_tier="official")
    result = await retrieve_evidence_node(state)

    assert playwright_called == ["https://taxinformation.cbic.gov.in/spa-page"]
    assert len(result["evidence_records"]) == 1
    rec = result["evidence_records"][0]
    assert rec["fetch_status"] == "fetched"
    assert rec["verified"] is True
    assert "GSTR-9C" in rec["excerpt"]

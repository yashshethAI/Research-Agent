from __future__ import annotations

import httpx
import pytest

from backend.app.agents.nodes.citation_validator import citation_validator_node
from backend.app.agents.nodes.official_source_search import official_source_search_node
from backend.app.agents.state import ResearchState
from backend.app.core.config import settings
from backend.app.tools.search.base import SearchNotConfiguredError, SearchResult
from backend.app.tools.search.searxng_adapter import SearXNGSearchAdapter
from backend.app.tools.source_validator import source_validator


class _FakeAsyncClient:
    """Minimal async httpx client stub capturing GET calls."""

    def __init__(self, handler, **kwargs):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, params=None, headers=None):
        return self._handler(url, params or {}, headers or {})


@pytest.mark.asyncio
async def test_searxng_raises_when_base_url_empty():
    adapter = SearXNGSearchAdapter(base_url="")
    with pytest.raises(SearchNotConfiguredError):
        await adapter.search("Section 16(4) CGST Act")


@pytest.mark.asyncio
async def test_searxng_search_parses_results_and_sanitizes_pii(monkeypatch):
    captured_calls: list[tuple[str, dict]] = []

    def handler(url, params, headers):
        captured_calls.append((url, params))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Section 16 CGST Act",
                        "url": "https://taxinformation.cbic.gov.in/sec16.html",
                        "content": "Eligibility and conditions for taking ITC.",
                        "score": 4.0,
                    },
                    {
                        "title": "Circular 211/5/2024-GST",
                        "url": "https://www.cbic.gov.in/circular-211.pdf",
                        "content": "Retrospective relief under Section 16(5).",
                        "score": 6.5,
                    },
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))

    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080/", engines="google,duckduckgo")
    results = await adapter.search(
        query="ITC claim for 27AABCU9603R1ZN site:taxinformation.cbic.gov.in",
        domains=["taxinformation.cbic.gov.in", "cbic.gov.in"],
        max_results=5,
        time_range="year",
    )

    assert len(captured_calls) == 1
    req_url, req_params = captured_calls[0]
    assert req_url == "http://localhost:8080/search"
    assert req_params["format"] == "json"
    assert req_params["time_range"] == "year"
    assert req_params["engines"] == "google,duckduckgo"
    assert "[REDACTED_GSTIN]" in req_params["q"]
    assert "27AABCU9603R1ZN" not in req_params["q"]
    # Existing site: clause preserved without appending duplicate OR clauses
    assert req_params["q"].count("site:") == 1

    # Results sorted by score descending
    assert len(results) == 2
    assert results[0].url == "https://www.cbic.gov.in/circular-211.pdf"
    assert results[0].domain == "www.cbic.gov.in"
    assert results[0].score == 6.5
    assert results[1].snippet == "Eligibility and conditions for taking ITC."


@pytest.mark.asyncio
async def test_searxng_injects_site_clauses_when_missing(monkeypatch):
    captured_queries: list[str] = []

    def handler(url, params, headers):
        captured_queries.append(params["q"])
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))

    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080")
    await adapter.search(
        query="Section 16(4) judgment",
        domains=["sci.gov.in", "www.sci.gov.in", "indiankanoon.org"],
        time_range="invalid_range",
    )

    assert len(captured_queries) == 1
    q = captured_queries[0]
    assert "(site:sci.gov.in OR site:indiankanoon.org)" in q
    assert "www.sci.gov.in" not in q


@pytest.mark.asyncio
async def test_searxng_chunks_full_allowed_domains_and_deduplicates(monkeypatch):
    captured_queries: list[str] = []

    def handler(url, params, headers):
        captured_queries.append(params["q"])
        if "taxinformation.cbic.gov.in" in params["q"]:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "CBIC Sec 16",
                            "url": "https://taxinformation.cbic.gov.in/sec16",
                            "content": "Statutory text",
                            "score": 3.0,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "CBIC Sec 16 Duplicate",
                        "url": "https://taxinformation.cbic.gov.in/sec16",
                        "content": "Statutory text",
                        "score": 5.0,
                    },
                    {
                        "title": "Taxmann Ruling",
                        "url": "https://www.taxmann.com/post/gst-ruling",
                        "content": "High Court ruling",
                        "score": 4.0,
                    },
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))

    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080")
    results = await adapter.search(query="ITC judgment", domains=settings.allowed_domains, max_results=10)

    # Full allowlist split into 2 compact priority domain groups
    assert len(captured_queries) == 2
    assert len(results) == 2
    assert results[0].url == "https://taxinformation.cbic.gov.in/sec16"
    assert results[0].score == 5.0
    assert results[1].url == "https://www.taxmann.com/post/gst-ruling"


@pytest.mark.asyncio
async def test_searxng_error_handling_http_403_and_connect_error(monkeypatch):
    def handler_403(url, params, headers):
        return httpx.Response(403, text="Forbidden")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler_403, **kwargs))
    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080")
    with pytest.raises(RuntimeError, match="403 Forbidden"):
        await adapter.search("CGST Section 16")

    def handler_conn_err(url, params, headers):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler_conn_err, **kwargs))
    with pytest.raises(RuntimeError, match="Failed to reach SearXNG"):
        await adapter.search("CGST Section 16")


@pytest.mark.asyncio
async def test_searxng_health_check_variants(monkeypatch):
    def handler_config_ok(url, params, headers):
        return httpx.Response(200, json={"instance_name": "LocalSearXNG", "version": "2026.1"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler_config_ok, **kwargs))
    ok, msg = await SearXNGSearchAdapter(base_url="http://localhost:8080").health_check()
    assert ok is True
    assert "LocalSearXNG" in msg

    def handler_healthz_fallback(url, params, headers):
        if url.endswith("/config"):
            return httpx.Response(404, text="Not Found")
        return httpx.Response(200, text="OK")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler_healthz_fallback, **kwargs))
    ok2, msg2 = await SearXNGSearchAdapter(base_url="http://localhost:8080").health_check()
    assert ok2 is True
    assert "reachable" in msg2

    ok_empty, msg_empty = await SearXNGSearchAdapter(base_url="").health_check()
    assert ok_empty is False
    assert "not configured" in msg_empty


@pytest.mark.asyncio
async def test_official_source_search_node_uses_searxng_and_filters_domains(monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")

    async def mock_search(self, query, domains=None, max_results=10, time_range=None):
        return [
            SearchResult(
                title="Official CBIC",
                url="https://taxinformation.cbic.gov.in/sec16",
                snippet="Official text",
                domain="taxinformation.cbic.gov.in",
                score=5.0,
            ),
            SearchResult(
                title="Unofficial Blog",
                url="https://randomblog.example.com/gst-post",
                snippet="Blog text",
                domain="randomblog.example.com",
                score=8.0,
            ),
        ]

    monkeypatch.setattr(SearXNGSearchAdapter, "search", mock_search)
    monkeypatch.setattr(
        source_validator,
        "validate_url",
        lambda url: ("taxinformation.cbic.gov.in" in url, "mock validation"),
    )

    state = ResearchState(
        query="Latest Section 16(4) amendment",
        search_queries=["Section 16(4) CGST Act"],
    )
    out = await official_source_search_node(state)
    assert out["current_step"] == "official_source_search"
    assert len(out["search_results"]) == 1
    assert out["search_results"][0]["url"] == "https://taxinformation.cbic.gov.in/sec16"


@pytest.mark.asyncio
async def test_citation_validator_triggers_retry_for_searxng(monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")

    state = ResearchState(evidence_records=[], retry_count=0)
    out = await citation_validator_node(state)
    assert out["should_refine_search"] is True
    assert out["retry_count"] == 1

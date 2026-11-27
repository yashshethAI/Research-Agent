from __future__ import annotations

import httpx
import pytest

from backend.app.agents.nodes.retrieve_evidence import retrieve_evidence_node
from backend.app.agents.state import ResearchState
from backend.app.core.config import settings
from backend.app.tools.fetcher import FetchedDocument, safe_fetcher
from backend.app.tools.search.base import SearchNotConfiguredError, SearchResult
from backend.app.tools.search.searxng_adapter import SearXNGSearchAdapter, _result_cache
from backend.app.tools.source_validator import source_validator


@pytest.fixture(autouse=True)
def _clear_searxng_cache():
    _result_cache.clear()
    yield
    _result_cache.clear()


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
    assert req_params["q"].count("site:") == 1

    assert len(results) == 2
    assert results[0].url == "https://www.cbic.gov.in/circular-211.pdf"
    assert results[0].domain == "www.cbic.gov.in"
    assert results[0].score == 6.5
    assert results[1].snippet == "Eligibility and conditions for taking ITC."


@pytest.mark.asyncio
async def test_searxng_injects_site_clauses_when_enabled(monkeypatch):
    captured_queries: list[str] = []

    def handler(url, params, headers):
        captured_queries.append(params["q"])
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))

    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080", use_site_operators=True)
    await adapter.search(
        query="Section 16(4) judgment",
        domains=["sci.gov.in", "www.sci.gov.in", "gstat.gov.in"],
        time_range="invalid_range",
    )

    assert len(captured_queries) == 1
    q = captured_queries[0]
    assert "(site:sci.gov.in OR site:gstat.gov.in)" in q
    assert "www.sci.gov.in" not in q


@pytest.mark.asyncio
async def test_searxng_skips_site_clauses_by_default(monkeypatch):
    captured_queries: list[str] = []

    def handler(url, params, headers):
        captured_queries.append(params["q"])
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))

    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080", use_site_operators=False)
    await adapter.search(
        query="GSTR-9C due date FY 2025-26",
        domains=settings.official_domains,
    )

    assert captured_queries == ["GSTR-9C due date FY 2025-26"]
    assert "site:" not in captured_queries[0]


@pytest.mark.asyncio
async def test_searxng_chunks_tier1_domains_and_deduplicates(monkeypatch):
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
                        "title": "India Code CGST Act",
                        "url": "https://www.indiacode.nic.in/handle/cgst",
                        "content": "Bare Act text",
                        "score": 4.0,
                    },
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))

    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080", use_site_operators=True)
    results = await adapter.search(query="ITC judgment", domains=settings.official_domains, max_results=10)

    assert len(captured_queries) == 2
    assert len(results) == 2
    assert results[0].url == "https://taxinformation.cbic.gov.in/sec16"
    assert results[0].score == 5.0
    assert results[1].url == "https://www.indiacode.nic.in/handle/cgst"


@pytest.mark.asyncio
async def test_searxng_sequential_chunk_skips_group2_when_group1_has_5_hits(monkeypatch):
    captured_queries: list[str] = []

    def handler(url, params, headers):
        captured_queries.append(params["q"])
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": f"Doc {i}",
                        "url": f"https://taxinformation.cbic.gov.in/doc-{i}",
                        "content": "Statutory text",
                        "score": float(i),
                    }
                    for i in range(1, 6)
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))

    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080", use_site_operators=True)
    results = await adapter.search(query="ITC judgment", domains=settings.official_domains, max_results=10)

    assert len(captured_queries) == 1
    assert len(results) == 5


@pytest.mark.asyncio
async def test_searxng_ttl_cache_deduplicates_identical_queries(monkeypatch):
    call_count = 0

    def handler(url, params, headers):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "CBIC Notice",
                        "url": "https://www.cbic.gov.in/notice.pdf",
                        "content": "Due date extension",
                        "score": 5.0,
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))
    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080", use_site_operators=False)

    res1 = await adapter.search("GSTR-9C due date", time_range="year")
    res2 = await adapter.search("GSTR-9C due date", time_range="year")
    assert call_count == 1
    assert len(res1) == 1 and len(res2) == 1
    assert res1[0].url == res2[0].url


@pytest.mark.asyncio
async def test_searxng_open_web_fallback_runs_without_site_clause(monkeypatch):
    captured_queries: list[str] = []

    def handler(url, params, headers):
        captured_queries.append(params["q"])
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler, **kwargs))

    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080")
    await adapter.search(query="Section 16(5) retrospective ITC", domains=[])

    assert captured_queries == ["Section 16(5) retrospective ITC"]


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
async def test_retrieve_evidence_tier1_filters_domains_and_respects_time_range(monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")
    captured_time_ranges: list[str | None] = []

    async def mock_search(self, query, domains=None, max_results=10, time_range=None):
        captured_time_ranges.append(time_range)
        return [
            SearchResult(
                title="Official CBIC",
                url="https://taxinformation.cbic.gov.in/sec16",
                snippet="Section 16(4) official text",
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

    async def mock_fetch(url: str, allow_unverified: bool = False):
        return FetchedDocument(
            url=url,
            content=b"<html><body><h1>Section 16(4) CGST Act</h1><p>Eligibility conditions for input tax credit under Section 16(4) and Section 16(5) retrospective relief.</p></body></html>",
            content_type="text/html",
            status_code=200,
            sha256_hash="hash123456",
            file_path="",
        )

    monkeypatch.setattr(SearXNGSearchAdapter, "search", mock_search)
    monkeypatch.setattr(
        source_validator,
        "validate_url",
        lambda url, allow_unverified=False: ("taxinformation.cbic.gov.in" in url, "mock validation"),
    )
    monkeypatch.setattr(safe_fetcher, "fetch", mock_fetch)

    state = ResearchState(
        query="Current Section 16(4) amendment",
        search_queries=["Section 16(4) CGST Act"],
        search_tier="official",
        search_time_range=None,
    )
    out = await retrieve_evidence_node(state)
    assert out["current_step"] == "retrieve_evidence"
    # No blind time_range="year" on "Current" / "amendment"
    assert captured_time_ranges == [None]
    assert len(out["evidence_records"]) == 1
    assert out["evidence_records"][0]["url"] == "https://taxinformation.cbic.gov.in/sec16"
    assert out["evidence_records"][0]["source_tier"] == "official"


@pytest.mark.asyncio
async def test_retrieve_evidence_escalates_tier1_to_tier2_and_tier3(monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")
    monkeypatch.setattr(settings, "ALLOW_UNVERIFIED_FALLBACK", True)

    async def mock_empty_search(self, query, domains=None, max_results=10, time_range=None):
        return []

    monkeypatch.setattr(SearXNGSearchAdapter, "search", mock_empty_search)

    # Pass 1: official -> escalates to verified_secondary
    state1 = ResearchState(query="Corporate guarantee valuation", search_queries=["corporate guarantee rule 28(2)"], search_tier="official", retry_count=0)
    out1 = await retrieve_evidence_node(state1)
    assert out1["should_refine_search"] is True
    assert out1["search_tier"] == "verified_secondary"
    assert out1["retry_count"] == 1

    # Pass 2: verified_secondary -> escalates to unverified_fallback because ALLOW_UNVERIFIED_FALLBACK=True
    state2 = ResearchState(
        query="Corporate guarantee valuation",
        search_queries=out1["search_queries"],
        search_tier=out1["search_tier"],
        retry_count=out1["retry_count"],
        attempted_tiers=out1["attempted_tiers"],
    )
    out2 = await retrieve_evidence_node(state2)
    assert out2["should_refine_search"] is True
    assert out2["search_tier"] == "unverified_fallback"
    assert out2["retry_count"] == 2

    # When ALLOW_UNVERIFIED_FALLBACK is False, stops after verified_secondary
    monkeypatch.setattr(settings, "ALLOW_UNVERIFIED_FALLBACK", False)
    out2_disabled = await retrieve_evidence_node(state2)
    assert out2_disabled["should_refine_search"] is False


@pytest.mark.asyncio
async def test_searxng_detects_unresponsive_rate_limit_engines(monkeypatch):
    def handler_rate_limited(url, params, headers):
        return httpx.Response(
            200,
            json={
                "results": [],
                "unresponsive_engines": [["duckduckgo", "CAPTCHA"], ["google cse", "Suspended: too many requests"]],
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(handler_rate_limited, **kwargs))
    adapter = SearXNGSearchAdapter(base_url="http://localhost:8080")
    with pytest.raises(RuntimeError, match="blocked/rate-limited"):
        await adapter.search("corporate guarantee GST")

    # Verify retrieve_evidence records SearchEngineRateLimitError cleanly in node_errors and halts pointless tier loop
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")
    state = ResearchState(query="corporate guarantee GST", search_queries=["corporate guarantee rule 28(2)"], search_tier="official")
    out = await retrieve_evidence_node(state)
    assert out["should_refine_search"] is False
    assert any(err["error_type"] == "SearchEngineRateLimitError" for err in out["node_errors"])


@pytest.mark.asyncio
async def test_retrieve_evidence_reuses_pool_on_tier_escalation(monkeypatch):
    """Verify Tier 2 escalation promotes pre-discovered Tier 2 URLs from state.search_results."""
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "SEARXNG_BASE_URL", "http://localhost:8080")
    search_calls: list[str] = []

    async def mock_search(self, query, domains=None, max_results=10, time_range=None):
        search_calls.append(query)
        return []

    async def mock_fetch(url: str, allow_unverified: bool = False):
        return FetchedDocument(
            url=url,
            content=b"<html><body><h1>Rule 28(2) Corporate Guarantee</h1><p>Taxmann analysis of Rule 28(2) CGST Rules and Circular 225/19/2024-GST.</p></body></html>",
            content_type="text/html",
            status_code=200,
            sha256_hash="poolhash123",
            file_path="",
        )

    monkeypatch.setattr(SearXNGSearchAdapter, "search", mock_search)
    monkeypatch.setattr(source_validator, "validate_url", lambda url, allow_unverified=False: (True, "ok"))
    monkeypatch.setattr(safe_fetcher, "fetch", mock_fetch)

    # Simulate Tier 1 already stored a Tier 2 Taxmann URL in state.search_results
    state = ResearchState(
        query="Corporate guarantee Rule 28(2)",
        search_queries=["corporate guarantee rule 28(2)"],
        search_tier="verified_secondary",
        retry_count=1,
        search_results=[
            {
                "title": "Taxmann Rule 28(2) Analysis",
                "url": "https://www.taxmann.com/post/rule-28-2-corporate-guarantee",
                "snippet": "Rule 28(2) valuation analysis",
                "domain": "www.taxmann.com",
                "score": 6.0,
                "source_tier": "verified_secondary",
            }
        ],
    )
    out = await retrieve_evidence_node(state)
    assert len(out["evidence_records"]) >= 1
    assert any("taxmann.com" in r["url"] for r in out["evidence_records"])

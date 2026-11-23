from __future__ import annotations

import pytest

from backend.app.agents.nodes.source_fetcher import source_fetcher_node
from backend.app.agents.state import ResearchState
from backend.app.tools.fetcher import FetchedDocument, safe_fetcher


@pytest.mark.asyncio
async def test_source_fetcher_parallel_success(monkeypatch):
    """Verify source_fetcher_node fetches multiple candidate URLs concurrently."""
    fetched_urls = []

    async def mock_fetch(url: str):
        fetched_urls.append(url)
        return FetchedDocument(
            url=url,
            content=b"Sample content",
            content_type="text/html",
            status_code=200,
            sha256_hash="mockhash123456789",
            file_path="/mock/path.html",
        )

    monkeypatch.setattr(safe_fetcher, "fetch", mock_fetch)

    state = ResearchState(
        search_results=[
            {"url": f"https://taxinformation.cbic.gov.in/sec{i}", "snippet": f"Snippet {i}"}
            for i in range(1, 10)
        ]
    )

    result = await source_fetcher_node(state)
    assert result["current_step"] == "source_fetcher"
    # Should fetch up to MAX_FETCH_SOURCES (default 8)
    assert len(fetched_urls) == 8
    assert len(result["fetched_documents"]) == 8


@pytest.mark.asyncio
async def test_source_fetcher_partial_failure_with_snippet_fallback(monkeypatch):
    """Verify that if one URL times out, source_fetcher_node falls back to its search snippet."""
    async def mock_fetch(url: str):
        if "fail" in url:
            raise TimeoutError("Connection to slow government portal timed out")
        return FetchedDocument(
            url=url,
            content=b"Good content",
            content_type="text/html",
            status_code=200,
            sha256_hash="goodhash123",
            file_path="/mock/good.html",
        )

    monkeypatch.setattr(safe_fetcher, "fetch", mock_fetch)

    state = ResearchState(
        search_results=[
            {"url": "https://taxinformation.cbic.gov.in/good", "snippet": "Good official snippet"},
            {"url": "https://taxinformation.cbic.gov.in/fail", "snippet": "Fallback snippet for failed URL"},
        ]
    )

    result = await source_fetcher_node(state)
    docs = result["fetched_documents"]
    assert len(docs) == 2

    # First doc is successfully fetched
    assert docs[0]["url"] == "https://taxinformation.cbic.gov.in/good"
    assert docs[0]["content_bytes"] == b"Good content"

    # Second doc used search snippet fallback
    assert docs[1]["url"] == "https://taxinformation.cbic.gov.in/fail"
    assert docs[1]["content_bytes"] == b"Fallback snippet for failed URL"

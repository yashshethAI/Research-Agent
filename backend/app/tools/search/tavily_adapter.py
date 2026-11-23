from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.app.core.config import settings
from backend.app.tools.search.base import (
    BaseSearchProvider,
    SearchNotConfiguredError,
    SearchResult,
    sanitize_search_query,
)

logger = logging.getLogger(__name__)


class TavilySearchAdapter(BaseSearchProvider):
    """Tavily search provider adapter restricted to official Indian GST legal domains."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.TAVILY_API_KEY
        self.api_url = "https://api.tavily.com/search"

    async def search(
        self,
        query: str,
        domains: list[str] | None = None,
        max_results: int = 10,
        time_range: str | None = None,
    ) -> list[SearchResult]:
        if not self.api_key or not self.api_key.strip():
            raise SearchNotConfiguredError(
                "Tavily search API key is not configured. "
                "Please configure TAVILY_API_KEY in your .env file to enable live official search."
            )

        sanitized_query = sanitize_search_query(query)
        allowed_domains = domains or settings.allowed_domains

        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": sanitized_query,
            "search_depth": "advanced",
            "include_answer": False,
            "include_raw_content": False,
            "max_results": max_results,
            "include_domains": allowed_domains if allowed_domains else None,
        }
        if time_range:
            payload["time_range"] = time_range

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.api_url, json=payload)
            if resp.status_code != 200:
                logger.error(f"Tavily search error: HTTP {resp.status_code} - {resp.text}")
                raise RuntimeError(f"Tavily API returned HTTP {resp.status_code}: {resp.text}")

            data = resp.json()
            raw_results = data.get("results", [])

            results: list[SearchResult] = []
            for item in raw_results:
                url = item.get("url", "")
                domain = urlparse(url).hostname or ""
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=url,
                        snippet=item.get("content", ""),
                        domain=domain,
                        score=float(item.get("score", 1.0)),
                    )
                )

            return results

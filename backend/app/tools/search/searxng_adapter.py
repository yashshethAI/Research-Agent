from __future__ import annotations

import asyncio
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

_VALID_TIME_RANGES = {"day", "week", "month", "year"}
_DEFAULT_SINGLE_GROUP_LIMIT = 8
_CHUNK_SIZE = 6
_MAX_DOMAIN_GROUPS = 2


def _dedupe_www_domains(domains: list[str]) -> list[str]:
    """Deduplicates domains, dropping 'www.<root>' when '<root>' is also present."""
    cleaned = [d.strip().lower() for d in domains if d and d.strip()]
    domain_set = set(cleaned)
    result: list[str] = []
    seen: set[str] = set()

    for d in cleaned:
        canonical = d[4:] if d.startswith("www.") and d[4:] in domain_set else d
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


class SearXNGSearchAdapter(BaseSearchProvider):
    """SearXNG search provider adapter restricted to official Indian GST legal domains."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        engines: str | None = None,
    ):
        raw_url = base_url if base_url is not None else settings.SEARXNG_BASE_URL
        self.base_url = raw_url.strip().rstrip("/") if raw_url else ""
        self.timeout = timeout if timeout is not None else settings.SEARXNG_TIMEOUT
        raw_engines = engines if engines is not None else settings.SEARXNG_ENGINES
        self.engines = raw_engines.strip() if raw_engines and raw_engines.strip() else None

    def _build_effective_queries(self, query: str, domains: list[str] | None) -> list[str]:
        """Injects concise 'site:' domain filters when the query does not already specify one."""
        if "site:" in query.lower() or not domains:
            return [query]

        deduped = _dedupe_www_domains(domains)
        if not deduped:
            return [query]

        if len(deduped) <= _DEFAULT_SINGLE_GROUP_LIMIT:
            groups = [deduped]
        else:
            # Prefer canonical high-authority domains from sources.yaml when full allowlist is passed
            if set(domains) == set(settings.allowed_domains):
                selected = settings.get_priority_search_domains(max_domains=_CHUNK_SIZE * _MAX_DOMAIN_GROUPS)
            else:
                selected = deduped[: _CHUNK_SIZE * _MAX_DOMAIN_GROUPS]

            groups = [
                selected[i : i + _CHUNK_SIZE]
                for i in range(0, len(selected), _CHUNK_SIZE)
            ][:_MAX_DOMAIN_GROUPS]

        effective: list[str] = []
        for group in groups:
            if len(group) == 1:
                effective.append(f"{query} site:{group[0]}")
            else:
                site_clause = " OR ".join(f"site:{d}" for d in group)
                effective.append(f"{query} ({site_clause})")
        return effective

    def _build_params(self, effective_query: str, time_range: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": effective_query,
            "format": "json",
        }
        if time_range and time_range in _VALID_TIME_RANGES:
            params["time_range"] = time_range
        if self.engines:
            params["engines"] = self.engines
        return params

    async def _query_single(
        self,
        client: httpx.AsyncClient,
        effective_query: str,
        time_range: str | None,
    ) -> list[SearchResult]:
        search_url = f"{self.base_url}/search"
        headers = {
            "Accept": "application/json",
            "User-Agent": "GST-Practice-Copilot/1.0",
        }
        try:
            resp = await client.get(
                search_url,
                params=self._build_params(effective_query, time_range),
                headers=headers,
            )
        except httpx.RequestError as e:
            logger.error(f"SearXNG connection error at {search_url}: {e}")
            raise RuntimeError(f"Failed to reach SearXNG at {self.base_url}: {e}") from e

        if resp.status_code == 403:
            logger.error("SearXNG returned HTTP 403 Forbidden (JSON output may be disabled).")
            raise RuntimeError(
                "SearXNG API returned HTTP 403 Forbidden. "
                "Ensure 'json' is enabled under search.formats in your SearXNG settings.yml."
            )
        if resp.status_code != 200:
            logger.error(f"SearXNG search error: HTTP {resp.status_code} - {resp.text}")
            raise RuntimeError(f"SearXNG API returned HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        raw_results = data.get("results", [])

        results: list[SearchResult] = []
        for item in raw_results:
            url = (item.get("url") or "").strip()
            if not url:
                continue
            domain = urlparse(url).hostname or ""
            raw_score = item.get("score")
            try:
                score = float(raw_score) if raw_score is not None else 1.0
            except (TypeError, ValueError):
                score = 1.0

            results.append(
                SearchResult(
                    title=item.get("title") or url,
                    url=url,
                    snippet=item.get("content") or "",
                    domain=domain,
                    score=score,
                )
            )
        return results

    async def search(
        self,
        query: str,
        domains: list[str] | None = None,
        max_results: int = 10,
        time_range: str | None = None,
    ) -> list[SearchResult]:
        if not self.base_url:
            raise SearchNotConfiguredError(
                "SearXNG base URL is not configured. "
                "Please configure SEARXNG_BASE_URL in your .env file to enable live official search."
            )

        sanitized_query = sanitize_search_query(query).strip()
        if not sanitized_query:
            return []

        allowed_domains = domains if domains is not None else settings.allowed_domains
        effective_queries = self._build_effective_queries(sanitized_query, allowed_domains)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            tasks = [
                self._query_single(client, q, time_range)
                for q in effective_queries
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        merged_by_url: dict[str, SearchResult] = {}
        errors: list[Exception] = []

        for outcome in batch_results:
            if isinstance(outcome, Exception):
                errors.append(outcome)
                continue
            for item in outcome:
                existing = merged_by_url.get(item.url)
                if existing is None or item.score > existing.score:
                    merged_by_url[item.url] = item

        if not merged_by_url and errors:
            raise errors[0]

        sorted_results = sorted(merged_by_url.values(), key=lambda r: r.score, reverse=True)
        return sorted_results[:max_results]

    async def health_check(self) -> tuple[bool, str]:
        """Checks whether the configured SearXNG endpoint is reachable."""
        if not self.base_url:
            return False, "SearXNG base URL is not configured (SEARXNG_BASE_URL is empty)."

        headers = {
            "Accept": "application/json",
            "User-Agent": "GST-Practice-Copilot/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/config", headers=headers)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        instance = data.get("instance_name") or "SearXNG"
                        version = data.get("version") or ""
                        suffix = f" v{version}" if version else ""
                        return True, f"{instance}{suffix} reachable at {self.base_url}"
                    except ValueError:
                        return True, f"SearXNG endpoint reachable at {self.base_url}"

                if resp.status_code in (403, 404):
                    hz = await client.get(f"{self.base_url}/healthz", headers=headers)
                    if hz.status_code == 200:
                        return True, f"SearXNG endpoint reachable at {self.base_url}"
                    return False, f"SearXNG endpoint responded with HTTP {hz.status_code}"

                return False, f"SearXNG endpoint responded with HTTP {resp.status_code}"
        except Exception as e:
            return False, f"SearXNG health check failed: {e!s}"

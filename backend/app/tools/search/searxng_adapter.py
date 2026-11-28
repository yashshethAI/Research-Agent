from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.app.core.config import settings
from backend.app.tools.search.base import (
    BaseSearchProvider,
    SearchEngineRateLimitError,
    SearchNotConfiguredError,
    SearchResult,
    SearchServiceUnavailableError,
    sanitize_search_query,
)

logger = logging.getLogger(__name__)

_VALID_TIME_RANGES = {"day", "week", "month", "year"}
_DEFAULT_SINGLE_GROUP_LIMIT = 8
_CHUNK_SIZE = 6
_MAX_DOMAIN_GROUPS = 2
_RATE_LIMIT_MARKERS = (
    "captcha",
    "too many requests",
    "suspended",
    "rate limit",
    "429",
    "access denied",
)
_CONNECT_RETRY_DELAYS = (0.5, 1.0)
_ENGINE_COOLDOWN_SECONDS = 180

# ---------------------------------------------------------------------------
# In-memory TTL cache + engine cooldown tracker for SearXNG
# ---------------------------------------------------------------------------
_DEFAULT_MEMORY_TTL_SECONDS = 3600
_MAX_CACHE_SIZE = 128
_result_cache: dict[tuple[str, str | None, str | None], tuple[float, list[SearchResult]]] = {}
_engine_cooldown_until: dict[str, float] = {}


def clear_search_caches(cache_dir: Path | None = None) -> None:
    """Clears in-memory search caches, engine cooldowns, and optionally disk search cache."""
    _result_cache.clear()
    _engine_cooldown_until.clear()
    target_dir = cache_dir or (settings.source_cache_dir / "search_cache")
    if target_dir.exists():
        for p in target_dir.glob("*.json"):
            try:
                p.unlink()
            except OSError:
                pass


def _cache_get(
    key: tuple[str, str | None, str | None],
    ttl_seconds: int = _DEFAULT_MEMORY_TTL_SECONDS,
) -> list[SearchResult] | None:
    """Return cached results if present and not expired, else None."""
    if ttl_seconds <= 0:
        return None
    entry = _result_cache.get(key)
    if entry is None:
        return None
    ts, results = entry
    if time.monotonic() - ts > ttl_seconds:
        _result_cache.pop(key, None)
        return None
    return results


def _cache_put(
    key: tuple[str, str | None, str | None],
    results: list[SearchResult],
    ttl_seconds: int = _DEFAULT_MEMORY_TTL_SECONDS,
) -> None:
    """Store results in in-memory cache, evicting oldest entries if over capacity."""
    if ttl_seconds <= 0:
        return
    now = time.monotonic()
    expired = [k for k, (ts, _) in _result_cache.items() if now - ts > ttl_seconds]
    for k in expired:
        _result_cache.pop(k, None)
    while len(_result_cache) >= _MAX_CACHE_SIZE:
        oldest_key = min(_result_cache, key=lambda k: _result_cache[k][0])
        _result_cache.pop(oldest_key, None)
    _result_cache[key] = (now, results)


def _disk_cache_path(cache_dir: Path, key: tuple[str, str | None, str | None]) -> Path:
    effective_query, time_range, engines = key
    raw_key = f"{engines or ''}\n{time_range or ''}\n{effective_query}".encode("utf-8")
    digest = hashlib.sha256(raw_key).hexdigest()
    return cache_dir / f"{digest}.json"


def _disk_cache_get(
    cache_dir: Path,
    key: tuple[str, str | None, str | None],
    ttl_seconds: int,
) -> list[SearchResult] | None:
    if ttl_seconds <= 0:
        return None
    path = _disk_cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = float(payload.get("created_at", 0.0))
        if time.time() - created_at > ttl_seconds:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        return [SearchResult(**item) for item in payload.get("results", [])]
    except Exception:
        return None


def _disk_cache_put(
    cache_dir: Path,
    key: tuple[str, str | None, str | None],
    results: list[SearchResult],
    ttl_seconds: int,
) -> None:
    if ttl_seconds <= 0:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _disk_cache_path(cache_dir, key)
        tmp_path = path.with_suffix(".tmp")
        payload = {
            "created_at": time.time(),
            "results": [r.model_dump() for r in results],
        }
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as e:
        logger.debug(f"Failed writing SearXNG disk cache: {e}")


def _parse_engine_groups(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [grp.strip() for grp in raw.split(";") if grp and grp.strip()]


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
        use_site_operators: bool | None = None,
        fallback_engines: str | None = None,
        cache_ttl_seconds: int | None = None,
        cache_dir: Path | None = None,
    ):
        raw_url = base_url if base_url is not None else settings.SEARXNG_BASE_URL
        self.base_url = raw_url.strip().rstrip("/") if raw_url else ""
        self.timeout = timeout if timeout is not None else settings.SEARXNG_TIMEOUT
        raw_engines = engines if engines is not None else settings.SEARXNG_ENGINES
        self.engines = raw_engines.strip() if raw_engines and raw_engines.strip() else None
        raw_fallback = (
            fallback_engines if fallback_engines is not None else settings.SEARXNG_FALLBACK_ENGINES
        )
        self.fallback_engine_groups = _parse_engine_groups(raw_fallback)
        self.use_site_operators = (
            use_site_operators if use_site_operators is not None else settings.SEARXNG_USE_SITE_OPERATORS
        )
        self.cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else settings.SEARCH_CACHE_TTL_SECONDS
        )
        self.cache_dir = cache_dir if cache_dir is not None else (settings.source_cache_dir / "search_cache")

    def _candidate_engine_sets(self) -> list[str | None]:
        """Returns ordered engine groups, preferring groups not in rate-limit cooldown."""
        ordered: list[str | None] = []
        if self.engines:
            ordered.append(self.engines)
        else:
            ordered.append(None)

        for grp in self.fallback_engine_groups:
            if grp not in ordered:
                ordered.append(grp)

        now = time.monotonic()
        active = [eng for eng in ordered if _engine_cooldown_until.get(eng or "__default__", 0.0) <= now]
        if active:
            return active

        # If every configured group is in cooldown, try the one expiring soonest
        return sorted(ordered, key=lambda eng: _engine_cooldown_until.get(eng or "__default__", 0.0))

    def _build_effective_queries(self, query: str, domains: list[str] | None) -> list[str]:
        """Injects concise 'site:' domain filters when use_site_operators is True and query has none."""
        if not self.use_site_operators:
            return [query]

        if "site:" in query.lower() or not domains:
            return [query]

        deduped = _dedupe_www_domains(domains)
        if not deduped:
            return [query]

        if len(deduped) <= _DEFAULT_SINGLE_GROUP_LIMIT:
            groups = [deduped]
        else:
            domain_set = set(domains)
            if domain_set == set(settings.official_domains):
                selected = settings.get_priority_search_domains(
                    max_domains=_CHUNK_SIZE * _MAX_DOMAIN_GROUPS,
                    section="official_sources",
                )
            elif domain_set == set(settings.verified_secondary_domains):
                selected = settings.get_priority_search_domains(
                    max_domains=_CHUNK_SIZE * _MAX_DOMAIN_GROUPS,
                    section="verified_secondary_sources",
                )
            elif domain_set == set(settings.allowed_domains):
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

    def _build_params(
        self,
        effective_query: str,
        time_range: str | None,
        engines: str | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": effective_query,
            "format": "json",
        }
        if time_range and time_range in _VALID_TIME_RANGES:
            params["time_range"] = time_range
        if engines:
            params["engines"] = engines
        return params

    async def _http_get_with_retry(
        self,
        client: httpx.AsyncClient,
        search_url: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        """Executes GET against SearXNG with bounded retries for transient startup/connect errors."""
        attempts = len(_CONNECT_RETRY_DELAYS) + 1
        for attempt in range(attempts):
            try:
                return await client.get(search_url, params=params, headers=headers)
            except httpx.RequestError as e:
                if attempt < len(_CONNECT_RETRY_DELAYS):
                    delay = _CONNECT_RETRY_DELAYS[attempt]
                    logger.warning(
                        f"SearXNG connection attempt {attempt + 1}/{attempts} failed ({e}); retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(f"SearXNG connection error at {search_url}: {e}")
                raise SearchServiceUnavailableError(
                    f"Failed to reach SearXNG at {self.base_url}: {e}"
                ) from e
        raise SearchServiceUnavailableError(f"Failed to reach SearXNG at {self.base_url}")

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

        last_rate_limit_err: SearchEngineRateLimitError | None = None
        engine_candidates = self._candidate_engine_sets()

        for engine_idx, active_engines in enumerate(engine_candidates):
            cache_key = (effective_query, time_range, active_engines)
            cached = _cache_get(cache_key, ttl_seconds=self.cache_ttl_seconds)
            if cached is not None:
                logger.debug(
                    f"SearXNG memory cache hit for '{effective_query[:50]}' "
                    f"(engines={active_engines}, time_range={time_range})"
                )
                return cached

            disk_cached = _disk_cache_get(
                self.cache_dir,
                cache_key,
                ttl_seconds=self.cache_ttl_seconds,
            )
            if disk_cached is not None:
                logger.debug(
                    f"SearXNG disk cache hit for '{effective_query[:50]}' "
                    f"(engines={active_engines}, time_range={time_range})"
                )
                _cache_put(cache_key, disk_cached, ttl_seconds=self.cache_ttl_seconds)
                return disk_cached

            resp = await self._http_get_with_retry(
                client,
                search_url,
                self._build_params(effective_query, time_range, active_engines),
                headers,
            )

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
            unresponsive = data.get("unresponsive_engines") or []

            if unresponsive:
                unresponsive_msgs = [
                    f"{item[0]}: {item[1]}"
                    if isinstance(item, (list, tuple)) and len(item) >= 2
                    else str(item)
                    for item in unresponsive
                ]
                summary = "; ".join(unresponsive_msgs)
                logger.warning(
                    f"SearXNG unresponsive engines ({active_engines or 'default'}) "
                    f"for '{effective_query[:60]}': {summary}"
                )
                if not raw_results and any(m in summary.lower() for m in _RATE_LIMIT_MARKERS):
                    cooldown_key = active_engines or "__default__"
                    _engine_cooldown_until[cooldown_key] = time.monotonic() + _ENGINE_COOLDOWN_SECONDS
                    last_rate_limit_err = SearchEngineRateLimitError(
                        f"SearXNG upstream engines blocked/rate-limited ({summary})"
                    )
                    if engine_idx + 1 < len(engine_candidates):
                        next_engines = engine_candidates[engine_idx + 1]
                        logger.info(
                            f"Rotating SearXNG engines from '{active_engines or 'default'}' "
                            f"to '{next_engines or 'default'}' after rate-limit/CAPTCHA"
                        )
                        continue
                    raise last_rate_limit_err

            results: list[SearchResult] = []
            for item in raw_results:
                url = (item.get("url") or "").strip()
                if not url:
                    continue
                domain = (urlparse(url).hostname or "").strip()
                if not domain:
                    logger.debug(f"Skipping malformed SearXNG result URL without hostname: {url}")
                    continue
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

            _cache_put(cache_key, results, ttl_seconds=self.cache_ttl_seconds)
            _disk_cache_put(self.cache_dir, cache_key, results, ttl_seconds=self.cache_ttl_seconds)
            return results

        if last_rate_limit_err is not None:
            raise last_rate_limit_err
        return []

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

        sem = asyncio.Semaphore(2)

        async def _throttled_query(idx: int, q_str: str) -> list[SearchResult]:
            async with sem:
                if idx > 0:
                    await asyncio.sleep(1.0)
                return await self._query_single(client, q_str, time_range)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if self.use_site_operators and len(effective_queries) > 1:
                first_results = await self._query_single(client, effective_queries[0], time_range)
                if len(first_results) >= 5:
                    batch_results: list[list[SearchResult] | Exception] = [first_results]
                else:
                    remaining_tasks = [
                        _throttled_query(idx, q)
                        for idx, q in enumerate(effective_queries[1:], 1)
                    ]
                    remaining = await asyncio.gather(*remaining_tasks, return_exceptions=True)
                    batch_results = [first_results, *remaining]
            else:
                tasks = [
                    _throttled_query(idx, q)
                    for idx, q in enumerate(effective_queries)
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

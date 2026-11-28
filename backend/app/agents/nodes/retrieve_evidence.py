from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.app.agents.state import ResearchState
from backend.app.core.config import settings
from backend.app.core.logging_utils import (
    make_node_error,
    make_trace_entry,
    reset_log_context,
    set_log_context,
)
from backend.app.tools.evidence_extractor import (
    compile_relevant_evidence,
    detect_bot_block,
    detect_spa_shell,
    is_evidence_sufficient,
    is_utility_or_homepage_url,
    normalize_llm_search_queries,
    rerank_search_results,
)
from backend.app.tools.fetcher import safe_fetcher
from backend.app.tools.html_parser import HTMLParser
from backend.app.tools.pdf_parser import PDFParser
from backend.app.tools.search.base import (
    SearchEngineRateLimitError,
    SearchNotConfiguredError,
    SearchResult,
    SearchServiceUnavailableError,
)
from backend.app.tools.search.mock_adapter import MockSearchAdapter
from backend.app.tools.search.searxng_adapter import SearXNGSearchAdapter
from backend.app.tools.source_validator import source_validator

logger = logging.getLogger(__name__)

# Natural-language tier hints appended when site: operators are disabled
_TIER_HINTS: dict[str, str] = {
    "official": "CBIC",
    "verified_secondary": "Taxmann ICAI",
}
_BACKFILL_BATCH_LIMIT = 4


def _next_search_tier(current_tier: str) -> str | None:
    if current_tier == "official":
        return "verified_secondary"
    if current_tier == "verified_secondary" and settings.ALLOW_UNVERIFIED_FALLBACK:
        return "unverified_fallback"
    return None


def _broaden_queries(queries: list[str]) -> list[str]:
    """Simplifies overly narrow queries when escalating fallback tiers."""
    broadened: list[str] = []
    for q in queries:
        words = q.split()
        broadened.append(" ".join(words[:6]) if len(words) > 6 else q)
    return normalize_llm_search_queries(broadened, max_queries=4)


def _add_tier_hint(query: str, tier: str) -> str:
    """Appends a light tier hint when site: operators are disabled and query lacks domain cues."""
    if settings.SEARXNG_USE_SITE_OPERATORS:
        return query
    q_l = query.lower()
    if tier == "official":
        if "cbic" in q_l or "gst" in q_l or "cgst" in q_l or "igst" in q_l:
            return query
        return f"{query} CBIC"
    hint = _TIER_HINTS.get(tier)
    if hint and hint.lower() not in q_l:
        return f"{query} {hint}"
    return query


def _promote_from_pool(
    existing_results: list[dict[str, Any]],
    target_tier: str,
    seen_urls: set[str],
) -> list[SearchResult]:
    """Promotes already-fetched URLs matching target_tier from the unfiltered result pool."""
    promoted: list[SearchResult] = []
    for r in existing_results:
        url = r.get("url", "")
        if url in seen_urls:
            continue
        stored_tier = r.get("source_tier", "")
        if stored_tier == target_tier:
            promoted.append(
                SearchResult(
                    title=r.get("title", url),
                    url=url,
                    snippet=r.get("snippet", ""),
                    domain=r.get("domain", ""),
                    score=float(r.get("score", 1.0)),
                )
            )
            seen_urls.add(url)
    return promoted


async def _fetch_and_parse_candidates(
    candidates: list[SearchResult],
    active_tier: str,
    allow_unverified: bool,
    errors: list[dict[str, Any]],
    fetch_counts: dict[str, int],
) -> tuple[list[dict[str, Any]], list[tuple[SearchResult, Any, dict[str, Any]]]]:
    """Fetches candidate URLs in parallel, parses HTML/PDF, filters bot gates, and queues SPA shells."""
    if not candidates:
        return [], []

    fetch_outcomes = await asyncio.gather(
        *[safe_fetcher.fetch(r.url, allow_unverified=allow_unverified) for r in candidates],
        return_exceptions=True,
    )

    parsed_docs: list[dict[str, Any]] = []
    spa_pending: list[tuple[SearchResult, Any, dict[str, Any]]] = []

    for hit, outcome in zip(candidates, fetch_outcomes):
        if isinstance(outcome, Exception):
            logger.warning(f"Fetch failed for {hit.url}: {type(outcome).__name__}: {outcome}")
            errors.append(make_node_error("retrieve_evidence", "fetch", outcome, hit.url))
            if hit.snippet:
                fetch_counts["snippet_only"] += 1
                parsed_docs.append({
                    "url": hit.url,
                    "title": hit.title or hit.url,
                    "text": hit.snippet,
                    "doc_type": "Search Snippet Fallback",
                    "source_tier": active_tier,
                    "fetch_status": "snippet_only",
                    "sha256_hash": f"snippet-{abs(hash(hit.url)) % 1000000:06d}",
                })
            continue

        try:
            if "pdf" in outcome.content_type or outcome.url.lower().endswith(".pdf"):
                extracted = PDFParser.parse_pdf_bytes(outcome.content)
                doc_type = "PDF Notification / Circular / Order"
                is_bot_blocked = False
                is_spa = False
            else:
                html_str = outcome.content.decode("utf-8", errors="replace")
                extracted = HTMLParser.parse_html(html_str, base_url=outcome.url)
                doc_type = "Statutory Portal HTML Page"
                extracted_text = extracted.get("text") or ""
                is_bot_blocked = detect_bot_block(html_str, extracted_text)
                is_spa = False if is_bot_blocked else detect_spa_shell(html_str, extracted_text)

            if is_bot_blocked:
                logger.warning(f"Bot/CAPTCHA gate detected for {outcome.url}; skipping Playwright.")
                errors.append(
                    make_node_error(
                        "retrieve_evidence",
                        "fetch_blocked",
                        RuntimeError("Target site returned WAF/CAPTCHA interstitial"),
                        outcome.url,
                    )
                )
                if hit.snippet:
                    fetch_counts["snippet_only"] += 1
                    parsed_docs.append({
                        "url": outcome.url,
                        "title": hit.title or outcome.url,
                        "text": hit.snippet,
                        "doc_type": "Blocked Page Snippet Fallback",
                        "source_tier": active_tier,
                        "fetch_status": "snippet_only",
                        "sha256_hash": outcome.sha256_hash,
                    })
            elif is_spa:
                spa_pending.append((hit, outcome, extracted))
            else:
                fetch_counts["fetched"] += 1
                parsed_docs.append({
                    "url": outcome.url,
                    "title": extracted.get("title") or hit.title or outcome.url,
                    "text": (extracted.get("text") or "")[:150000],
                    "doc_type": doc_type,
                    "source_tier": active_tier,
                    "fetch_status": "fetched",
                    "sha256_hash": outcome.sha256_hash,
                })
        except Exception as parse_err:
            logger.error(f"Parse error for {outcome.url}: {parse_err}")
            errors.append(make_node_error("retrieve_evidence", "parse", parse_err, outcome.url))
            if hit.snippet:
                fetch_counts["snippet_only"] += 1
                parsed_docs.append({
                    "url": outcome.url,
                    "title": hit.title or hit.url,
                    "text": hit.snippet,
                    "doc_type": "Parse Error Snippet Fallback",
                    "source_tier": active_tier,
                    "fetch_status": "snippet_only",
                    "sha256_hash": outcome.sha256_hash,
                })

    return parsed_docs, spa_pending


async def retrieve_evidence_node(state: ResearchState) -> dict[str, Any]:
    """Node 2: Executes one tier pass (search -> rerank -> fetch -> parse -> relevant passage compile)."""
    t0 = time.perf_counter()
    active_tier = state.search_tier or "official"
    tokens = set_log_context(
        conversation_id=state.conversation_id,
        research_id=state.research_id,
        node="retrieve_evidence",
        tier=active_tier,
    )
    errors = list(state.node_errors)
    trace = list(state.execution_trace)

    try:
        if state.llm_unconfigured_guidance or state.needs_clarification:
            return {"current_step": "retrieve_evidence"}

        queries = normalize_llm_search_queries(state.search_queries, max_queries=3)
        if not queries:
            queries = normalize_llm_search_queries([state.query], max_queries=2)

        # Cap to 2 focused queries on first pass
        if state.retry_count == 0 and len(queries) > 2:
            queries = queries[:2]

        allow_unverified = active_tier == "unverified_fallback"
        target_domains = settings.get_tier_domains(active_tier, max_domains=12)
        attempted_tiers = list(state.attempted_tiers)
        if active_tier not in attempted_tiers:
            attempted_tiers.append(active_tier)

        attempted_queries = list(state.attempted_queries)
        for q in queries:
            tag = f"[{active_tier}] {q}"
            if tag not in attempted_queries:
                attempted_queries.append(tag)

        # 1. Select search provider
        if settings.SEARCH_PROVIDER == "mock":
            adapter = MockSearchAdapter()
        elif settings.SEARCH_PROVIDER == "searxng":
            adapter = SearXNGSearchAdapter()
        else:
            err_msg = f"Unsupported search provider: {settings.SEARCH_PROVIDER}"
            errors.append(make_node_error("retrieve_evidence", "init_adapter", err_msg))
            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry("retrieve_evidence", active_tier, "error", dur, error=err_msg))
            return {
                "current_step": "retrieve_evidence",
                "error_message": err_msg,
                "should_refine_search": False,
                "attempted_tiers": attempted_tiers,
                "attempted_queries": attempted_queries,
                "execution_trace": trace,
                "node_errors": errors,
            }

        # 2. Try promoting from result pool before querying SearXNG
        already_fetched_urls: set[str] = {e.get("url", "") for e in state.evidence_records if e.get("url")}
        pool_hits = _promote_from_pool(state.search_results, active_tier, already_fetched_urls)
        seen_urls: set[str] = already_fetched_urls | {r.get("url", "") for r in state.search_results if r.get("url")}

        # 3. Search across queries in active tier
        raw_hits: list[SearchResult] = list(pool_hits)
        rate_limited = False
        early_stop_threshold = 5

        for idx, q in enumerate(queries):
            substantive_hits = sum(1 for r in raw_hits if not is_utility_or_homepage_url(r.url))
            if substantive_hits >= early_stop_threshold:
                logger.info(
                    f"Early stop: {substantive_hits} substantive hits already, skipping remaining queries"
                )
                break

            if idx > 0 and settings.SEARCH_PROVIDER == "searxng":
                await asyncio.sleep(1.2)

            hinted_query = _add_tier_hint(q, active_tier)

            try:
                results = await adapter.search(
                    query=hinted_query,
                    domains=target_domains,
                    max_results=settings.MAX_SEARCH_RESULTS,
                    time_range=state.search_time_range,
                )
                for r in results:
                    is_valid, reason = source_validator.validate_url(r.url, allow_unverified=allow_unverified)
                    if is_valid and r.url not in seen_urls:
                        seen_urls.add(r.url)
                        raw_hits.append(r)
                    elif not is_valid:
                        logger.debug(f"Filtered URL ({reason}): {r.url}")
            except (SearchNotConfiguredError, SearchServiceUnavailableError) as e:
                logger.warning(f"Search unavailable/unconfigured: {e}")
                errors.append(make_node_error("retrieve_evidence", "search", e, q))
                dur = int((time.perf_counter() - t0) * 1000)
                trace.append(make_trace_entry("retrieve_evidence", active_tier, "error", dur, error=str(e)))
                return {
                    "current_step": "retrieve_evidence",
                    "error_message": str(e),
                    "should_refine_search": False,
                    "attempted_tiers": attempted_tiers,
                    "attempted_queries": attempted_queries,
                    "execution_trace": trace,
                    "node_errors": errors,
                }
            except SearchEngineRateLimitError as e:
                logger.warning(f"Search engine rate limit for '{q}': {e}")
                errors.append(make_node_error("retrieve_evidence", "search", e, q))
                rate_limited = True
                break
            except Exception as e:
                logger.error(f"Search failed for query '{q}': {e}")
                errors.append(make_node_error("retrieve_evidence", "search", e, q))

        # 4. Rerank hits across queries before selecting top fetch slots
        effective_query = (state.extracted_facts or {}).get("effective_query") or state.query
        target_terms = (state.research_plan or {}).get("target_sections") or []
        ranked_hits = rerank_search_results(raw_hits, query=effective_query, target_terms=target_terms)

        # Store ALL unfiltered results with real tier from domain authority for pool reuse
        existing_pool_urls = {r.get("url", "") for r in state.search_results if r.get("url")}
        tier_search_results: list[dict[str, Any]] = []
        for r in ranked_hits:
            if r.url not in existing_pool_urls:
                real_tier, _, _ = settings.get_domain_authority_info(r.domain or "")
                tier_search_results.append({**r.model_dump(), "source_tier": real_tier})
        all_search_results = [*state.search_results, *tier_search_results]

        # 5 & 6. Parallel fetch top substantive candidates + parse
        substantive_ranked = [r for r in ranked_hits if not is_utility_or_homepage_url(r.url)]
        fetch_pool = substantive_ranked if substantive_ranked else ranked_hits
        max_fetch = settings.MAX_FETCH_SOURCES
        fetch_counts = {"fetched": 0, "spa_shell": 0, "snippet_only": 0, "playwright_rendered": 0}
        parsed_docs, spa_pending = await _fetch_and_parse_candidates(
            fetch_pool[:max_fetch],
            active_tier=active_tier,
            allow_unverified=allow_unverified,
            errors=errors,
            fetch_counts=fetch_counts,
        )

        # 6a. Backfill from remaining ranked hits if initial candidates failed/blocked
        usable_target = min(4, max_fetch)
        if fetch_counts["fetched"] + len(spa_pending) < usable_target and len(fetch_pool) > max_fetch:
            backfill_candidates = fetch_pool[max_fetch : max_fetch + _BACKFILL_BATCH_LIMIT]
            extra_docs, extra_spa = await _fetch_and_parse_candidates(
                backfill_candidates,
                active_tier=active_tier,
                allow_unverified=allow_unverified,
                errors=errors,
                fetch_counts=fetch_counts,
            )
            parsed_docs.extend(extra_docs)
            spa_pending.extend(extra_spa)

        # 6b. Batch-render up to 3 SPA shells concurrently in a single Chromium session
        if spa_pending:
            rendered_docs = await safe_fetcher.fetch_rendered_html_batch(
                [outcome.url for _, outcome, _ in spa_pending],
                max_urls=3,
            )
            for hit, outcome, extracted in spa_pending:
                rendered_doc = rendered_docs.get(outcome.url)
                if rendered_doc is not None:
                    rendered_html = rendered_doc.content.decode("utf-8", errors="replace")
                    rendered_extracted = HTMLParser.parse_html(rendered_html, base_url=outcome.url)
                    rendered_text = rendered_extracted.get("text") or ""
                    if not detect_bot_block(rendered_html, rendered_text) and len(rendered_text.strip()) > 250:
                        fetch_counts["playwright_rendered"] += 1
                        parsed_docs.append({
                            "url": outcome.url,
                            "title": rendered_extracted.get("title") or hit.title or outcome.url,
                            "text": rendered_text[:150000],
                            "doc_type": "JS-SPA Rendered (Playwright)",
                            "source_tier": active_tier,
                            "fetch_status": "fetched",
                            "sha256_hash": rendered_doc.sha256_hash,
                        })
                        continue

                fetch_counts["spa_shell"] += 1
                fallback_text = hit.snippet or (extracted.get("text") or "")
                parsed_docs.append({
                    "url": outcome.url,
                    "title": extracted.get("title") or hit.title or outcome.url,
                    "text": fallback_text,
                    "doc_type": "JS-SPA Shell (Snippet Only)",
                    "source_tier": active_tier,
                    "fetch_status": "spa_shell",
                    "sha256_hash": outcome.sha256_hash,
                })

        # 7. Compile query-relevant passages & merge with any prior tier records
        new_evidence = compile_relevant_evidence(
            parsed_docs,
            query=effective_query,
            research_plan=state.research_plan,
            tier=active_tier,
            start_index=len(state.evidence_records) + 1,
            max_excerpt_chars=2200,
        )
        merged_evidence = [*state.evidence_records, *new_evidence]

        # 8. Sufficiency gate & tier escalation decision
        sufficient, feedback = is_evidence_sufficient(
            merged_evidence,
            query=effective_query,
            research_plan=state.research_plan,
        )

        next_tier = _next_search_tier(active_tier)
        fetched_after = {e.get("url", "") for e in merged_evidence if e.get("url")}
        has_pool_for_next = bool(
            next_tier
            and any(
                r.get("source_tier") == next_tier and r.get("url") not in fetched_after
                for r in all_search_results
            )
        )
        should_escalate = (
            not sufficient
            and next_tier is not None
            and state.retry_count < settings.MAX_RESEARCH_RETRIES
            and (not rate_limited or has_pool_for_next)
        )

        next_retry = state.retry_count + 1 if should_escalate else state.retry_count
        next_queries = _broaden_queries(queries) if should_escalate else queries

        dur = int((time.perf_counter() - t0) * 1000)
        summary = {
            "raw_hits": len(raw_hits),
            "pool_promoted": len(pool_hits),
            "fetch_counts": fetch_counts,
            "new_evidence": len(new_evidence),
            "total_evidence": len(merged_evidence),
            "sufficient": sufficient,
            "escalate_to": next_tier if should_escalate else None,
        }
        trace.append(make_trace_entry("retrieve_evidence", active_tier, "ok", dur, summary))
        logger.info(f"Completed retrieve_evidence ({active_tier}) in {dur}ms: {summary}")

        return {
            "current_step": "retrieve_evidence",
            "search_results": all_search_results,
            "evidence_records": merged_evidence,
            "attempted_tiers": attempted_tiers,
            "attempted_queries": attempted_queries,
            "search_feedback": feedback,
            "should_refine_search": should_escalate,
            "search_tier": next_tier if should_escalate else active_tier,
            "search_queries": next_queries,
            "retry_count": next_retry,
            "execution_trace": trace,
            "node_errors": errors,
        }
    finally:
        reset_log_context(tokens)

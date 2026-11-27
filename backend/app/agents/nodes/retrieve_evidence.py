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
    detect_spa_shell,
    is_evidence_sufficient,
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
)
from backend.app.tools.search.mock_adapter import MockSearchAdapter
from backend.app.tools.search.searxng_adapter import SearXNGSearchAdapter
from backend.app.tools.source_validator import source_validator

logger = logging.getLogger(__name__)


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

        # 2. Search across queries in active tier
        raw_hits: list[SearchResult] = []
        seen_urls: set[str] = {r.get("url", "") for r in state.search_results}
        rate_limited = False

        for idx, q in enumerate(queries):
            if idx > 0 and settings.SEARCH_PROVIDER == "searxng":
                await asyncio.sleep(0.25)
            try:
                results = await adapter.search(
                    query=q,
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
            except SearchNotConfiguredError as e:
                logger.warning(f"Search not configured: {e}")
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

        # 3. Rerank hits across queries before selecting top fetch slots
        effective_query = (state.extracted_facts or {}).get("effective_query") or state.query
        target_terms = (state.research_plan or {}).get("target_sections") or []
        ranked_hits = rerank_search_results(raw_hits, query=effective_query, target_terms=target_terms)

        tier_search_results = [{**r.model_dump(), "source_tier": active_tier} for r in ranked_hits]
        all_search_results = [*state.search_results, *tier_search_results]

        # 4. Parallel fetch top candidates
        max_fetch = settings.MAX_FETCH_SOURCES
        candidates = ranked_hits[:max_fetch]
        fetch_outcomes = await asyncio.gather(
            *[safe_fetcher.fetch(r.url, allow_unverified=allow_unverified) for r in candidates],
            return_exceptions=True,
        )

        # 5. Parse HTML / PDF in memory (never storing raw bytes in ResearchState)
        parsed_docs: list[dict[str, Any]] = []
        fetch_counts = {"fetched": 0, "spa_shell": 0, "snippet_only": 0}

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
                    is_spa = False
                else:
                    html_str = outcome.content.decode("utf-8", errors="replace")
                    extracted = HTMLParser.parse_html(html_str, base_url=outcome.url)
                    doc_type = "Statutory Portal HTML Page"
                    is_spa = detect_spa_shell(html_str, extracted.get("text") or "")

                if is_spa:
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
                        "title": hit.title or outcome.url,
                        "text": hit.snippet,
                        "doc_type": "Parse Error Snippet Fallback",
                        "source_tier": active_tier,
                        "fetch_status": "snippet_only",
                        "sha256_hash": outcome.sha256_hash,
                    })

        # 6. Compile query-relevant passages & merge with any prior tier records
        new_evidence = compile_relevant_evidence(
            parsed_docs,
            query=effective_query,
            research_plan=state.research_plan,
            tier=active_tier,
            start_index=len(state.evidence_records) + 1,
            max_excerpt_chars=2200,
        )
        merged_evidence = [*state.evidence_records, *new_evidence]

        # 7. Sufficiency gate & tier escalation decision
        sufficient, feedback = is_evidence_sufficient(
            merged_evidence,
            query=effective_query,
            research_plan=state.research_plan,
        )

        next_tier = _next_search_tier(active_tier)
        should_escalate = (
            not sufficient
            and not rate_limited
            and next_tier is not None
            and state.retry_count < settings.MAX_RESEARCH_RETRIES
        )

        next_retry = state.retry_count + 1 if should_escalate else state.retry_count
        next_queries = _broaden_queries(queries) if should_escalate else queries

        dur = int((time.perf_counter() - t0) * 1000)
        summary = {
            "raw_hits": len(raw_hits),
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

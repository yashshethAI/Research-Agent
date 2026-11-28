from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from backend.app.agents.state import ResearchState
from backend.app.core.logging_utils import make_trace_entry, reset_log_context, set_log_context

logger = logging.getLogger(__name__)

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_SRC_REF_RE = re.compile(r"^(?:#|https?://)?(SRC-\d{3})$", re.IGNORECASE)
_BARE_SRC_GROUP_RE = re.compile(r"(?<!\[)\[(SRC-\d{3}(?:\s*,\s*SRC-\d{3})*)\](?!\()", re.IGNORECASE)
_PAREN_SRC_GROUP_RE = re.compile(r"(?<!\])\((SRC-\d{3}(?:\s*,\s*SRC-\d{3})*)\)", re.IGNORECASE)
_NOTIF_CITE_RE = re.compile(r"Notification\s+No\.?\s*(\d+/\d{4})", re.IGNORECASE)
_CIRC_CITE_RE = re.compile(r"Circular\s+No\.?\s*(\d+/\d+/\d{4})", re.IGNORECASE)


async def validate_citations_node(state: ResearchState) -> dict[str, Any]:
    """Node 4: Deterministic post-generation audit resolving SRC-XXX links and checking citations against evidence."""
    t0 = time.perf_counter()
    tokens = set_log_context(
        conversation_id=state.conversation_id,
        research_id=state.research_id,
        node="validate_citations",
        tier=state.search_tier,
    )
    trace = list(state.execution_trace)

    try:
        if state.llm_unconfigured_guidance or state.needs_clarification or state.error_message:
            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry("validate_citations", state.search_tier, "skipped", dur))
            return {"current_step": "validate_citations", "execution_trace": trace}

        evidence_records = state.evidence_records or []
        report = state.final_report or ""

        if not evidence_records:
            dur = int((time.perf_counter() - t0) * 1000)
            trace.append(make_trace_entry("validate_citations", state.search_tier, "no_evidence", dur))
            return {
                "current_step": "validate_citations",
                "citation_validation": {
                    "verified_citations": [],
                    "unverified_claims": [],
                    "source_count": 0,
                    "tiers_used": state.attempted_tiers,
                    "links_resolved": 0,
                    "links_stripped": 0,
                    "validation_status": "No Evidence Retrieved",
                },
                "execution_trace": trace,
            }

        by_id: dict[str, dict[str, Any]] = {
            (e.get("source_id") or "").upper(): e for e in evidence_records if e.get("source_id")
        }
        evidence_urls: set[str] = {e.get("url", "") for e in evidence_records if e.get("url")}
        evidence_hosts: set[str] = {
            (urlparse(u).hostname or "").lower() for u in evidence_urls if urlparse(u).hostname
        }
        evidence_corpus = " ".join(
            f"{e.get('title', '')} {e.get('section_or_rule', '')} {e.get('excerpt', '')}"
            for e in evidence_records
        ) + f" {state.query}"

        unverified_claims: list[str] = []
        links_resolved = 0
        links_stripped = 0

        def _resolve_src_list(raw_group: str) -> str:
            nonlocal links_resolved, links_stripped
            parts: list[str] = []
            for token in raw_group.split(","):
                src_id = token.strip().upper()
                rec = by_id.get(src_id)
                if rec and rec.get("url"):
                    links_resolved += 1
                    parts.append(f"[{src_id}]({rec['url']})")
                else:
                    links_stripped += 1
                    unverified_claims.append(f"Unresolved source reference: {src_id}")
                    parts.append(f"{src_id} *(unverified)*")
            return ", ".join(parts)

        # Pass 1: Resolve [Label](SRC-XXX) and strip fabricated external URLs
        def _audit_md_link(match: re.Match[str]) -> str:
            nonlocal links_resolved, links_stripped
            label = match.group(1)
            target = match.group(2).strip()

            src_match = _SRC_REF_RE.match(target)
            if src_match:
                src_id = src_match.group(1).upper()
                rec = by_id.get(src_id)
                if rec and rec.get("url"):
                    links_resolved += 1
                    return f"[{label}]({rec['url']})"
                links_stripped += 1
                unverified_claims.append(f"Unresolved source reference: {target}")
                return f"{label} *(source reference unverified)*"

            if target in evidence_urls:
                return match.group(0)

            host = (urlparse(target).hostname or "").lower()
            if host and host in evidence_hosts:
                return match.group(0)

            links_stripped += 1
            unverified_claims.append(f"Removed ungrounded link URL: {target}")
            return f"{label} *(link unverified)*"

        audited_report = _MD_LINK_RE.sub(_audit_md_link, report)

        # Pass 2: Convert bare [SRC-008] / [SRC-003, SRC-007] into clickable links
        audited_report = _BARE_SRC_GROUP_RE.sub(
            lambda m: _resolve_src_list(m.group(1)),
            audited_report,
        )

        # Pass 3: Convert parenthetical (SRC-002) / (SRC-002, SRC-004) into clickable links
        audited_report = _PAREN_SRC_GROUP_RE.sub(
            lambda m: f"({_resolve_src_list(m.group(1))})",
            audited_report,
        )

        # Dynamically check cited Notification & Circular numbers against retrieved evidence corpus
        for num in dict.fromkeys(_NOTIF_CITE_RE.findall(audited_report)):
            if num not in evidence_corpus:
                unverified_claims.append(f"Notification No. {num} cited without direct text match in retrieved sources")

        for num in dict.fromkeys(_CIRC_CITE_RE.findall(audited_report)):
            if num not in evidence_corpus:
                unverified_claims.append(f"Circular No. {num} cited without direct text match in retrieved sources")

        tiers_used = list(dict.fromkeys(
            e.get("source_tier", "official") for e in evidence_records
        ))
        has_unverified_fallback = "unverified_fallback" in tiers_used

        notices: list[str] = []
        if has_unverified_fallback:
            notices.append(
                "Note: Primary official portals did not cover all points; fallback sources from the open web were consulted and should be cross-checked on CBIC/GST portals."
            )
        if unverified_claims:
            notices.append(
                f"Citation Audit: {len(unverified_claims)} citation(s) or external link(s) could not be matched directly in retrieved extracts and were stripped or flagged for verification."
            )

        if notices and audited_report:
            audited_report = audited_report.rstrip() + "\n\n---\n> " + "\n> ".join(notices)

        verified_citations = [
            {
                "source_id": e.get("source_id"),
                "title": e.get("title"),
                "url": e.get("url"),
                "authority": e.get("authority"),
                "source_tier": e.get("source_tier"),
                "fetch_status": e.get("fetch_status"),
                "section_or_rule": e.get("section_or_rule"),
                "verified": bool(e.get("verified")),
            }
            for e in evidence_records
        ]

        validation_result = {
            "verified_citations": verified_citations,
            "unverified_claims": unverified_claims,
            "source_count": len(verified_citations),
            "tiers_used": tiers_used,
            "links_resolved": links_resolved,
            "links_stripped": links_stripped,
            "validation_status": (
                "Passed" if verified_citations and not unverified_claims
                else ("Passed with Warnings" if verified_citations else "Unverified / Baseline Analysis")
            ),
        }

        dur = int((time.perf_counter() - t0) * 1000)
        trace.append(make_trace_entry(
            "validate_citations",
            state.search_tier,
            "ok",
            dur,
            {"resolved": links_resolved, "stripped": links_stripped, "unverified_claims": len(unverified_claims)},
        ))
        logger.info(f"Completed validate_citations in {dur}ms: {validation_result['validation_status']}")

        return {
            "current_step": "validate_citations",
            "final_report": audited_report,
            "citation_validation": validation_result,
            "execution_trace": trace,
        }
    finally:
        reset_log_context(tokens)

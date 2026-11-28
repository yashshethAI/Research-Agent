from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from backend.app.core.config import settings
from backend.app.tools.search.base import SearchResult, sanitize_search_query

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for",
    "from", "gst", "has", "have", "how", "if", "in", "into", "is", "it", "its",
    "may", "my", "of", "on", "or", "should", "such", "that", "the", "their", "this",
    "to", "under", "was", "we", "what", "when", "where", "which", "who", "will", "with",
}

_OPERATIVE_CUES = (
    "held that", "clarified", "provided that", "substituted", "inserted",
    "omitted", "w.e.f.", "effective from", "not entitled", "entitled to",
    "liable to", "exempt from", "reverse charge", "time limit", "retrospective",
)

_BOILERPLATE_CUES = (
    "cookie", "privacy policy", "terms of use", "skip to main content",
    "all rights reserved", "subscribe", "advertisement", "advocate for",
)

_SITE_TOKEN_RE = re.compile(r"\bsite:\S+", re.IGNORECASE)
_OR_NOISE_RE = re.compile(r"(?:^\s*(?:OR|AND)\s+|\s+(?:OR|AND)\s*$)", re.IGNORECASE)
_CITATION_RE = re.compile(
    r"(?:Section|Sec\.?|Rule|Notification\s+No\.?|Circular\s+No\.?)\s*[\dA-Za-z()/\-]+",
    re.IGNORECASE,
)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:[().\-/][a-z0-9]+)*", (text or "").lower()) if len(t) > 1]


def _extract_query_keywords(query: str, extra_terms: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Returns (keywords, exact_citation_phrases) extracted from query and plan terms."""
    combined = f"{query} {' '.join(extra_terms or [])}"
    citations = [c.strip().lower() for c in _CITATION_RE.findall(combined)]
    raw_tokens = _tokenize(combined)
    keywords = [t for t in dict.fromkeys(raw_tokens) if t not in _STOPWORDS]
    return keywords, list(dict.fromkeys(citations))


def normalize_llm_search_queries(
    queries: list[str],
    max_queries: int = 4,
    max_words: int = 10,
) -> list[str]:
    """Deterministically cleans LLM-generated queries: strips site: tokens, PII, and excess conversational filler."""
    cleaned_queries: list[str] = []
    for raw in queries:
        if not raw or not isinstance(raw, str):
            continue
        # 1. Strip any site: clauses inserted by small models so SearXNGAdapter controls tier domains
        q = _SITE_TOKEN_RE.sub("", raw)
        q = q.replace("(", " ").replace(")", " ") if "OR" in q else q
        q = _OR_NOISE_RE.sub(" ", q)
        q = re.sub(r"\s+", " ", q).strip(" ,;:-?")

        # 2. Sanitize PII before external transmission
        q = sanitize_search_query(q).strip()
        if not q:
            continue

        # 3. Trim overly long conversational queries while keeping citations/numbers
        words = q.split()
        if len(words) > max_words:
            kept = [w for w in words if w.lower() not in _STOPWORDS or any(c.isdigit() for c in w)]
            words = (kept or words)[:max_words]
            q = " ".join(words)

        if q and q.lower() not in {existing.lower() for existing in cleaned_queries}:
            cleaned_queries.append(q)
        if len(cleaned_queries) >= max_queries:
            break

    return cleaned_queries


_NON_CONTENT_PORTAL_PATHS = (
    "/services/login",
    "/services/searchtp",
    "/gst-number-search",
    "/registration/",
    "/payment/",
    "/help/returns",
    "/login",
    "/signin",
)

_PORTAL_HOMEPAGE_HOSTS = frozenset({
    "gst.gov.in",
    "www.gst.gov.in",
    "services.gst.gov.in",
    "einvoice1.gst.gov.in",
    "cbic.gov.in",
    "www.cbic.gov.in",
    "taxinformation.cbic.gov.in",
})


def is_utility_or_homepage_url(url: str) -> bool:
    """Returns True for generic portal homepages and login/payment/searchtp utility links."""
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if any(p.rstrip("/") in path for p in _NON_CONTENT_PORTAL_PATHS):
        return True
    if host in _PORTAL_HOMEPAGE_HOSTS and path in ("", "/"):
        return True
    return False

_BOT_BLOCK_MARKERS = (
    "cf-browser-verification",
    "cf-challenge",
    "attention required! | cloudflare",
    "verify you are human",
    "checking your browser before accessing",
    "just a moment...",
    "g-recaptcha",
    "hcaptcha",
    "turnstile",
    "access denied",
    "request blocked",
    "pardon our interruption",
    "enable cookies and javascript",
)


def rerank_search_results(
    results: list[SearchResult],
    query: str,
    target_terms: list[str] | None = None,
) -> list[SearchResult]:
    """Reranks merged search results across queries by source priority, keyword/citation overlap, and URL signal."""
    if not results:
        return []

    keywords, citations = _extract_query_keywords(query, target_terms)
    domain_counts: Counter[str] = Counter()
    scored: list[tuple[float, SearchResult]] = []

    for r in results:
        domain = (r.domain or urlparse(r.url).hostname or "").lower()
        tier, priority, _ = settings.get_domain_authority_info(domain)

        # 1. Authority base score (Tier 1 priority 1 > Tier 1 priority 2 > Tier 2 > Tier 3)
        tier_bonus = 6.0 if tier == "official" else (3.0 if tier == "verified_secondary" else 0.0)
        priority_bonus = max(0.0, 5.0 - float(priority))

        # 2. Query keyword & exact citation overlap in title + snippet
        haystack = f"{r.title} {r.snippet}".lower()
        kw_hits = sum(1 for kw in keywords if kw in haystack)
        cit_hits = sum(1 for cit in citations if cit in haystack)
        overlap_score = (kw_hits * 1.2) + (cit_hits * 3.0)

        # 3. Document quality signals
        url_lower = r.url.lower()
        doc_bonus = 0.0
        if url_lower.endswith(".pdf") or any(k in url_lower for k in ("circular", "notification", "judgment", "order", "act")):
            doc_bonus += 2.0
        if any(p in url_lower for p in _NON_CONTENT_PORTAL_PATHS):
            doc_bonus -= 5.0
        if len(url_lower.rstrip("/").split("/")) <= 3 and not r.snippet:
            doc_bonus -= 2.0

        # 4. Upstream search score contribution (bounded)
        upstream = min(max(float(r.score or 0.0), 0.0), 10.0) * 0.25

        # 5. Soft diversity penalty so one domain doesn't monopolize all fetch slots
        domain_counts[domain] += 1
        diversity_penalty = max(0, domain_counts[domain] - 2) * 1.5

        total_score = tier_bonus + priority_bonus + overlap_score + doc_bonus + upstream - diversity_penalty
        scored.append((total_score, r))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored]


_GENERIC_QUERY_WORDS = _STOPWORDS | {
    "latest", "recent", "update", "updates", "amendment", "amendments", "new",
    "current", "rule", "rules", "section", "act", "cgst", "igst", "sgst", "utgst",
    "india", "indian", "law", "position", "legal", "scheme", "2017", "2024", "2025", "2026",
}

_PORTAL_CHROME_RE = re.compile(
    r"(?:skip to main content|screen reader|light theme|dark theme|useful links|"
    r"contact gst council|page last updated on|all rights reserved|###\s*(?:archives|rti|faqs|useful links))",
    re.IGNORECASE,
)


def _strip_portal_chrome(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    kept = [
        ln for ln in lines
        if not _PORTAL_CHROME_RE.search(ln)
        and not re.match(r"^(?:english|hindi|rti|faqs|address\s*:|phone\s*:|e-?mail\s*:)", ln, re.IGNORECASE)
    ]
    return "\n".join(kept).strip()


def detect_bot_block(html_text: str, extracted_text: str) -> bool:
    """Detects WAF, Cloudflare, or CAPTCHA interstitial pages lacking substantive legal text."""
    clean_body = _strip_portal_chrome(extracted_text or "")
    body_l = clean_body.lower()
    if len(clean_body) >= 1200 or any(
        cue in body_l for cue in ("cgst act", "igst act", "notification no", "circular no")
    ):
        return False

    combined_l = f"{(html_text or '')[:12000]}\n{body_l}".lower()
    return any(marker in combined_l for marker in _BOT_BLOCK_MARKERS)


def detect_spa_shell(html_text: str, extracted_text: str) -> bool:
    """Detects JS-rendered SPA shells or boilerplate-only portal pages lacking substantive content."""
    clean_body = _strip_portal_chrome(extracted_text or "")
    text_len = len(clean_body)
    if text_len >= 250:
        return False

    html_l = (html_text or "").lower()
    spa_markers = (
        "<app-root",
        "id=\"root\"",
        "id=\"app\"",
        "enable javascript",
        "javascript is required",
        "loading...",
    )
    if any(m in html_l for m in spa_markers):
        return True
    return text_len < 50


def _split_into_chunks(text: str, chunk_size: int = 650) -> list[str]:
    """Splits text along paragraph, heading, and page boundaries into ~650-char chunks."""
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size * 1.5:
            # Split long single paragraphs cleanly at sentence boundaries
            if current:
                chunks.append(current.strip())
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", para)
            buf = ""
            for sent in sentences:
                if buf and len(buf) + len(sent) + 1 > chunk_size:
                    chunks.append(buf.strip())
                    buf = sent
                else:
                    buf = f"{buf} {sent}".strip() if buf else sent
            if buf:
                chunks.append(buf.strip())
            continue

        if current and len(current) + len(para) + 2 > chunk_size:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}".strip() if current else para

    if current:
        chunks.append(current.strip())

    return chunks


def extract_relevant_passages(
    text: str,
    query: str,
    target_terms: list[str] | None = None,
    max_total_chars: int = 1500,
) -> str:
    """Selects header + top BM25/IDF-weighted query-relevant passages in reading order."""
    clean_text = (text or "").strip()
    if not clean_text:
        return ""
    if len(clean_text) <= max_total_chars:
        return clean_text

    chunks = _split_into_chunks(clean_text, chunk_size=650)
    if not chunks:
        return clean_text[:max_total_chars].strip()

    keywords, citations = _extract_query_keywords(query, target_terms)
    num_chunks = len(chunks)

    # Compute document frequency across chunks for BM25/IDF weighting
    chunk_tokens_list = [Counter(_tokenize(ch)) for ch in chunks]
    df: Counter[str] = Counter()
    for tok_counts in chunk_tokens_list:
        for kw in keywords:
            if tok_counts.get(kw, 0) > 0:
                df[kw] += 1

    avg_len = sum(sum(c.values()) for c in chunk_tokens_list) / max(1, num_chunks)
    k1 = 1.2
    b = 0.75

    scored_chunks: list[tuple[float, int]] = []
    for idx, ch in enumerate(chunks):
        ch_lower = ch.lower()
        tok_counts = chunk_tokens_list[idx]
        doc_len = max(1, sum(tok_counts.values()))

        bm25 = 0.0
        for kw in keywords:
            tf = tok_counts.get(kw, 0)
            if tf > 0:
                idf = math.log((num_chunks - df[kw] + 0.5) / (df[kw] + 0.5) + 1.0)
                tf_norm = (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * (doc_len / avg_len)))
                bm25 += idf * tf_norm

        cit_score = sum(4.0 for cit in citations if cit in ch_lower)
        cue_bonus = sum(0.8 for cue in _OPERATIVE_CUES if cue in ch_lower)
        boilerplate_penalty = sum(1.5 for bp in _BOILERPLATE_CUES if bp in ch_lower)

        total = bm25 + cit_score + cue_bonus - boilerplate_penalty
        scored_chunks.append((total, idx))

    # Reserve short opening header (~200 chars) if not already in top chunks
    opening_header = chunks[0][:200].strip()
    positive_chunks = [(score, idx) for score, idx in scored_chunks if score > 0]
    if not positive_chunks:
        return clean_text[:max_total_chars].strip()

    positive_chunks.sort(key=lambda x: x[0], reverse=True)
    selected_indices: list[int] = []
    budget_used = 0 if positive_chunks[0][1] == 0 else len(opening_header) + 6

    for _, idx in positive_chunks:
        chunk_len = len(chunks[idx])
        if selected_indices and budget_used + chunk_len + 6 > max_total_chars:
            continue
        selected_indices.append(idx)
        budget_used += chunk_len + 6
        if len(selected_indices) >= 3 or budget_used >= max_total_chars:
            break

    selected_indices.sort()
    parts: list[str] = []
    if 0 not in selected_indices and opening_header:
        parts.append(opening_header)
    for idx in selected_indices:
        parts.append(chunks[idx])

    assembled = "\n...\n".join(parts).strip()
    return assembled[:max_total_chars].strip()


def _detect_legal_references(text: str) -> str:
    notifs_found = re.findall(
        r"Notification\s+No\.?\s*\d+/\d{4}[-\s]*(?:Central\s+Tax(?:\s*\(Rate\))?|Integrated\s+Tax(?:\s*\(Rate\))?|Compensation\s+Cess(?:\s*\(Rate\))?|Union\s+Territory\s+Tax(?:\s*\(Rate\))?|CT(?:\s*\(Rate\))?|IT(?:\s*\(Rate\))?)?",
        text,
        flags=re.IGNORECASE,
    )
    sections_found = re.findall(r"Section\s+\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))*", text, flags=re.IGNORECASE)
    rules_found = re.findall(r"Rule\s+\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))*", text, flags=re.IGNORECASE)
    circulars_found = re.findall(r"Circular\s+No\.?\s*[\d/]+(?:\-GST)?", text, flags=re.IGNORECASE)

    if notifs_found:
        ref = ", ".join(dict.fromkeys(n.strip() for n in notifs_found[:2]))
        if sections_found:
            ref += f" (with {', '.join(dict.fromkeys(sections_found[:2]))})"
        return ref
    if sections_found:
        return ", ".join(dict.fromkeys(sections_found[:3]))
    if rules_found:
        return ", ".join(dict.fromkeys(rules_found[:3]))
    if circulars_found:
        return ", ".join(dict.fromkeys(circulars_found[:2]))
    return "General Statutory Framework"


def _detect_document_date(text: str) -> str:
    match = re.search(
        r"\b(?:\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December),?\s+20\d{2}|\d{2}[-/]\d{2}[-/]20\d{2})\b",
        text[:4000],
        flags=re.IGNORECASE,
    )
    return match.group(0) if match else "Date Not Stated in Extract"


def compile_relevant_evidence(
    parsed_docs: list[dict[str, Any]],
    query: str,
    research_plan: dict[str, Any] | None = None,
    tier: str = "official",
    start_index: int = 1,
    max_excerpt_chars: int = 2200,
) -> list[dict[str, Any]]:
    """Compiles structured, query-relevant evidence records with truthful tier & verification flags."""
    plan = research_plan or {}
    target_terms = [
        *(plan.get("target_sections") or []),
        *(plan.get("target_rules") or []),
        *(plan.get("target_acts") or []),
    ]

    records: list[dict[str, Any]] = []
    for offset, doc in enumerate(parsed_docs):
        idx = start_index + offset
        url = doc.get("url") or ""
        domain = (urlparse(url).hostname or "").lower()
        doc_tier = doc.get("source_tier") or tier
        _, _, authority = settings.get_domain_authority_info(domain)
        if doc_tier == "unverified_fallback":
            authority = f"Open Web Fallback ({domain or 'web'}) [Unverified]"

        full_text = doc.get("text") or ""
        fetch_status = doc.get("fetch_status") or "fetched"
        excerpt = extract_relevant_passages(
            full_text,
            query=query,
            target_terms=target_terms,
            max_total_chars=max_excerpt_chars,
        )
        legal_ref = _detect_legal_references(excerpt or full_text[:4000])
        doc_date = _detect_document_date(full_text)
        is_verified = (fetch_status == "fetched") and (doc_tier != "unverified_fallback")

        records.append({
            "source_id": f"SRC-{idx:03d}",
            "title": doc.get("title") or f"GST Source {idx}",
            "url": url,
            "authority": authority,
            "source_tier": doc_tier,
            "fetch_status": fetch_status,
            "document_type": doc.get("doc_type", "Statutory Source"),
            "section_or_rule": legal_ref,
            "excerpt": excerpt,
            "document_date": doc_date,
            "sha256_hash": doc.get("sha256_hash") or "",
            "verified": is_verified,
        })

    return records


def is_evidence_sufficient(
    evidence_records: list[dict[str, Any]],
    query: str,
    research_plan: dict[str, Any] | None = None,
    min_sources: int | None = None,
) -> tuple[bool, str]:
    """Determines whether retrieved evidence is sufficient or should escalate to a fallback tier."""
    threshold = min_sources if min_sources is not None else settings.MIN_OFFICIAL_SOURCES_SUFFICIENT
    usable = [
        e for e in evidence_records
        if e.get("fetch_status") == "fetched" and len((e.get("excerpt") or "").strip()) >= 150
    ]

    if not usable:
        if evidence_records and all(e.get("fetch_status") == "spa_shell" for e in evidence_records):
            return False, "Only JS-rendered SPA shells were returned; escalating source tier."
        return False, "No full fetched documents with substantive text retrieved yet."

    plan = research_plan or {}
    target_terms = [
        *(plan.get("target_sections") or []),
        *(plan.get("target_rules") or []),
    ]
    keywords, citations = _extract_query_keywords(query, target_terms)
    specific_keywords = [kw for kw in keywords if kw not in _GENERIC_QUERY_WORDS] or keywords
    query_wants_customs = any(k in (query or "").lower() for k in ("customs", "sez", "icegate", "dgft", "import", "export"))

    relevant_count = 0
    for rec in usable:
        text_l = f"{rec.get('title', '')} {rec.get('excerpt', '')}".lower()
        if not query_wants_customs and "customs act" in text_l and "cgst" not in text_l and "igst" not in text_l:
            continue
        kw_matches = sum(1 for kw in specific_keywords if kw in text_l)
        cit_matches = sum(1 for cit in citations if cit in text_l)
        if cit_matches >= 1 or kw_matches >= min(2, max(1, len(specific_keywords))):
            relevant_count += 1

    if relevant_count >= threshold:
        return True, f"Found {relevant_count} relevant full-text sources."
    if relevant_count >= 1 and any(e.get("source_tier") == "official" for e in usable):
        # Single strong official match with clear citation hit is often enough if threshold=1,
        # otherwise escalate once to check secondary sources when threshold >= 2.
        if threshold <= 1:
            return True, "Found authoritative official statutory match."

    return False, (
        f"Only {relevant_count} relevant full-text source(s) matched (need {threshold}); "
        "escalating to fallback tier."
    )

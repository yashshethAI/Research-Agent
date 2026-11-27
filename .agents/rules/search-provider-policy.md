# Search Provider & Official Source Discovery Policy

## Local-First Search Architecture
1. **SearXNG Standard**: Use `SearXNGSearchAdapter` (`SEARCH_PROVIDER=searxng`, `SEARXNG_BASE_URL`) for live search and `MockSearchAdapter` (`SEARCH_PROVIDER=mock`) for offline/deterministic testing. Do not reintroduce paid external search SaaS dependencies.
2. **PII Sanitization Invariant**: All search queries must pass through `sanitize_search_query()` before external HTTP transmission so client GSTINs, PANs, emails, and phone numbers are redacted.

## Domain Allowlist Enforcement
3. **3-Tier Official-First Search & Fallback Policy**:
   - **Tier 1 (`official_sources`)**: Always search the configured official source domains in `config/sources.yaml` first. Stop without hitting fallback tiers if sufficient usable official evidence is retrieved.
   - **Tier 2 (`verified_secondary_sources`)**: Search configured secondary legal/tax portals only when Tier 1 returns empty, JS-SPA shells, or insufficient coverage.
   - **Tier 3 (`unverified_fallback`)**: Search general web blogs only as a last resort when both Tier 1 and Tier 2 are insufficient and `ALLOW_UNVERIFIED_FALLBACK=true` in `.env`, while still enforcing SSRF private-IP checks and `blocked_domains` filtering.
   - Always tag every retrieved record with `source_tier` and disclose fallback/unverified status transparently.

## Testing & Configuration Synchronization
4. **Hermetic Tests**: Automated tests under `tests/` must mock network calls (`httpx.AsyncClient` / `health_check`) or use `MockSearchAdapter` so `pytest` passes reliably even when SearXNG is offline.
5. **Cross-Layer Sync**: Whenever search settings or providers change, update `backend/app/core/config.py`, `.env.example`, `/api/v1/health` & `/api/v1/config/status`, `frontend/components/sidebar.py`, `README.md`, and `tests/test_config.py` together.

## Dynamic Query Planning & Grounding Invariants
6. **No Static Query Templates or Blanket Recency Filters**: Generate search queries dynamically from extracted legal intent and persisted conversation history. Never apply `time_range="year"` based on generic keywords like `"amendment"` or `"current"`.
7. **Query-Aware Passage Extraction & Small-Model (<26B) Grounding**: Rerank search results by authority tier and relevance before fetching, select query-relevant passages instead of head truncation (`text[:1500]`), keep LLM context capped and free of `<think>` leakage, and resolve/audit `[Label](SRC-XXX)` links and citations post-generation dynamically.

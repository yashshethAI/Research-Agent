# Search Provider & Official Source Discovery Policy

## Local-First Search Architecture
1. **SearXNG Standard**: Use `SearXNGSearchAdapter` (`SEARCH_PROVIDER=searxng`, `SEARXNG_BASE_URL`) for live search and `MockSearchAdapter` (`SEARCH_PROVIDER=mock`) for offline/deterministic testing. Do not reintroduce paid external search SaaS dependencies.
2. **PII Sanitization Invariant**: All search queries must pass through `sanitize_search_query()` before external HTTP transmission so client GSTINs, PANs, emails, and phone numbers are redacted.

## Domain Allowlist Enforcement
3. **Dual-Layer Filtering**: Because SearXNG has no native `include_domains` payload option:
   - Inject concise priority/chunked `site:` clauses for queries lacking `site:` so upstream engines return official GST/judicial results.
   - Always validate every returned URL through `source_validator.validate_url()` against `config/sources.yaml`.

## Testing & Configuration Synchronization
4. **Hermetic Tests**: Automated tests under `tests/` must mock network calls (`httpx.AsyncClient` / `health_check`) or use `MockSearchAdapter` so `pytest` passes reliably even when SearXNG is offline.
5. **Cross-Layer Sync**: Whenever search settings or providers change, update `backend/app/core/config.py`, `.env.example`, `/api/v1/health` & `/api/v1/config/status`, `frontend/components/sidebar.py`, `README.md`, and `tests/test_config.py` together.

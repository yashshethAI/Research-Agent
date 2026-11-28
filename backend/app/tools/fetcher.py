from __future__ import annotations

import asyncio
import logging
import sys
from urllib.parse import urlparse, urlunparse

import httpx

from backend.app.core.config import settings
from backend.app.storage.source_cache import SourceCacheStorage, source_cache_storage
from backend.app.tools.source_validator import SourceSecurityError, source_validator

logger = logging.getLogger(__name__)

# Try importing playwright for conditional SPA rendering
try:
    from playwright.async_api import async_playwright

    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False
    logger.info("playwright not installed; SPA rendering fallback is unavailable.")

# Tier 1/2 domains allowed for Playwright rendering (anti-SSRF safeguard)
_PLAYWRIGHT_ALLOWED_DOMAINS = frozenset(
    d.lower() for d in [*settings.official_domains, *settings.verified_secondary_domains]
)

_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_TRANSIENT_RETRY_DELAYS = (0.5, 1.5)


def _is_gov_domain(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".gov.in") or host == "gov.in" or host.endswith(".nic.in") or host == "nic.in"


def _strip_www_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host.lower().startswith("www."):
        return None
    bare_host = host[4:]
    if parsed.port:
        new_netloc = f"{bare_host}:{parsed.port}"
    else:
        new_netloc = bare_host
    return urlunparse(parsed._replace(netloc=new_netloc))


class FetchedDocument:
    def __init__(
        self,
        url: str,
        content: bytes,
        content_type: str,
        status_code: int,
        sha256_hash: str,
        file_path: str,
    ):
        self.url = url
        self.content = content
        self.content_type = content_type
        self.status_code = status_code
        self.sha256_hash = sha256_hash
        self.file_path = file_path


class SafeFetcher:
    """Asynchronously fetches web pages and PDF documents from official sources with SSRF guards."""

    def __init__(
        self,
        timeout: int | None = None,
        max_size_mb: int | None = None,
        cache_storage: SourceCacheStorage | None = None,
    ):
        self.timeout = timeout or settings.SOURCE_FETCH_TIMEOUT
        self.max_size_bytes = (max_size_mb or settings.MAX_SOURCE_SIZE_MB) * 1024 * 1024
        self._cache_storage = cache_storage

    def _get_cache(self) -> SourceCacheStorage:
        return self._cache_storage or source_cache_storage

    async def _request_with_resilience(
        self,
        current_url: str,
        headers: dict[str, str],
        verify_ssl: bool,
        allow_unverified: bool,
    ) -> tuple[httpx.Response, str, bool]:
        """Executes HTTP GET with transient retries, apex www-strip on hostname mismatch, and gov.in SSL fallback."""
        attempts = len(_TRANSIENT_RETRY_DELAYS) + 1
        active_url = current_url
        active_verify = verify_ssl
        tried_apex = False

        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=False,
                    verify=active_verify,
                ) as client:
                    resp = await client.get(active_url, headers=headers)
                    return resp, active_url, active_verify
            except httpx.ConnectError as e:
                err_str = str(e)
                if "CERTIFICATE_VERIFY_FAILED" in err_str:
                    if not tried_apex and "hostname mismatch" in err_str.lower():
                        apex_url = _strip_www_from_url(active_url)
                        if apex_url:
                            try:
                                source_validator.assert_valid_url(apex_url, allow_unverified=allow_unverified)
                                logger.warning(
                                    f"SSL hostname mismatch for '{active_url}'; retrying allowlisted apex '{apex_url}' with strict TLS."
                                )
                                active_url = apex_url
                                active_verify = True
                                tried_apex = True
                                continue
                            except Exception:
                                pass

                    if active_verify and _is_gov_domain(active_url):
                        logger.warning(
                            f"SSL verify failed for official government portal '{active_url}'. "
                            "Retrying with relaxed SSL verify for approved official domain."
                        )
                        active_verify = False
                        continue
                    raise

                if attempt < len(_TRANSIENT_RETRY_DELAYS):
                    delay = _TRANSIENT_RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Transient ConnectError fetching '{active_url}' (attempt {attempt + 1}/{attempts}); retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except httpx.TimeoutException:
                if attempt < len(_TRANSIENT_RETRY_DELAYS):
                    delay = _TRANSIENT_RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Timeout fetching '{active_url}' (attempt {attempt + 1}/{attempts}); retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        raise httpx.ConnectError(f"Exhausted connection attempts for {active_url}")

    async def fetch(self, url: str, allow_unverified: bool = False) -> FetchedDocument:
        """Validates and fetches a document safely, reusing recent cached downloads within TTL."""
        source_validator.assert_valid_url(url, allow_unverified=allow_unverified)

        cache = self._get_cache()
        cached = cache.get_recent_document_by_url(
            url,
            max_age_seconds=settings.SOURCE_CACHE_TTL_SECONDS,
        )
        if cached is not None:
            content_bytes, meta, path = cached
            logger.debug(f"URL cache hit for '{url}'")
            return FetchedDocument(
                url=meta.get("url", url),
                content=content_bytes,
                content_type=meta.get("content_type", "text/html"),
                status_code=int(meta.get("http_status", 200)),
                sha256_hash=meta.get("hash", ""),
                file_path=str(path),
            )

        headers = {
            "User-Agent": _BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }

        current_url = url
        redirect_count = 0
        max_redirects = 5
        verify_ssl = True

        while redirect_count <= max_redirects:
            # Re-validate before each hop
            source_validator.assert_valid_url(current_url, allow_unverified=allow_unverified)

            resp, current_url, verify_ssl = await self._request_with_resilience(
                current_url=current_url,
                headers=headers,
                verify_ssl=verify_ssl,
                allow_unverified=allow_unverified,
            )

            if resp.status_code in (301, 302, 303, 307, 308):
                redirect_count += 1
                location = resp.headers.get("location")
                if not location:
                    raise SourceSecurityError(f"Redirect status {resp.status_code} with no Location header.")
                parsed_next = httpx.URL(current_url).join(location)
                current_url = str(parsed_next)
                continue

            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"Failed fetching {url}: HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )

            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > self.max_size_bytes:
                raise ValueError(f"Content length {content_length} exceeds limit of {self.max_size_bytes} bytes.")

            content_bytes = resp.content
            if len(content_bytes) > self.max_size_bytes:
                raise ValueError(f"Fetched content size exceeds limit of {self.max_size_bytes} bytes.")

            content_type = resp.headers.get("content-type", "").lower()
            domain = urlparse(current_url).hostname or "unknown"
            extension = "pdf" if "pdf" in content_type or current_url.lower().endswith(".pdf") else "html"

            doc_hash, path = cache.save_document(
                url=current_url,
                domain=domain,
                content=content_bytes,
                extension=extension,
                metadata={"content_type": content_type, "http_status": resp.status_code},
            )
            if current_url != url:
                # Also index the originally requested URL (e.g. www. -> apex fallback or redirect)
                try:
                    cache._save_url_index(
                        url,
                        doc_hash,
                        path,
                        {"content_type": content_type, "http_status": resp.status_code},
                    )
                except OSError:
                    pass

            return FetchedDocument(
                url=current_url,
                content=content_bytes,
                content_type=content_type,
                status_code=resp.status_code,
                sha256_hash=doc_hash,
                file_path=str(path),
            )

        raise SourceSecurityError("Exceeded maximum redirects (5) during fetch.")

    def _is_playwright_allowed(self, url: str) -> bool:
        """Validates Tier 1/2 domain allowlist and anti-SSRF rules prior to browser navigation."""
        hostname = (urlparse(url).hostname or "").lower()
        if not any(hostname == d or hostname.endswith("." + d) for d in _PLAYWRIGHT_ALLOWED_DOMAINS):
            logger.warning(f"Playwright render denied for non-allowlisted domain: {hostname}")
            return False
        try:
            source_validator.assert_valid_url(url, allow_unverified=False)
            return True
        except Exception:
            logger.warning(f"Playwright SSRF check failed for {url}")
            return False

    async def _render_urls_with_playwright(self, urls: list[str]) -> dict[str, str]:
        """Renders up to len(urls) pages concurrently inside one headless Chromium browser.

        Runs on an isolated ProactorEventLoop inside a worker thread on Windows so
        Playwright's subprocess transport works even when Uvicorn uses SelectorEventLoop.
        """

        async def _render_page(browser, url: str) -> tuple[str, str | None]:
            context = None
            if hasattr(browser, "new_context"):
                context = await browser.new_context(
                    user_agent=_BROWSER_USER_AGENT,
                    locale="en-IN",
                    ignore_https_errors=_is_gov_domain(url),
                )
                page = await context.new_page()
            else:
                page = await browser.new_page()

            try:
                if hasattr(page, "route"):
                    async def _abort_heavy_assets(route):
                        if route.request.resource_type in {"image", "media", "font"}:
                            await route.abort()
                        else:
                            await route.continue_()

                    await page.route("**/*", _abort_heavy_assets)

                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                if hasattr(page, "wait_for_load_state"):
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                try:
                    await page.wait_for_selector("main, article, p, table, h1, h2", timeout=4000)
                except Exception:
                    await page.wait_for_timeout(1500)

                if hasattr(page, "evaluate"):
                    try:
                        text_len = await page.evaluate(
                            "() => (document.body && document.body.innerText || '').trim().length"
                        )
                        if text_len < 300:
                            await page.wait_for_timeout(2000)
                    except Exception:
                        pass
                return url, await page.content()
            except Exception as e:
                logger.error(f"Playwright rendering failed for {url}: {e}")
                return url, None
            finally:
                await page.close()
                if context is not None:
                    await context.close()

        async def _run_batch() -> dict[str, str]:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    pairs = await asyncio.gather(*[_render_page(browser, u) for u in urls])
                    return {u: html for u, html in pairs if html}
                finally:
                    await browser.close()

        def _thread_entry() -> dict[str, str]:
            if sys.platform == "win32":
                loop = asyncio.ProactorEventLoop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(_run_batch())
                finally:
                    loop.close()
            return asyncio.run(_run_batch())

        return await asyncio.to_thread(_thread_entry)

    async def fetch_rendered_html_batch(
        self, urls: list[str], max_urls: int = 3
    ) -> dict[str, FetchedDocument]:
        """Renders up to max_urls JS-heavy Tier 1/2 SPA pages in a single Chromium session."""
        if not urls:
            return {}

        # Preserve instance-level monkeypatches on fetch_rendered_html in tests
        if "fetch_rendered_html" in self.__dict__:
            out: dict[str, FetchedDocument] = {}
            for u in urls[:max_urls]:
                doc = await self.fetch_rendered_html(u)
                if doc is not None:
                    out[u] = doc
            return out

        if not _HAS_PLAYWRIGHT:
            logger.warning("Playwright not installed; cannot render SPA pages.")
            return {}

        eligible = [u for u in dict.fromkeys(urls) if self._is_playwright_allowed(u)][:max_urls]
        if not eligible:
            return {}

        try:
            rendered_map = await self._render_urls_with_playwright(eligible)
        except Exception as e:
            logger.error(f"Playwright batch rendering failed: {e}")
            return {}

        cache = self._get_cache()
        docs: dict[str, FetchedDocument] = {}
        for url, rendered_html in rendered_map.items():
            content_bytes = rendered_html.encode("utf-8")
            if len(content_bytes) > self.max_size_bytes:
                logger.warning(f"Playwright rendered content too large for {url}")
                continue
            domain = urlparse(url).hostname or "unknown"
            doc_hash, path = cache.save_document(
                url=url,
                domain=domain,
                content=content_bytes,
                extension="html",
                metadata={"content_type": "text/html", "fetch_method": "playwright"},
            )
            docs[url] = FetchedDocument(
                url=url,
                content=content_bytes,
                content_type="text/html",
                status_code=200,
                sha256_hash=doc_hash,
                file_path=str(path),
            )
        return docs

    async def fetch_rendered_html(self, url: str) -> FetchedDocument | None:
        """Renders a JS-heavy SPA page using headless Playwright Chromium.

        Strictly limited to Tier 1/2 allowlisted domains with anti-SSRF checks.
        Returns None if Playwright is unavailable or the domain is not allowlisted.
        """
        rendered = await self.fetch_rendered_html_batch([url], max_urls=1)
        return rendered.get(url)


# Global instance
safe_fetcher = SafeFetcher()

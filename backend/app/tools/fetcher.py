from __future__ import annotations

import asyncio
import logging
import sys
from urllib.parse import urlparse

import httpx

from backend.app.core.config import settings
from backend.app.storage.source_cache import source_cache_storage
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
    ):
        self.timeout = timeout or settings.SOURCE_FETCH_TIMEOUT
        self.max_size_bytes = (max_size_mb or settings.MAX_SOURCE_SIZE_MB) * 1024 * 1024

    async def fetch(self, url: str, allow_unverified: bool = False) -> FetchedDocument:
        """Validates and fetches a document safely."""
        source_validator.assert_valid_url(url, allow_unverified=allow_unverified)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GST-Legal-Research-Agent/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            verify=True,
        ) as client:
            current_url = url
            redirect_count = 0
            max_redirects = 5

            while redirect_count <= max_redirects:
                # Re-validate before each hop
                source_validator.assert_valid_url(current_url, allow_unverified=allow_unverified)

                try:
                    resp = await client.get(current_url, headers=headers)
                except httpx.ConnectError as e:
                    # Many Indian official portals (CBIC/eCourts) use Indian NIC/CCA certificates
                    # not present in standard Linux certifi stores.
                    if "CERTIFICATE_VERIFY_FAILED" in str(e) and (
                        "gov.in" in current_url or "nic.in" in current_url
                    ):
                        logger.warning(
                            f"SSL verify failed for official government portal '{current_url}'. "
                            "Retrying with relaxed SSL verify for approved official domain."
                        )
                        async with httpx.AsyncClient(
                            timeout=self.timeout, follow_redirects=False, verify=False
                        ) as fallback_client:
                            resp = await fallback_client.get(current_url, headers=headers)
                    else:
                        raise

                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_count += 1
                    location = resp.headers.get("location")
                    if not location:
                        raise SourceSecurityError(f"Redirect status {resp.status_code} with no Location header.")
                    # Handle relative redirects
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

                doc_hash, path = source_cache_storage.save_document(
                    url=current_url,
                    domain=domain,
                    content=content_bytes,
                    extension=extension,
                    metadata={"content_type": content_type, "http_status": resp.status_code},
                )

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
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                try:
                    await page.wait_for_selector("p, table, h1, h2", timeout=5000)
                except Exception:
                    await page.wait_for_timeout(2000)
                return url, await page.content()
            except Exception as e:
                logger.error(f"Playwright rendering failed for {url}: {e}")
                return url, None
            finally:
                await page.close()

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
        self, urls: list[str], max_urls: int = 2
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

        docs: dict[str, FetchedDocument] = {}
        for url, rendered_html in rendered_map.items():
            content_bytes = rendered_html.encode("utf-8")
            if len(content_bytes) > self.max_size_bytes:
                logger.warning(f"Playwright rendered content too large for {url}")
                continue
            domain = urlparse(url).hostname or "unknown"
            doc_hash, path = source_cache_storage.save_document(
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

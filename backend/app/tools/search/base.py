from __future__ import annotations

import abc
import re

from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    domain: str
    source_id: str | None = None
    score: float = 1.0


class SearchNotConfiguredError(Exception):
    """Raised when the search provider is unconfigured or missing credentials."""


class BaseSearchProvider(abc.ABC):
    """Abstract interface for GST legal search providers."""

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        domains: list[str] | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Performs a domain-restricted search on official GST resources."""


def sanitize_search_query(query: str) -> str:
    """Sanitizes user search queries before sending to third-party search engines.

    Removes client PANs, GSTINs, phone numbers, and email addresses.
    """
    if not query:
        return ""

    sanitized = query

    # 1. Mask 15-digit Indian GSTIN
    # Example: 27AABCU9603R1ZN
    gstin_pattern = r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b"
    sanitized = re.sub(gstin_pattern, "[REDACTED_GSTIN]", sanitized, flags=re.IGNORECASE)

    # 2. Mask 10-digit Indian Income Tax PAN
    # Example: ABCDE1234F
    pan_pattern = r"\b[A-Z]{5}\d{4}[A-Z]{1}\b"
    sanitized = re.sub(pan_pattern, "[REDACTED_PAN]", sanitized, flags=re.IGNORECASE)

    # 3. Mask email addresses
    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    sanitized = re.sub(email_pattern, "[REDACTED_EMAIL]", sanitized)

    # 4. Mask 10-digit Indian mobile numbers
    phone_pattern = r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b"
    sanitized = re.sub(phone_pattern, "[REDACTED_PHONE]", sanitized)

    return sanitized

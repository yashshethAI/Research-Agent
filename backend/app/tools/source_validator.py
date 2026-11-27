from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class SourceSecurityError(Exception):
    """Raised when a URL violates SSRF, allowlist, or safety policies."""


class SourceValidator:
    """Enforces SSRF prevention, private network isolation, and tiered domain allowlists."""

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        enforce_official: bool | None = None,
        blocked_domains: list[str] | None = None,
    ):
        self.enforce_official = (
            enforce_official if enforce_official is not None else settings.ENFORCE_OFFICIAL_DOMAINS
        )
        self.allowed_domains = allowed_domains if allowed_domains is not None else settings.allowed_domains
        self.blocked_domains = blocked_domains if blocked_domains is not None else settings.blocked_domains

    def is_ip_private_or_restricted(self, ip_str: str) -> bool:
        """Checks if an IP address belongs to private, loopback, or reserved networks."""
        try:
            ip = ipaddress.ip_address(ip_str)
            return (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            )
        except ValueError:
            return True

    @staticmethod
    def _matches_domain_list(hostname: str, domains: list[str]) -> bool:
        for domain in domains:
            d = domain.strip().lower()
            if d and (hostname == d or hostname.endswith("." + d)):
                return True
        return False

    def validate_url(self, url: str, allow_unverified: bool = False) -> tuple[bool, str]:
        """Validates that a URL is safe to fetch.

        Always checks scheme, blocked domains, obsolete paths, and public IP resolution (anti-SSRF).
        Enforces the configured allowlist unless allow_unverified=True (explicit Tier 3 fallback).
        """
        if not url:
            return False, "URL is empty"

        try:
            parsed = urlparse(url)
        except Exception as e:
            return False, f"Invalid URL structure: {e}"

        if parsed.scheme not in ("http", "https"):
            return False, f"Unsupported scheme '{parsed.scheme}'. Only http and https allowed."

        hostname = parsed.hostname
        if not hostname:
            return False, "URL lacks a valid hostname."

        hostname = hostname.lower()

        # 1. Blocked Domains Check (applies across all tiers including Tier 3 open-web fallback)
        if self.blocked_domains and self._matches_domain_list(hostname, self.blocked_domains):
            return False, f"Domain '{hostname}' is in the blocked domains list."

        # 2. Tiered Domain Allowlist Check (bypassed only during explicit Tier 3 fallback)
        if self.enforce_official and not allow_unverified:
            if not self._matches_domain_list(hostname, self.allowed_domains):
                return False, f"Domain '{hostname}' is not in the approved GST domain registry."

        # 3. Exclude obsolete prototype or draft return utilities
        path_lower = (parsed.path or "").lower()
        if "offlineutilities/returns/newgstreturn" in path_lower or "prototype" in path_lower:
            return False, f"URL path '{parsed.path}' is an obsolete prototype or draft utility, not enacted law."

        # 4. SSRF Check: Resolve hostname to IP and check if private
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for entry in addr_info:
                ip_str = entry[4][0]
                if self.is_ip_private_or_restricted(ip_str):
                    return False, f"SSRF Protection: Hostname '{hostname}' resolves to private/restricted IP '{ip_str}'."
        except socket.gaierror:
            return False, f"DNS resolution failed for hostname '{hostname}'."
        except Exception as e:
            return False, f"Error validating host IP: {e}"

        return True, "URL is valid and permitted."

    def assert_valid_url(self, url: str, allow_unverified: bool = False) -> None:
        valid, reason = self.validate_url(url, allow_unverified=allow_unverified)
        if not valid:
            raise SourceSecurityError(reason)


# Global instance
source_validator = SourceValidator()

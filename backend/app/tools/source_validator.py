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
    """Enforces SSRF prevention, private network isolation, and official domain allowlists."""

    def __init__(self, allowed_domains: list[str] | None = None, enforce_official: bool | None = None):
        self.enforce_official = (
            enforce_official if enforce_official is not None else settings.ENFORCE_OFFICIAL_DOMAINS
        )
        self.allowed_domains = allowed_domains or settings.allowed_domains

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

    def validate_url(self, url: str) -> tuple[bool, str]:
        """Validates that a URL is safe to fetch: valid HTTP/HTTPS scheme,

        public IP resolution (anti-SSRF), and belongs to official allowlist.
        Returns (is_valid, reason).
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

        # 1. Domain Allowlist Check
        if self.enforce_official:
            matched = False
            for allowed in self.allowed_domains:
                if hostname == allowed or hostname.endswith("." + allowed):
                    matched = True
                    break
            if not matched:
                return False, f"Domain '{hostname}' is not in the approved official GST domain registry."

        # 2. SSRF Check: Resolve hostname to IP and check if private
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

    def assert_valid_url(self, url: str) -> None:
        valid, reason = self.validate_url(url)
        if not valid:
            raise SourceSecurityError(reason)


# Global instance
source_validator = SourceValidator()

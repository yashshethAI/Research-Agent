from __future__ import annotations

from backend.app.tools.search.base import sanitize_search_query
from backend.app.tools.source_validator import SourceValidator


def test_private_ip_detection():
    validator = SourceValidator()
    assert validator.is_ip_private_or_restricted("127.0.0.1") is True
    assert validator.is_ip_private_or_restricted("10.0.0.5") is True
    assert validator.is_ip_private_or_restricted("192.168.1.100") is True
    assert validator.is_ip_private_or_restricted("169.254.169.254") is True
    assert validator.is_ip_private_or_restricted("8.8.8.8") is False


def test_invalid_scheme_rejected():
    validator = SourceValidator()
    valid, reason = validator.validate_url("ftp://taxinformation.cbic.gov.in/doc.pdf")
    assert valid is False
    assert "Unsupported scheme" in reason


def test_non_allowlisted_domain_rejected_by_default():
    validator = SourceValidator(allowed_domains=["taxinformation.cbic.gov.in"], enforce_official=True)
    valid, reason = validator.validate_url("https://random-unverified-blog.com/gst-update")
    assert valid is False
    assert "not in the approved GST domain registry" in reason


def test_unverified_fallback_allows_public_non_blocked_domain_but_still_blocks_ssrf(monkeypatch):
    validator = SourceValidator(
        allowed_domains=["taxinformation.cbic.gov.in"],
        enforce_official=True,
        blocked_domains=["spamblog.example"],
    )

    monkeypatch.setattr("socket.getaddrinfo", lambda host, port: [(None, None, None, None, ("93.184.216.34", 443))])
    ok, _ = validator.validate_url("https://good-tax-blog.example/gst-article", allow_unverified=True)
    assert ok is True

    blocked, blocked_reason = validator.validate_url("https://spamblog.example/post", allow_unverified=True)
    assert blocked is False
    assert "blocked domains" in blocked_reason

    monkeypatch.setattr("socket.getaddrinfo", lambda host, port: [(None, None, None, None, ("127.0.0.1", 80))])
    ssrf_ok, ssrf_reason = validator.validate_url("https://rebind-local.example/admin", allow_unverified=True)
    assert ssrf_ok is False
    assert "SSRF Protection" in ssrf_reason


def test_allowlisted_domain_accepted(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda host, port: [(None, None, None, None, ("164.100.1.1", 443))])

    validator = SourceValidator(allowed_domains=["cbic.gov.in", "tutorial.gst.gov.in"], enforce_official=True)
    valid, reason = validator.validate_url("https://www.cbic.gov.in/circular.pdf")
    assert valid is True
    assert "permitted" in reason


def test_obsolete_prototype_url_rejected():
    validator = SourceValidator(allowed_domains=["tutorial.gst.gov.in"], enforce_official=True)
    valid, reason = validator.validate_url("https://tutorial.gst.gov.in/offlineutilities/returns/NewGSTReturn_Normal.pdf")
    assert valid is False
    assert "obsolete prototype or draft utility" in reason


def test_sanitize_search_query():
    q1 = "Check Section 16 for taxpayer 27AABCU9603R1ZN in Maharashtra"
    s1 = sanitize_search_query(q1)
    assert "27AABCU9603R1ZN" not in s1
    assert "[REDACTED_GSTIN]" in s1

    q2 = "Notice issued to director ABCDE1234F under section 73"
    s2 = sanitize_search_query(q2)
    assert "ABCDE1234F" not in s2
    assert "[REDACTED_PAN]" in s2

    q3 = "Contact client at ca_firm@example.com or 9876543210 regarding GSTR-3B"
    s3 = sanitize_search_query(q3)
    assert "ca_firm@example.com" not in s3
    assert "[REDACTED_EMAIL]" in s3
    assert "9876543210" not in s3
    assert "[REDACTED_PHONE]" in s3

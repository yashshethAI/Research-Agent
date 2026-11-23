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


def test_non_allowlisted_domain_rejected():
    validator = SourceValidator(allowed_domains=["taxinformation.cbic.gov.in"], enforce_official=True)
    valid, reason = validator.validate_url("https://random-unverified-blog.com/gst-update")
    assert valid is False
    assert "not in the approved official GST domain registry" in reason


def test_allowlisted_domain_accepted(monkeypatch):
    # Mock socket resolution so test does not depend on live internet DNS
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
    # Test GSTIN redaction
    q1 = "Check Section 16 for taxpayer 27AABCU9603R1ZN in Maharashtra"
    s1 = sanitize_search_query(q1)
    assert "27AABCU9603R1ZN" not in s1
    assert "[REDACTED_GSTIN]" in s1

    # Test PAN redaction
    q2 = "Notice issued to director ABCDE1234F under section 73"
    s2 = sanitize_search_query(q2)
    assert "ABCDE1234F" not in s2
    assert "[REDACTED_PAN]" in s2

    # Test email & phone redaction
    q3 = "Contact client at ca_firm@example.com or 9876543210 regarding GSTR-3B"
    s3 = sanitize_search_query(q3)
    assert "ca_firm@example.com" not in s3
    assert "[REDACTED_EMAIL]" in s3
    assert "9876543210" not in s3
    assert "[REDACTED_PHONE]" in s3

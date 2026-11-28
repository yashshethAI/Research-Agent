from __future__ import annotations

from backend.app.core.config import Settings


def test_settings_default_values():
    s = Settings(_env_file=None)
    assert s.APP_NAME == "GST Practice Copilot"
    assert s.APP_PORT == 8000
    assert s.STREAMLIT_PORT == 8501
    assert s.LLM_TIMEOUT == 180
    assert s.LLM_REASONING_EFFORT == "low"
    assert s.RESEARCH_LLM_REASONING_EFFORT == "none"
    assert s.SEARCH_PROVIDER == "searxng"
    assert s.SEARXNG_BASE_URL == "http://localhost:8080"
    assert s.SEARXNG_TIMEOUT == 30
    assert s.MAX_RESEARCH_RETRIES == 2
    assert s.MIN_OFFICIAL_SOURCES_SUFFICIENT == 2
    assert s.MAX_EVIDENCE_SOURCES_FOR_LLM == 5
    assert s.ALLOW_UNVERIFIED_FALLBACK is False
    assert s.SEARXNG_ENGINES == "bing,yahoo"
    assert s.SEARXNG_FALLBACK_ENGINES == "duckduckgo,startpage;brave,mojeek"
    assert s.SEARXNG_USE_SITE_OPERATORS is False
    assert s.SEARCH_CACHE_TTL_SECONDS == 3600
    assert s.MAX_SOURCE_SIZE_MB == 20
    assert s.SOURCE_CACHE_TTL_SECONDS == 21600
    assert s.MAX_SEARCH_RESULTS == 20
    assert s.MAX_FETCH_SOURCES == 8


def test_is_llm_configured_logic():
    s1 = Settings(LLM_BASE_URL="")
    assert s1.is_llm_configured is False

    s2 = Settings(LLM_BASE_URL="http://localhost:11434/v1")
    assert s2.is_llm_configured is True


def test_is_search_configured_logic():
    s1 = Settings(_env_file=None, SEARCH_PROVIDER="searxng", SEARXNG_BASE_URL="")
    assert s1.is_search_configured is False

    s2 = Settings(_env_file=None, SEARCH_PROVIDER="searxng", SEARXNG_BASE_URL="http://localhost:8080")
    assert s2.is_search_configured is True

    s3 = Settings(_env_file=None, SEARCH_PROVIDER="mock")
    assert s3.is_search_configured is True

    s4 = Settings(_env_file=None, SEARCH_PROVIDER="unknown")
    assert s4.is_search_configured is False


def test_priority_search_domains_tiered():
    s = Settings(_env_file=None)
    tier1 = s.get_tier_domains("official", max_domains=12)
    assert len(tier1) == 12
    assert "taxinformation.cbic.gov.in" in tier1
    assert "cbic.gov.in" in tier1
    assert "www.cbic.gov.in" not in tier1
    assert "gstcouncil.gov.in" in tier1
    assert "gst.gov.in" in tier1
    assert "gstat.gov.in" in tier1
    assert "indiacode.nic.in" in tier1
    assert "sci.gov.in" in tier1

    tier2 = s.get_tier_domains("verified_secondary", max_domains=12)
    assert "idtc.icai.org" in tier2
    assert "taxmann.com" in tier2
    assert "taxsutra.com" in tier2
    assert "centaxonline.com" in tier2
    assert "livelaw.in" in tier2
    assert "barandbench.com" in tier2
    assert "taxo.online" in tier2
    assert "cleartax.in" in tier2
    assert "vinodkothari.com" in tier2

    assert s.get_tier_domains("unverified_fallback") == []


def test_tiered_domains_and_authority_lookup():
    s = Settings(_env_file=None)
    assert "taxinformation.cbic.gov.in" in s.official_domains
    assert "gstat.gov.in" in s.official_domains
    assert "pib.gov.in" in s.official_domains
    assert "dgft.gov.in" in s.official_domains
    assert "icegate.gov.in" in s.official_domains

    assert "taxmann.com" in s.verified_secondary_domains
    assert "taxsutra.com" in s.verified_secondary_domains
    assert "vinodkothari.com" in s.verified_secondary_domains

    assert set(s.official_domains).issubset(set(s.allowed_domains))
    assert set(s.verified_secondary_domains).issubset(set(s.allowed_domains))

    tier1, prio1, _ = s.get_domain_authority_info("taxinformation.cbic.gov.in")
    assert tier1 == "official"
    assert prio1 == 1

    tier2, _, _ = s.get_domain_authority_info("www.taxsutra.com")
    assert tier2 == "verified_secondary"

    tier3, _, _ = s.get_domain_authority_info("some-random-blog.example")
    assert tier3 == "unverified_fallback"

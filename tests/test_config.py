from __future__ import annotations

from backend.app.core.config import Settings


def test_settings_default_values():
    s = Settings(_env_file=None)
    assert s.APP_NAME == "GST Practice Copilot"
    assert s.APP_PORT == 8000
    assert s.STREAMLIT_PORT == 8501
    assert s.LLM_TIMEOUT == 180
    assert s.SEARCH_PROVIDER == "searxng"
    assert s.SEARXNG_BASE_URL == "http://localhost:8080"
    assert s.SEARXNG_TIMEOUT == 30
    assert s.MAX_RESEARCH_RETRIES == 2
    assert s.MAX_SOURCE_SIZE_MB == 20
    assert s.MAX_UPLOAD_SIZE_MB == 20
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


def test_priority_search_domains_dedupes_www_and_balances_sources():
    s = Settings(_env_file=None)
    priority_12 = s.get_priority_search_domains(max_domains=12)
    assert len(priority_12) == 12
    assert "taxinformation.cbic.gov.in" in priority_12
    assert "cbic.gov.in" in priority_12
    assert "www.cbic.gov.in" not in priority_12
    assert "sci.gov.in" in priority_12
    assert "indiankanoon.org" in priority_12
    assert "cestat.gov.in" in priority_12

    priority_15 = s.get_priority_search_domains(max_domains=15)
    assert "taxmann.com" in priority_15
    assert "livelaw.in" in priority_15


def test_allowed_domains_loaded_from_sources_yaml():
    s = Settings()
    domains = s.allowed_domains
    assert isinstance(domains, list)
    assert len(domains) > 0
    assert "taxinformation.cbic.gov.in" in domains
    assert "cbic.gov.in" in domains
    assert "gst.gov.in" in domains
    assert "gstcouncil.gov.in" in domains
    assert "sci.gov.in" in domains
    assert "icai.org" in domains
    assert "indiankanoon.org" in domains
    assert "taxmann.com" in domains
    assert "cleartax.in" in domains

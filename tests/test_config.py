from __future__ import annotations

from backend.app.core.config import Settings


def test_settings_default_values():
    s = Settings(_env_file=None)
    assert s.APP_NAME == "GST Practice Copilot"
    assert s.APP_PORT == 8000
    assert s.STREAMLIT_PORT == 8501
    assert s.LLM_TIMEOUT == 180
    assert s.MAX_RESEARCH_RETRIES == 2
    assert s.MAX_SOURCE_SIZE_MB == 20
    assert s.MAX_UPLOAD_SIZE_MB == 20


def test_is_llm_configured_logic():
    s1 = Settings(LLM_BASE_URL="")
    assert s1.is_llm_configured is False

    s2 = Settings(LLM_BASE_URL="http://localhost:11434/v1")
    assert s2.is_llm_configured is True


def test_is_search_configured_logic():
    s1 = Settings(SEARCH_PROVIDER="tavily", TAVILY_API_KEY="")
    assert s1.is_search_configured is False

    s2 = Settings(SEARCH_PROVIDER="tavily", TAVILY_API_KEY="tvly-mock-key")
    assert s2.is_search_configured is True

    s3 = Settings(SEARCH_PROVIDER="mock")
    assert s3.is_search_configured is True


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

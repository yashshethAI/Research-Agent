from __future__ import annotations

import pytest

from backend.app.core.config import settings
from backend.app.llm.factory import (
    LLMFactory,
    LLMNotConfiguredError,
    invoke_llm_with_streaming,
    research_llm_factory,
)


def test_factory_unconfigured():
    factory = LLMFactory(override_settings={"LLM_BASE_URL": ""})
    assert factory.is_configured() is False

    with pytest.raises(LLMNotConfiguredError) as exc_info:
        factory.get_chat_model()
    assert "Inference Endpoint is not configured" in str(exc_info.value)


@pytest.mark.asyncio
async def test_factory_health_check_unconfigured():
    factory = LLMFactory(override_settings={"LLM_BASE_URL": ""})
    ok, msg = await factory.health_check()
    assert ok is False
    assert "not configured" in msg


def test_factory_configured():
    factory = LLMFactory(
        override_settings={
            "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "LLM_MODEL": "qwen2.5:14b",
            "LLM_API_KEY": "dummy",
            "LLM_TEMPERATURE": 0.0,
            "LLM_TIMEOUT": 60,
        }
    )
    assert factory.is_configured() is True
    chat_model = factory.get_chat_model()
    assert chat_model is not None
    assert chat_model.model_name == "qwen2.5:14b"


def test_factory_bearer_auth_headers():
    factory = LLMFactory(
        override_settings={
            "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "LLM_API_KEY": "sk-my-bearer-token",
        }
    )
    headers = factory.get_default_headers()
    assert "Authorization" not in headers  # ChatOpenAI uses api_key as Bearer directly
    assert headers.get("ngrok-skip-browser-warning") == "true"


def test_factory_basic_auth_env_vars():
    factory = LLMFactory(
        override_settings={
            "LLM_BASE_URL": "https://smilingly-ramp-ammonium.ngrok-free.dev/v1",
            "LLM_BASIC_AUTH_USERNAME": "yash",
            "LLM_BASIC_AUTH_PASSWORD": "secretpassword",
        }
    )
    headers = factory.get_default_headers()
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")
    # Verify base64 decoding
    import base64
    b64 = headers["Authorization"].split(" ")[1]
    decoded = base64.b64decode(b64).decode("utf-8")
    assert decoded == "yash:secretpassword"
    assert headers.get("ngrok-skip-browser-warning") == "true"


def test_factory_basic_auth_from_url():
    factory = LLMFactory(
        override_settings={
            "LLM_BASE_URL": "https://ngrokuser:ngrokpass@smilingly-ramp-ammonium.ngrok-free.dev:8000/v1",
        }
    )
    # Check that credentials were extracted
    user, pwd = factory.basic_auth_credentials
    assert user == "ngrokuser"
    assert pwd == "ngrokpass"

    # Check clean base URL
    assert factory.base_url == "https://smilingly-ramp-ammonium.ngrok-free.dev:8000/v1"

    # Check headers
    headers = factory.get_default_headers()
    import base64
    b64 = headers["Authorization"].split(" ")[1]
    decoded = base64.b64decode(b64).decode("utf-8")
    assert decoded == "ngrokuser:ngrokpass"


def test_research_llm_factory_uses_research_overrides_and_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://main-llm:8000/v1")
    monkeypatch.setattr(settings, "LLM_MODEL", "qwen3:14b")
    monkeypatch.setattr(settings, "LLM_BASIC_AUTH_USERNAME", "mainuser")
    monkeypatch.setattr(settings, "LLM_BASIC_AUTH_PASSWORD", "mainpass")

    # 1. When RESEARCH_LLM_* is unset, falls back cleanly to LLM_*
    monkeypatch.setattr(settings, "RESEARCH_LLM_BASE_URL", None)
    monkeypatch.setattr(settings, "RESEARCH_LLM_MODEL", None)
    monkeypatch.setattr(settings, "RESEARCH_LLM_BASIC_AUTH_USERNAME", None)
    monkeypatch.setattr(settings, "RESEARCH_LLM_BASIC_AUTH_PASSWORD", None)
    assert research_llm_factory.base_url == "http://main-llm:8000/v1"
    assert research_llm_factory.model_name == "qwen3:14b"
    assert research_llm_factory.basic_auth_credentials == ("mainuser", "mainpass")

    # 2. When RESEARCH_LLM_* is set, uses separate endpoint/model while falling back Basic Auth if unset
    monkeypatch.setattr(settings, "RESEARCH_LLM_BASE_URL", "http://planner-llm:8001/v1")
    monkeypatch.setattr(settings, "RESEARCH_LLM_MODEL", "gemma4-extended")
    assert research_llm_factory.base_url == "http://planner-llm:8001/v1"
    assert research_llm_factory.model_name == "gemma4-extended"
    assert research_llm_factory.basic_auth_credentials == ("mainuser", "mainpass")
    # Main llm_factory remains unchanged
    main_factory = LLMFactory()
    assert main_factory.base_url == "http://main-llm:8000/v1"
    assert main_factory.model_name == "qwen3:14b"


def test_factory_passes_reasoning_effort_to_chat_model(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://main-llm:8000/v1")
    monkeypatch.setattr(settings, "LLM_REASONING_EFFORT", "low")
    monkeypatch.setattr(settings, "RESEARCH_LLM_REASONING_EFFORT", "none")

    answer_model = LLMFactory().get_chat_model()
    planner_model = research_llm_factory.get_chat_model()
    assert answer_model.reasoning_effort == "low"
    assert planner_model.reasoning_effort == "none"


@pytest.mark.asyncio
async def test_invoke_llm_with_streaming_and_fallback():
    from types import SimpleNamespace

    class _StreamingStub:
        async def astream(self, messages):
            yield SimpleNamespace(content="Part 1 ")
            yield SimpleNamespace(content=[{"type": "text", "text": "Part 2"}])

    class _InvokeStub:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="Fallback response")

    assert await invoke_llm_with_streaming(_StreamingStub(), []) == "Part 1 Part 2"
    assert await invoke_llm_with_streaming(_InvokeStub(), []) == "Fallback response"

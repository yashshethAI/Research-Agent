from __future__ import annotations

import pytest

from backend.app.llm.factory import LLMFactory, LLMNotConfiguredError


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

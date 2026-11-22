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

from __future__ import annotations

import base64
import logging
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class LLMNotConfiguredError(Exception):
    """Raised when the LLM inference endpoint is required but has not been configured."""


class LLMFactory:
    """Configurable factory for OpenAI-compatible local/remote LLM endpoints.

    Supports vLLM, Ollama, llama.cpp, DeepInfra, and any OpenAI-compatible server.
    Supports Bearer authentication, HTTP Basic authentication, and optional RESEARCH_LLM_* overrides.
    """

    def __init__(
        self,
        override_settings: dict[str, Any] | None = None,
        use_research_settings: bool = False,
    ):
        self.settings = override_settings or {}
        self.use_research_settings = use_research_settings

    def _get_setting(self, key: str, default: Any = None) -> Any:
        if key in self.settings:
            return self.settings[key]
        if self.use_research_settings:
            research_val = getattr(settings, f"RESEARCH_{key}", None)
            if isinstance(research_val, str):
                if research_val.strip():
                    return research_val
            elif research_val is not None:
                return research_val
        return getattr(settings, key, default)

    @property
    def raw_base_url(self) -> str | None:
        return self._get_setting("LLM_BASE_URL")

    @property
    def basic_auth_credentials(self) -> tuple[str | None, str | None]:
        """Resolves basic auth username and password from URL or settings."""
        raw = self.raw_base_url
        if raw and "@" in raw:
            try:
                parsed = urlparse(raw)
                if parsed.username and parsed.password:
                    return parsed.username, parsed.password
            except Exception:
                pass

        if "LLM_BASE_URL" in self.settings:
            user = self.settings.get("LLM_BASIC_AUTH_USERNAME")
            pwd = self.settings.get("LLM_BASIC_AUTH_PASSWORD")
        else:
            user = self._get_setting("LLM_BASIC_AUTH_USERNAME")
            pwd = self._get_setting("LLM_BASIC_AUTH_PASSWORD")

        if user and pwd:
            return user.strip(), pwd.strip()

        return None, None

    @property
    def base_url(self) -> str | None:
        """Returns the clean base URL without basic auth credentials embedded."""
        raw = self.raw_base_url
        if not raw:
            return None

        if "@" in raw:
            try:
                parsed = urlparse(raw)
                if parsed.username:
                    host_part = parsed.hostname or ""
                    if parsed.port:
                        host_part = f"{host_part}:{parsed.port}"
                    clean = parsed._replace(netloc=host_part)
                    return urlunparse(clean)
            except Exception:
                pass

        return raw

    @property
    def api_key(self) -> str:
        key = self._get_setting("LLM_API_KEY")
        return key if key and key.strip() else "none"

    @property
    def model_name(self) -> str:
        model = self._get_setting("LLM_MODEL")
        return model if model and model.strip() else "default"

    @property
    def temperature(self) -> float:
        val = self._get_setting("LLM_TEMPERATURE", 0.0)
        return float(val if val is not None else settings.LLM_TEMPERATURE)

    @property
    def timeout(self) -> int:
        val = self._get_setting("LLM_TIMEOUT", 180)
        return int(val if val is not None else settings.LLM_TIMEOUT)

    @property
    def max_retries(self) -> int:
        val = self._get_setting("LLM_MAX_RETRIES", 2)
        return int(val if val is not None else settings.LLM_MAX_RETRIES)

    @property
    def reasoning_effort(self) -> str | None:
        val = self._get_setting("LLM_REASONING_EFFORT")
        if isinstance(val, str) and val.strip():
            return val.strip()
        return None

    def is_configured(self) -> bool:
        """Returns True if an LLM base URL is present."""
        return bool(self.base_url and self.base_url.strip())

    def get_default_headers(self) -> dict[str, str]:
        """Constructs request headers including ngrok bypass and optional HTTP Basic Auth."""
        headers: dict[str, str] = {
            "User-Agent": "GST-Practice-Copilot/1.0",
            "ngrok-skip-browser-warning": "true",
        }

        user, pwd = self.basic_auth_credentials
        if user and pwd:
            token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"

        return headers

    async def health_check(self) -> tuple[bool, str]:
        """Checks whether the configured LLM endpoint is reachable and responsive using a fast /models lookup."""
        if not self.is_configured():
            return False, "Inference endpoint is not configured (LLM_BASE_URL is empty)."

        try:
            url = f"{self.base_url.rstrip('/')}/models"
            headers = self.get_default_headers()
            if self.api_key and "Authorization" not in headers:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code in (200, 404):
                    return True, f"LLM endpoint reachable. Model: {self.model_name}"
                return False, f"LLM endpoint responded with HTTP {resp.status_code}"
        except Exception as e:
            return False, f"LLM health check failed: {e!s}"

    def get_chat_model(self, max_tokens: int | None = None) -> BaseChatModel:
        """Returns an instance of ChatOpenAI pointed at the configured OpenAI-compatible endpoint."""
        if not self.is_configured():
            raise LLMNotConfiguredError(
                "Local LLM Inference Endpoint is not configured.\n\n"
                "To configure your local LLM, edit your `.env` file:\n"
                "  LLM_BASE_URL=http://localhost:11434/v1  # (e.g. for Ollama)\n"
                "  LLM_MODEL=qwen2.5:14b                 # (or your downloaded model name)\n"
                "  LLM_API_KEY=none                      # (if authentication is not required)\n"
            )

        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model_name,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.get_default_headers(),
        }
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        return ChatOpenAI(**kwargs)


async def invoke_llm_with_streaming(llm: Any, messages: list[Any]) -> str:
    """Streams tokens when supported by the model to keep remote HTTP sockets alive, falling back to ainvoke."""
    if hasattr(llm, "astream"):
        parts: list[str] = []
        async for chunk in llm.astream(messages):
            content = getattr(chunk, "content", chunk)
            if isinstance(content, str) and content:
                parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
        return "".join(parts)

    response = await llm.ainvoke(messages)
    content = getattr(response, "content", response)
    return content if isinstance(content, str) else str(content)


# Global factory instances
llm_factory = LLMFactory()
research_llm_factory = LLMFactory(use_research_settings=True)

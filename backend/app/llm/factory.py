from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class LLMNotConfiguredError(Exception):
    """Raised when the LLM inference endpoint is required but has not been configured."""


class LLMFactory:
    """Configurable factory for OpenAI-compatible local/remote LLM endpoints.

    Supports vLLM, Ollama, llama.cpp, DeepInfra, and any OpenAI-compatible server.
    """

    def __init__(self, override_settings: dict[str, Any] | None = None):
        self.settings = override_settings or {}

    @property
    def base_url(self) -> str | None:
        return self.settings.get("LLM_BASE_URL") or settings.LLM_BASE_URL

    @property
    def api_key(self) -> str:
        key = self.settings.get("LLM_API_KEY") or settings.LLM_API_KEY
        return key if key and key.strip() else "none"

    @property
    def model_name(self) -> str:
        model = self.settings.get("LLM_MODEL") or settings.LLM_MODEL
        return model if model and model.strip() else "default"

    @property
    def temperature(self) -> float:
        return float(self.settings.get("LLM_TEMPERATURE") or settings.LLM_TEMPERATURE)

    @property
    def timeout(self) -> int:
        return int(self.settings.get("LLM_TIMEOUT") or settings.LLM_TIMEOUT)

    @property
    def max_retries(self) -> int:
        return int(self.settings.get("LLM_MAX_RETRIES") or settings.LLM_MAX_RETRIES)

    def is_configured(self) -> bool:
        """Returns True if an LLM base URL is present."""
        return bool(self.base_url and self.base_url.strip())

    async def health_check(self) -> tuple[bool, str]:
        """Checks whether the configured LLM endpoint is reachable and responsive."""
        if not self.is_configured():
            return False, "Inference endpoint is not configured (LLM_BASE_URL is empty)."

        try:
            llm = self.get_chat_model()
            # Simple ping message
            await llm.ainvoke([("user", "ping")])
            return True, f"LLM endpoint reachable. Model: {self.model_name}"
        except Exception as e:
            return False, f"LLM health check failed: {e!s}"

    def get_chat_model(self) -> BaseChatModel:
        """Returns an instance of ChatOpenAI pointed at the configured OpenAI-compatible endpoint."""
        if not self.is_configured():
            raise LLMNotConfiguredError(
                "Local LLM Inference Endpoint is not configured.\n\n"
                "To configure your local LLM, edit your `.env` file:\n"
                "  LLM_BASE_URL=http://localhost:11434/v1  # (e.g. for Ollama)\n"
                "  LLM_MODEL=qwen2.5:14b                 # (or your downloaded model name)\n"
                "  LLM_API_KEY=none                      # (if authentication is not required)\n"
            )

        return ChatOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model_name,
            temperature=self.temperature,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )


# Global factory instance
llm_factory = LLMFactory()

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "GST Practice Copilot"
    APP_ENV: str = "development"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    STREAMLIT_PORT: int = 8501

    # OpenAI-Compatible Local/Cloud LLM
    LLM_PROVIDER: str = "openai_compatible"
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_BASIC_AUTH_USERNAME: str | None = None
    LLM_BASIC_AUTH_PASSWORD: str | None = None
    LLM_MODEL: str | None = None
    LLM_TEMPERATURE: float = 0.0
    LLM_TIMEOUT: int = 180
    LLM_MAX_RETRIES: int = 2

    # Web Search (Local-First SearXNG)
    SEARCH_PROVIDER: str = "searxng"
    SEARXNG_BASE_URL: str = "http://localhost:8080"
    SEARXNG_TIMEOUT: int = 30
    SEARXNG_ENGINES: str | None = None
    MAX_SEARCH_RESULTS: int = 20
    MAX_FETCH_SOURCES: int = 8
    MAX_RESEARCH_RETRIES: int = 2

    # Source Validation & Security
    ENFORCE_OFFICIAL_DOMAINS: bool = True
    SOURCE_FETCH_TIMEOUT: int = 30
    MAX_SOURCE_SIZE_MB: int = 20

    # Storage
    DATA_DIR: str = "./data"
    MAX_UPLOAD_SIZE_MB: int = 20
    MAX_CONVERSATION_HISTORY: int = 30

    # Security & Logging
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    ENABLE_STREAMING: bool = True

    # Cached source registry data
    _sources_registry: dict[str, Any] | None = None

    @property
    def is_llm_configured(self) -> bool:
        """Returns True if LLM endpoint base URL is configured and non-empty."""
        return bool(self.LLM_BASE_URL and self.LLM_BASE_URL.strip())

    @property
    def is_search_configured(self) -> bool:
        """Returns True if search configuration is valid for the selected provider."""
        if self.SEARCH_PROVIDER == "mock":
            return True
        if self.SEARCH_PROVIDER == "searxng":
            return bool(self.SEARXNG_BASE_URL and self.SEARXNG_BASE_URL.strip())
        return False

    @property
    def root_data_dir(self) -> Path:
        p = Path(self.DATA_DIR).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def conversations_dir(self) -> Path:
        p = self.root_data_dir / "conversations"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def research_sessions_dir(self) -> Path:
        p = self.root_data_dir / "research_sessions"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def downloaded_sources_dir(self) -> Path:
        p = self.root_data_dir / "downloaded_sources"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def source_cache_dir(self) -> Path:
        p = self.root_data_dir / "source_cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads_dir(self) -> Path:
        p = self.root_data_dir / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_sources_registry(self) -> dict[str, Any]:
        """Loads config/sources.yaml official registry."""
        if self._sources_registry is not None:
            return self._sources_registry

        # Search for sources.yaml relative to current working directory or app root
        candidates = [
            Path("config/sources.yaml"),
            Path(__file__).resolve().parent.parent.parent.parent / "config" / "sources.yaml",
        ]
        for c in candidates:
            if c.exists():
                with open(c, "r", encoding="utf-8") as f:
                    self._sources_registry = yaml.safe_load(f) or {}
                    return self._sources_registry

        self._sources_registry = {"official_sources": [], "authority_hierarchy": []}
        return self._sources_registry

    @property
    def allowed_domains(self) -> list[str]:
        """Returns list of allowed domain names from sources.yaml."""
        registry = self.get_sources_registry()
        domains: list[str] = []
        for s in registry.get("official_sources", []):
            for d in s.get("domains", []):
                cleaned = d.strip().lower()
                if cleaned and cleaned not in domains:
                    domains.append(cleaned)
        return domains

    def get_priority_search_domains(self, max_domains: int = 12) -> list[str]:
        """Returns priority-ordered canonical root domains across official sources."""
        registry = self.get_sources_registry()
        sources = sorted(
            registry.get("official_sources", []),
            key=lambda s: s.get("priority", 99),
        )

        source_domain_lists: list[list[str]] = []
        for s in sources:
            raw = [d.strip().lower() for d in s.get("domains", []) if d and d.strip()]
            raw_set = set(raw)
            deduped: list[str] = []
            for d in raw:
                canonical = d[4:] if d.startswith("www.") and d[4:] in raw_set else d
                if canonical not in deduped:
                    deduped.append(canonical)
            if deduped:
                source_domain_lists.append(deduped)

        selected: list[str] = []
        # First pass: take primary canonical domain from each source in priority order
        for d_list in source_domain_lists:
            primary = d_list[0]
            if primary not in selected:
                selected.append(primary)
                if len(selected) >= max_domains:
                    return selected

        # Second pass: backfill secondary domains if still below max_domains
        for d_list in source_domain_lists:
            for d in d_list[1:]:
                if d not in selected:
                    selected.append(d)
                    if len(selected) >= max_domains:
                        return selected

        return selected


# Global settings singleton
settings = Settings()

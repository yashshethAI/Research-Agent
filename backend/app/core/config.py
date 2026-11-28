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

    # OpenAI-Compatible Local/Cloud LLM (Answer Generation)
    LLM_PROVIDER: str = "openai_compatible"
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_BASIC_AUTH_USERNAME: str | None = None
    LLM_BASIC_AUTH_PASSWORD: str | None = None
    LLM_MODEL: str | None = None
    LLM_TEMPERATURE: float = 0.0
    LLM_TIMEOUT: int = 180
    LLM_MAX_RETRIES: int = 2
    LLM_REASONING_EFFORT: str | None = "low"

    # Optional Separate OpenAI-Compatible LLM for Query Understanding (falls back to LLM_* if unset)
    RESEARCH_LLM_BASE_URL: str | None = None
    RESEARCH_LLM_API_KEY: str | None = None
    RESEARCH_LLM_BASIC_AUTH_USERNAME: str | None = None
    RESEARCH_LLM_BASIC_AUTH_PASSWORD: str | None = None
    RESEARCH_LLM_MODEL: str | None = None
    RESEARCH_LLM_TEMPERATURE: float | None = None
    RESEARCH_LLM_TIMEOUT: int | None = None
    RESEARCH_LLM_MAX_RETRIES: int | None = None
    RESEARCH_LLM_REASONING_EFFORT: str | None = "none"

    # Web Search (Local-First SearXNG)
    SEARCH_PROVIDER: str = "searxng"
    SEARXNG_BASE_URL: str = "http://localhost:8080"
    SEARXNG_TIMEOUT: int = 30
    SEARXNG_ENGINES: str | None = "bing,yahoo"
    SEARXNG_FALLBACK_ENGINES: str | None = "duckduckgo,startpage;brave,mojeek"
    SEARXNG_USE_SITE_OPERATORS: bool = False
    SEARCH_CACHE_TTL_SECONDS: int = 3600
    MAX_SEARCH_RESULTS: int = 20
    MAX_FETCH_SOURCES: int = 8
    MAX_RESEARCH_RETRIES: int = 2
    MIN_OFFICIAL_SOURCES_SUFFICIENT: int = 2
    MAX_EVIDENCE_SOURCES_FOR_LLM: int = 5

    # Source Validation & Security
    ENFORCE_OFFICIAL_DOMAINS: bool = True
    ALLOW_UNVERIFIED_FALLBACK: bool = False
    SOURCE_FETCH_TIMEOUT: int = 30
    SOURCE_CACHE_TTL_SECONDS: int = 21600
    MAX_SOURCE_SIZE_MB: int = 20

    # Storage
    DATA_DIR: str = "./data"
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

    def get_sources_registry(self) -> dict[str, Any]:
        """Loads config/sources.yaml 3-tier source registry."""
        if self._sources_registry is not None:
            return self._sources_registry

        candidates = [
            Path("config/sources.yaml"),
            Path(__file__).resolve().parent.parent.parent.parent / "config" / "sources.yaml",
        ]
        for c in candidates:
            if c.exists():
                with open(c, "r", encoding="utf-8") as f:
                    self._sources_registry = yaml.safe_load(f) or {}
                    return self._sources_registry

        self._sources_registry = {
            "official_sources": [],
            "verified_secondary_sources": [],
            "unverified_fallback_policy": {"blocked_domains": []},
            "authority_hierarchy": [],
        }
        return self._sources_registry

    def _extract_domains_from_section(self, section_name: str) -> list[str]:
        registry = self.get_sources_registry()
        domains: list[str] = []
        for s in registry.get(section_name, []) or []:
            for d in s.get("domains", []) or []:
                cleaned = d.strip().lower()
                if cleaned and cleaned not in domains:
                    domains.append(cleaned)
        return domains

    @property
    def official_domains(self) -> list[str]:
        """Tier 1 official government, statutory, and judicial domains."""
        return self._extract_domains_from_section("official_sources")

    @property
    def verified_secondary_domains(self) -> list[str]:
        """Tier 2 verified institutional and legal/tax reporter domains."""
        return self._extract_domains_from_section("verified_secondary_sources")

    @property
    def blocked_domains(self) -> list[str]:
        """Domains excluded from open-web fallback searches."""
        registry = self.get_sources_registry()
        policy = registry.get("unverified_fallback_policy") or {}
        return [d.strip().lower() for d in policy.get("blocked_domains", []) if d and d.strip()]

    @property
    def allowed_domains(self) -> list[str]:
        """Combined Tier 1 + Tier 2 allowlisted domains from sources.yaml."""
        combined: list[str] = []
        for d in [*self.official_domains, *self.verified_secondary_domains]:
            if d not in combined:
                combined.append(d)
        return combined

    def get_priority_search_domains(self, max_domains: int = 12, section: str | None = None) -> list[str]:
        """Returns priority-ordered canonical domains from sources.yaml (or a specific tier section)."""
        registry = self.get_sources_registry()
        if section:
            raw_sources = list(registry.get(section, []) or [])
        else:
            raw_sources = [
                *(registry.get("official_sources", []) or []),
                *(registry.get("verified_secondary_sources", []) or []),
            ]

        sources = sorted(raw_sources, key=lambda s: s.get("priority", 99))

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
        for d_list in source_domain_lists:
            primary = d_list[0]
            if primary not in selected:
                selected.append(primary)
                if len(selected) >= max_domains:
                    return selected

        for d_list in source_domain_lists:
            for d in d_list[1:]:
                if d not in selected:
                    selected.append(d)
                    if len(selected) >= max_domains:
                        return selected

        return selected

    def get_tier_domains(self, tier: str, max_domains: int = 12) -> list[str]:
        """Returns canonical search domains for 'official', 'verified_secondary', or 'unverified_fallback'."""
        if tier == "official":
            return self.get_priority_search_domains(max_domains=max_domains, section="official_sources")
        if tier == "verified_secondary":
            return self.get_priority_search_domains(max_domains=max_domains, section="verified_secondary_sources")
        if tier == "unverified_fallback":
            return []
        return self.get_priority_search_domains(max_domains=max_domains)

    def get_domain_authority_info(self, domain: str) -> tuple[str, int, str]:
        """Looks up (tier, priority, authority_name) for a domain from sources.yaml."""
        d = (domain or "").strip().lower()
        registry = self.get_sources_registry()

        for section, tier_label in (
            ("official_sources", "official"),
            ("verified_secondary_sources", "verified_secondary"),
        ):
            for entry in registry.get(section, []) or []:
                for allowed in entry.get("domains", []) or []:
                    allowed_l = allowed.strip().lower()
                    if d == allowed_l or d.endswith("." + allowed_l):
                        return tier_label, int(entry.get("priority", 5)), entry.get("authority") or entry.get("name", "GST Source")

        return "unverified_fallback", 10, "Open Web Fallback Source (Unverified)"


# Global settings singleton
settings = Settings()

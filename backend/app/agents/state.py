from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResearchState(BaseModel):
    """Unified state passed across the 5-node GST legal research LangGraph."""

    # Session identifiers
    conversation_id: str = ""
    research_id: str = ""
    query: str = ""
    user_role: str = "Professional"

    # Persisted conversation history
    messages: list[dict[str, Any]] = Field(default_factory=list)

    # Dynamic query understanding & clarification
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_prompt: str | None = None

    # Tiered search planning & retrieval
    research_plan: dict[str, Any] = Field(default_factory=dict)
    search_queries: list[str] = Field(default_factory=list)
    search_time_range: str | None = None
    search_tier: str = "official"
    attempted_tiers: list[str] = Field(default_factory=list)
    attempted_queries: list[str] = Field(default_factory=list)
    search_results: list[dict[str, Any]] = Field(default_factory=list)
    search_feedback: str | None = None

    # Compiled evidence & citation audit
    evidence_records: list[dict[str, Any]] = Field(default_factory=list)
    citation_validation: dict[str, Any] = Field(default_factory=dict)

    # Flow control & diagnostics
    retry_count: int = 0
    should_refine_search: bool = False
    error_message: str | None = None
    llm_unconfigured_guidance: str | None = None
    current_step: str = "start"
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    node_errors: list[dict[str, Any]] = Field(default_factory=list)

    # Final outputs
    final_report: str = ""
    persisted: bool = False

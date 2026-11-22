from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResearchState(BaseModel):
    """The unified state passed across all 13 LangGraph nodes."""

    # Session identifiers
    conversation_id: str = ""
    research_id: str = ""
    query: str = ""
    user_role: str = "Professional"
    attachment_ids: list[str] = Field(default_factory=list)

    # Conversation history
    messages: list[dict[str, Any]] = Field(default_factory=list)

    # Extracted facts and assumptions
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_prompt: str = ""

    # Research planning & execution
    research_plan: dict[str, Any] = Field(default_factory=dict)
    search_queries: list[str] = Field(default_factory=list)
    search_results: list[dict[str, Any]] = Field(default_factory=list)
    fetched_documents: list[dict[str, Any]] = Field(default_factory=list)
    parsed_documents: list[dict[str, Any]] = Field(default_factory=list)

    # Evidence records & analysis
    evidence_records: list[dict[str, Any]] = Field(default_factory=list)
    legal_analysis: dict[str, Any] = Field(default_factory=dict)
    citation_validation: dict[str, Any] = Field(default_factory=dict)

    # Flow control & retries
    retry_count: int = 0
    should_refine_search: bool = False
    error_message: str | None = None
    llm_unconfigured_guidance: str | None = None
    current_step: str = "start"

    # Final outputs
    final_report: str = ""
    persisted: bool = False

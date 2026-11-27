from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="GST research query entered by the user")
    conversation_id: str | None = Field(None, description="Optional existing conversation ID")
    user_role: str = Field(
        default="Professional",
        description="Active persona: 'Professional', 'Intern / Article Assistant', or 'Partner / Counsel'",
    )
    stream: bool = Field(default=False, description="Whether to stream response via SSE")


class ChatResponse(BaseModel):
    research_id: str
    conversation_id: str
    answer: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_prompt: str | None = None
    llm_configured: bool = True
    search_tiers_used: list[str] = Field(default_factory=list)
    node_errors: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "completed"


class ConfigStatusResponse(BaseModel):
    app_name: str
    app_env: str
    llm_configured: bool
    llm_base_url: str | None = None
    llm_model: str | None = None
    search_configured: bool
    search_provider: str
    search_reachable: bool = False
    search_base_url: str | None = None
    search_status_message: str | None = None
    official_domains_count: int
    verified_secondary_domains_count: int = 0
    allow_unverified_fallback: bool = False
    data_dir_writable: bool


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str


class ConversationDetail(BaseModel):
    conversation_id: str
    messages: list[dict[str, Any]]

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.app.schemas.api import ConversationDetail, ConversationSummary
from backend.app.storage.conversations import conversation_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations() -> list[ConversationSummary]:
    """Returns summaries of all saved conversations."""
    summaries = conversation_storage.list_conversations()
    return [ConversationSummary(**s) for s in summaries]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str) -> ConversationDetail:
    """Returns full message history for a specific conversation."""
    messages = conversation_storage.get_conversation(conversation_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return ConversationDetail(conversation_id=conversation_id, messages=messages)


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict:
    """Deletes a conversation from filesystem storage."""
    success = conversation_storage.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or already deleted.")
    return {"message": "Conversation deleted successfully.", "conversation_id": conversation_id}

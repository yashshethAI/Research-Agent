from __future__ import annotations

import logging

from backend.app.agents.state import ResearchState
from backend.app.storage.conversations import conversation_storage

logger = logging.getLogger(__name__)


async def load_conversation_node(state: ResearchState) -> dict:
    """Node 1: Loads conversation history from filesystem JSONL storage."""
    conv_id = state.conversation_id
    if not conv_id:
        return {"current_step": "load_conversation", "messages": []}

    try:
        messages = conversation_storage.get_conversation(conv_id)
        logger.info(f"Loaded {len(messages)} messages for conversation {conv_id}")
        return {
            "current_step": "load_conversation",
            "messages": messages,
        }
    except Exception as e:
        logger.error(f"Error loading conversation {conv_id}: {e}")
        return {"current_step": "load_conversation"}

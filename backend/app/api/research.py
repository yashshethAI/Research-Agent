from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.storage.research import research_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/research", tags=["Research"])


@router.get("/{research_id}")
async def get_research_session(research_id: str) -> dict[str, Any]:
    """Retrieves all persisted research session artifacts (query, plan, search results, evidence, answer markdown)."""
    session = research_storage.get_research_session(research_id)
    if not session:
        raise HTTPException(status_code=404, detail="Research session not found.")
    return session

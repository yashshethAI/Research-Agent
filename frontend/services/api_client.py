from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


class BackendAPIClient:
    """Client for communicating with the FastAPI backend over HTTP and SSE."""

    def __init__(self, base_url: str = DEFAULT_BACKEND_URL):
        self.base_url = base_url.rstrip("/")

    def get_health(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/v1/health")
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch backend health: {e}")
        return {"status": "unreachable", "message": "Backend server is not running on 127.0.0.1:8000"}

    def get_config_status(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/v1/config/status")
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch config status: {e}")
        return {"llm_configured": False, "search_configured": False}

    def list_conversations(self) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/v1/conversations")
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.error(f"Failed to list conversations: {e}")
        return []

    def get_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/v1/conversations/{conversation_id}")
                if resp.status_code == 200:
                    return resp.json().get("messages", [])
        except Exception as e:
            logger.error(f"Failed to get conversation {conversation_id}: {e}")
        return []

    def delete_conversation(self, conversation_id: str) -> bool:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.delete(f"{self.base_url}/api/v1/conversations/{conversation_id}")
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to delete conversation {conversation_id}: {e}")
            return False

    def send_chat(
        self,
        query: str,
        conversation_id: str | None = None,
        user_role: str = "Professional",
        attachment_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "query": query,
            "conversation_id": conversation_id,
            "user_role": user_role,
            "stream": False,
            "attachment_ids": attachment_ids or [],
        }
        with httpx.Client(timeout=180) as client:
            resp = client.post(f"{self.base_url}/api/v1/chat", json=payload)
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Backend error ({resp.status_code}): {resp.text}")

    def upload_document(self, filename: str, content: bytes) -> dict[str, Any]:
        files = {"file": (filename, content)}
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{self.base_url}/api/v1/documents/upload", files=files)
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Upload failed: {resp.text}")

    def get_research_artifacts(self, research_id: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/v1/research/{research_id}")
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.error(f"Failed to get research {research_id}: {e}")
        return {}


# Global client instance
api_client = BackendAPIClient()

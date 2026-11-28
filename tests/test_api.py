from __future__ import annotations

import json

from starlette.testclient import TestClient

from backend.app.core.config import settings
from backend.app.llm.factory import llm_factory
from backend.app.main import app
from backend.app.tools.search.searxng_adapter import SearXNGSearchAdapter

client = TestClient(app)


def test_api_health_endpoint(monkeypatch):
    async def mock_health(self):
        return True, "SearXNG reachable at http://localhost:8080"

    monkeypatch.setattr(SearXNGSearchAdapter, "health_check", mock_health)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "llm_status" in data
    assert "research_llm_status" in data
    assert "search_status" in data
    assert data["search_status"]["provider"] == settings.SEARCH_PROVIDER
    assert "allow_unverified_fallback" in data["search_status"]


def test_api_config_status_endpoint(monkeypatch):
    async def mock_health(self):
        return False, "SearXNG health check failed: connection refused"

    monkeypatch.setattr(SearXNGSearchAdapter, "health_check", mock_health)
    response = client.get("/api/v1/config/status")
    assert response.status_code == 200
    data = response.json()
    assert "app_name" in data
    assert "llm_configured" in data
    assert "research_llm_model" in data
    assert "search_configured" in data
    assert data["search_provider"] == settings.SEARCH_PROVIDER
    assert data["search_reachable"] is False
    assert "search_fallback_engines" in data
    assert "search_cache_ttl_seconds" in data
    assert "source_cache_ttl_seconds" in data
    assert "official_domains_count" in data
    assert "verified_secondary_domains_count" in data
    assert "allow_unverified_fallback" in data
    assert data["data_dir_writable"] is True


def test_api_chat_endpoint_unconfigured_llm(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: False)
    payload = {
        "query": "Is ITC admissible on corporate CSR expenditure?",
        "user_role": "Professional",
        "stream": False,
    }
    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "research_id" in data
    assert "conversation_id" in data
    assert "INFERENCE SETUP REQUIRED" in data["answer"]
    assert "search_tiers_used" in data
    assert "node_errors" in data


def test_api_conversations_flow(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: False)
    chat_resp = client.post(
        "/api/v1/chat",
        json={"query": "Test conversation query", "user_role": "Intern / Article Assistant"},
    )
    assert chat_resp.status_code == 200
    conv_id = chat_resp.json()["conversation_id"]

    list_resp = client.get("/api/v1/conversations")
    assert list_resp.status_code == 200
    assert any(c["conversation_id"] == conv_id for c in list_resp.json())

    detail_resp = client.get(f"/api/v1/conversations/{conv_id}")
    assert detail_resp.status_code == 200
    assert len(detail_resp.json()["messages"]) >= 2

    del_resp = client.delete(f"/api/v1/conversations/{conv_id}")
    assert del_resp.status_code == 200


def test_api_document_upload_removed():
    response = client.post("/api/v1/documents/upload")
    assert response.status_code == 404


def test_api_chat_stream_endpoint(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: False)
    payload = {
        "query": "Is GST applicable on directors remuneration under RCM?",
        "conversation_id": "test-sse-stream-conv",
        "user_role": "Professional",
        "stream": True,
    }
    with client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        assert len(events) >= 2
        assert events[0]["event"] == "started"
        event_types = [e["event"] for e in events]
        assert "complete" in event_types


def test_api_chat_stream_emits_heartbeat_during_slow_node(monkeypatch):
    import asyncio

    import backend.app.api.chat as chat_mod

    async def slow_astream(state, stream_mode="updates"):
        await asyncio.sleep(0.08)
        yield {"understand_query": {"final_report": "Done", "needs_clarification": False}}

    monkeypatch.setattr(chat_mod, "_SSE_HEARTBEAT_INTERVAL_S", 0.02)
    monkeypatch.setattr(chat_mod.gst_research_graph, "astream", slow_astream)

    payload = {
        "query": "Test heartbeat query",
        "conversation_id": "test-sse-hb-conv",
        "user_role": "Professional",
        "stream": True,
    }
    with client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[6:])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]
    event_types = [e["event"] for e in events]
    assert "heartbeat" in event_types
    assert "complete" in event_types

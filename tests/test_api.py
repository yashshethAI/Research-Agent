from __future__ import annotations

import json

from starlette.testclient import TestClient

from backend.app.llm.factory import llm_factory
from backend.app.main import app

client = TestClient(app)


def test_api_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "llm_status" in data
    assert "search_status" in data


def test_api_config_status_endpoint():
    response = client.get("/api/v1/config/status")
    assert response.status_code == 200
    data = response.json()
    assert "app_name" in data
    assert "llm_configured" in data
    assert "search_configured" in data
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
    assert "answer" in data
    assert "INFERENCE SETUP REQUIRED" in data["answer"]


def test_api_conversations_flow(monkeypatch):
    monkeypatch.setattr(llm_factory, "is_configured", lambda: False)
    # 1. Post a query to generate conversation
    chat_resp = client.post(
        "/api/v1/chat",
        json={"query": "Test conversation query", "user_role": "Intern / Article Assistant"},
    )
    assert chat_resp.status_code == 200
    conv_id = chat_resp.json()["conversation_id"]

    # 2. List conversations
    list_resp = client.get("/api/v1/conversations")
    assert list_resp.status_code == 200
    conversations = list_resp.json()
    assert any(c["conversation_id"] == conv_id for c in conversations)

    # 3. Get single conversation
    detail_resp = client.get(f"/api/v1/conversations/{conv_id}")
    assert detail_resp.status_code == 200
    messages = detail_resp.json()["messages"]
    assert len(messages) >= 2  # user and assistant

    # 4. Delete conversation
    del_resp = client.delete(f"/api/v1/conversations/{conv_id}")
    assert del_resp.status_code == 200


def test_api_document_upload():
    test_pdf_content = b"%PDF-1.4 test dummy pdf content"
    files = {"file": ("notice_sec73.pdf", test_pdf_content, "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "notice_sec73.pdf"
    assert "sha256_hash" in data
    assert len(data["sha256_hash"]) == 64


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
        assert "complete" in event_types or "step" in event_types

from __future__ import annotations

import tempfile
from pathlib import Path

from backend.app.storage.conversations import ConversationStorage
from backend.app.storage.research import ResearchStorage
from backend.app.storage.source_cache import SourceCacheStorage


def test_conversation_storage_crud():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = ConversationStorage(storage_dir=Path(tmp_dir))
        conv_id = "test-conv-001"

        # 1. Append messages
        storage.append_message(conv_id, "user", "What is Section 16(4)?")
        storage.append_message(conv_id, "assistant", "Section 16(4) governs ITC time limits.")

        # 2. Get messages
        messages = storage.get_conversation(conv_id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What is Section 16(4)?"
        assert messages[1]["role"] == "assistant"

        # 3. List conversations
        summaries = storage.list_conversations()
        assert len(summaries) == 1
        assert summaries[0]["conversation_id"] == conv_id
        assert summaries[0]["message_count"] == 2

        # 4. Delete conversation
        deleted = storage.delete_conversation(conv_id)
        assert deleted is True
        assert len(storage.get_conversation(conv_id)) == 0


def test_research_storage_save_and_retrieve():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = ResearchStorage(storage_dir=Path(tmp_dir))
        res_id = "res-test-123"
        conv_id = "conv-test-123"

        storage.save_research_session(
            research_id=res_id,
            conversation_id=conv_id,
            query="Analyze RCM under Section 9(3)",
            research_plan={"target_sections": ["Section 9(3)"]},
            search_results=[{"title": "Notification 13/2017"}],
            evidence=[{"source_id": "SRC-001", "title": "Notification 13/2017"}],
            answer_md="## A. EXECUTIVE CONCLUSION\nRCM is applicable on specified services.",
            metadata={"user_role": "Partner / Counsel"},
        )

        session = storage.get_research_session(res_id)
        assert session is not None
        assert session["research_id"] == res_id
        assert session["query"]["query"] == "Analyze RCM under Section 9(3)"
        assert session["research_plan"]["target_sections"] == ["Section 9(3)"]
        assert len(session["search_results"]) == 1
        assert len(session["evidence"]) == 1
        assert "## A. EXECUTIVE CONCLUSION" in session["answer_md"]
        assert session["metadata"]["user_role"] == "Partner / Counsel"


def test_source_cache_storage():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = SourceCacheStorage(storage_dir=Path(tmp_dir))
        content = b"Official CBIC Circular Content Here"
        url = "https://taxinformation.cbic.gov.in/doc.html"
        domain = "taxinformation.cbic.gov.in"

        sha, file_path = storage.save_document(url, domain, content, "html")
        assert len(sha) == 64
        assert file_path.exists()
        assert "CBIC" in str(file_path)

        retrieved = storage.get_document(sha)
        assert retrieved is not None
        cached_bytes, meta = retrieved
        assert cached_bytes == content
        assert meta["url"] == url

        recent = storage.get_recent_document_by_url(url, max_age_seconds=3600)
        assert recent is not None
        recent_bytes, recent_meta, recent_path = recent
        assert recent_bytes == content
        assert recent_meta["hash"] == sha
        assert recent_path.exists()

        assert storage.get_recent_document_by_url(url, max_age_seconds=0) is None

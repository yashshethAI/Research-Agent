from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class ConversationStorage:
    """Thread-safe and process-safe JSONL conversation storage."""

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = storage_dir or settings.conversations_dir

    def _get_path(self, conversation_id: str) -> Path:
        safe_id = Path(conversation_id).name  # Prevent directory traversal
        return self.storage_dir / f"{safe_id}.jsonl"

    def _get_lock_path(self, conversation_id: str) -> Path:
        safe_id = Path(conversation_id).name
        return self.storage_dir / f"{safe_id}.lock"

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Appends a single message record to the conversation's JSONL file."""
        file_path = self._get_path(conversation_id)
        lock_path = self._get_lock_path(conversation_id)

        msg_id = str(uuid.uuid4())
        record = {
            "message_id": msg_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
        }

        with FileLock(str(lock_path), timeout=10):
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record

    def get_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        """Reads all messages for a given conversation_id."""
        file_path = self._get_path(conversation_id)
        if not file_path.exists():
            return []

        lock_path = self._get_lock_path(conversation_id)
        messages: list[dict[str, Any]] = []

        with FileLock(str(lock_path), timeout=10):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing conversation line in {file_path}: {e}")

        return messages

    def list_conversations(self) -> list[dict[str, Any]]:
        """Lists summaries of all stored conversations ordered by most recent activity."""
        summaries: list[dict[str, Any]] = []
        for file in self.storage_dir.glob("*.jsonl"):
            conv_id = file.stem
            try:
                # Read first and last lines for metadata
                first_line: str | None = None
                last_line: str | None = None
                msg_count = 0
                with open(file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            if first_line is None:
                                first_line = line
                            last_line = line
                            msg_count += 1

                title = "New GST Query"
                created_at = datetime.fromtimestamp(file.stat().st_ctime, tz=UTC).isoformat()
                updated_at = datetime.fromtimestamp(file.stat().st_mtime, tz=UTC).isoformat()

                if first_line:
                    first_record = json.loads(first_line)
                    raw_content = first_record.get("content", "")
                    title = (raw_content[:60] + "...") if len(raw_content) > 60 else raw_content
                    created_at = first_record.get("timestamp", created_at)

                if last_line:
                    last_record = json.loads(last_line)
                    updated_at = last_record.get("timestamp", updated_at)

                summaries.append({
                    "conversation_id": conv_id,
                    "title": title or f"Conversation {conv_id[:8]}",
                    "message_count": msg_count,
                    "created_at": created_at,
                    "updated_at": updated_at,
                })
            except Exception as e:
                logger.error(f"Error reading conversation file {file}: {e}")

        # Sort by updated_at descending
        summaries.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return summaries

    def delete_conversation(self, conversation_id: str) -> bool:
        """Deletes conversation JSONL and lock files."""
        file_path = self._get_path(conversation_id)
        lock_path = self._get_lock_path(conversation_id)
        deleted = False

        if file_path.exists():
            file_path.unlink()
            deleted = True
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass

        return deleted


# Global instance
conversation_storage = ConversationStorage()

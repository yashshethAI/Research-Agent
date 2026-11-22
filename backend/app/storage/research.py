from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class ResearchStorage:
    """Stores full research session artifacts in deterministic directory structures."""

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = storage_dir or settings.research_sessions_dir

    def _get_session_dir(self, research_id: str) -> Path:
        safe_id = Path(research_id).name
        d = self.storage_dir / safe_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _atomic_write_json(self, file_path: Path, data: Any) -> None:
        """Atomically writes JSON using a temporary file and replace."""
        tmp_path = file_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(file_path)

    def _atomic_write_text(self, file_path: Path, text: str) -> None:
        """Atomically writes text using a temporary file and replace."""
        tmp_path = file_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
        tmp_path.replace(file_path)

    def save_research_session(
        self,
        research_id: str,
        conversation_id: str,
        query: str,
        research_plan: dict[str, Any] | None = None,
        search_results: Any | None = None,
        evidence: Any | None = None,
        answer_md: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Saves all artifacts for a given research session."""
        session_dir = self._get_session_dir(research_id)
        lock_file = session_dir / ".lock"

        with FileLock(str(lock_file), timeout=10):
            # 1. query.json
            self._atomic_write_json(
                session_dir / "query.json",
                {
                    "research_id": research_id,
                    "conversation_id": conversation_id,
                    "query": query,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # 2. research_plan.json
            if research_plan is not None:
                self._atomic_write_json(session_dir / "research_plan.json", research_plan)

            # 3. search_results.json
            if search_results is not None:
                self._atomic_write_json(session_dir / "search_results.json", search_results)

            # 4. evidence.json
            if evidence is not None:
                self._atomic_write_json(session_dir / "evidence.json", evidence)

            # 5. answer.md
            if answer_md is not None:
                self._atomic_write_text(session_dir / "answer.md", answer_md)

            # 6. metadata.json
            meta_record = {
                "research_id": research_id,
                "conversation_id": conversation_id,
                "created_at": datetime.now(UTC).isoformat(),
                **(metadata or {}),
            }
            self._atomic_write_json(session_dir / "metadata.json", meta_record)

        return session_dir

    def get_research_session(self, research_id: str) -> dict[str, Any] | None:
        """Reads all artifacts for a research session."""
        safe_id = Path(research_id).name
        session_dir = self.storage_dir / safe_id
        if not session_dir.exists():
            return None

        result: dict[str, Any] = {"research_id": safe_id}

        query_file = session_dir / "query.json"
        if query_file.exists():
            with open(query_file, "r", encoding="utf-8") as f:
                result["query"] = json.load(f)

        plan_file = session_dir / "research_plan.json"
        if plan_file.exists():
            with open(plan_file, "r", encoding="utf-8") as f:
                result["research_plan"] = json.load(f)

        results_file = session_dir / "search_results.json"
        if results_file.exists():
            with open(results_file, "r", encoding="utf-8") as f:
                result["search_results"] = json.load(f)

        evidence_file = session_dir / "evidence.json"
        if evidence_file.exists():
            with open(evidence_file, "r", encoding="utf-8") as f:
                result["evidence"] = json.load(f)

        answer_file = session_dir / "answer.md"
        if answer_file.exists():
            with open(answer_file, "r", encoding="utf-8") as f:
                result["answer_md"] = f.read()

        meta_file = session_dir / "metadata.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                result["metadata"] = json.load(f)

        return result


# Global instance
research_storage = ResearchStorage()

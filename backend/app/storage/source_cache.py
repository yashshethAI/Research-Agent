from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class SourceCacheStorage:
    """Manages cached raw downloads (HTML, PDF) indexed by SHA-256, authority, and URL."""

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = storage_dir or settings.downloaded_sources_dir

    def _determine_authority_folder(self, domain: str) -> str:
        d = domain.lower()
        if "cbic" in d:
            return "CBIC"
        if "gst.gov.in" in d or "gstcouncil" in d:
            return "GSTN"
        if "court" in d or "judiciary" in d or "sci.gov.in" in d:
            return "COURTS"
        if "comtax" in d or "mahagst" in d or "tax" in d:
            return "STATES"
        return "GENERAL"

    def compute_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _url_index_path(self, url: str) -> Path:
        url_digest = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()
        return self.storage_dir / "_url_index" / f"{url_digest}.json"

    def _save_url_index(
        self,
        url: str,
        sha256_hash: str,
        doc_path: Path,
        meta_record: dict[str, Any],
    ) -> None:
        index_path = self._url_index_path(url)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "url": url,
            "hash": sha256_hash,
            "file_path": str(doc_path),
            "cached_at": time.time(),
            "content_type": meta_record.get("content_type", ""),
            "http_status": meta_record.get("http_status", 200),
        }
        tmp_idx = index_path.with_suffix(".tmp")
        with open(tmp_idx, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        tmp_idx.replace(index_path)

    def get_recent_document_by_url(
        self,
        url: str,
        max_age_seconds: int,
    ) -> tuple[bytes, dict[str, Any], Path] | None:
        """Returns cached (content, metadata, file_path) for a URL if within max_age_seconds."""
        if max_age_seconds <= 0 or not url or not url.strip():
            return None
        index_path = self._url_index_path(url)
        if not index_path.exists():
            return None
        try:
            idx = json.loads(index_path.read_text(encoding="utf-8"))
            cached_at = float(idx.get("cached_at", 0.0))
            if time.time() - cached_at > max_age_seconds:
                return None
            file_path = Path(idx.get("file_path", ""))
            if file_path.exists():
                content = file_path.read_bytes()
                return content, idx, file_path
            sha = idx.get("hash") or ""
            if sha:
                found = self.get_document(sha)
                if found is not None:
                    content, meta = found
                    return content, {**idx, **meta}, file_path
        except Exception as e:
            logger.debug(f"URL cache lookup failed for {url}: {e}")
        return None

    def save_document(
        self,
        url: str,
        domain: str,
        content: bytes,
        extension: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, Path]:
        """Saves a downloaded document and returns (sha256_hash, file_path)."""
        sha256_hash = self.compute_hash(content)
        authority_dir = self.storage_dir / self._determine_authority_folder(domain)
        authority_dir.mkdir(parents=True, exist_ok=True)

        clean_ext = extension.lstrip(".") or "bin"
        doc_path = authority_dir / f"{sha256_hash}.{clean_ext}"
        meta_path = authority_dir / f"{sha256_hash}.meta.json"
        lock_path = authority_dir / f"{sha256_hash}.lock"

        with FileLock(str(lock_path), timeout=10):
            if not doc_path.exists():
                tmp_doc = doc_path.with_suffix(".tmp")
                with open(tmp_doc, "wb") as f:
                    f.write(content)
                tmp_doc.replace(doc_path)

            meta_record = {
                "hash": sha256_hash,
                "url": url,
                "domain": domain,
                "extension": clean_ext,
                "size_bytes": len(content),
                "retrieved_at": datetime.now(UTC).isoformat(),
                **(metadata or {}),
            }
            tmp_meta = meta_path.with_suffix(".tmp")
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(meta_record, f, indent=2)
            tmp_meta.replace(meta_path)

        try:
            self._save_url_index(url, sha256_hash, doc_path, meta_record)
        except OSError as e:
            logger.debug(f"Failed saving URL cache index for {url}: {e}")

        return sha256_hash, doc_path

    def get_document(self, sha256_hash: str) -> tuple[bytes, dict[str, Any]] | None:
        """Retrieves document content and metadata by hash."""
        if not self.storage_dir.exists():
            return None
        for auth_dir in self.storage_dir.iterdir():
            if auth_dir.is_dir() and auth_dir.name != "_url_index":
                matches = list(auth_dir.glob(f"{sha256_hash}.*"))
                doc_file = next(
                    (
                        f
                        for f in matches
                        if not f.name.endswith(".json")
                        and not f.name.endswith(".lock")
                        and not f.name.endswith(".tmp")
                    ),
                    None,
                )
                meta_file = auth_dir / f"{sha256_hash}.meta.json"
                if doc_file and doc_file.exists():
                    with open(doc_file, "rb") as f:
                        content = f.read()
                    meta = {}
                    if meta_file.exists():
                        with open(meta_file, "r", encoding="utf-8") as mf:
                            meta = json.load(mf)
                    return content, meta
        return None


# Global instance
source_cache_storage = SourceCacheStorage()

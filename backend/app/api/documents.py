from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.app.core.config import settings
from backend.app.schemas.api import DocumentUploadResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentUploadResponse:
    """Safely accepts and stores user-uploaded GST documents (PDFs, notifications, notices)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a valid filename.")

    # Validate file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in [".pdf", ".txt", ".html"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Only .pdf, .txt, and .html documents are allowed.",
        )

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Uploaded file exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    file_id = str(uuid.uuid4())
    safe_filename = Path(file.filename).name  # Prevent path traversal
    dest_path = settings.uploads_dir / f"{file_id}_{safe_filename}"

    sha_hash = hashlib.sha256(content).hexdigest()

    with open(dest_path, "wb") as f:
        f.write(content)

    logger.info(f"Saved uploaded document {safe_filename} ({sha_hash[:8]}) to {dest_path}")

    return DocumentUploadResponse(
        file_id=file_id,
        filename=safe_filename,
        size_bytes=len(content),
        sha256_hash=sha_hash,
        message="Document uploaded and stored successfully.",
    )

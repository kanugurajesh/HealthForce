"""Upload storage. Files are stored under random names inside an org-specific directory;
the user-supplied filename is display-only and never touches the filesystem path."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain import DocumentKind, JobState
from app.errors import AppError
from app.extraction.errors import ExtractionError
from app.extraction.text import sanitize_filename, validate_upload
from app.models import Candidate, Document, ProcessingJob
from app.security import Principal
from app.services import audit

_UPLOAD_STATUS = {"unsupported_type": 415, "file_too_large": 413}


def storage_path(document: Document) -> Path:
    base = get_settings().upload_dir.resolve()
    path = (base / document.organization_id / document.stored_name).resolve()
    if base not in path.parents:  # defence in depth: stored_name is generated, but never trust paths
        raise AppError(500, "storage_error", "Invalid storage path.")
    return path


def store_document(db: Session, principal: Principal | None, candidate: Candidate, filename: str, data: bytes, kind: DocumentKind) -> tuple[Document, bool]:
    """Validate, persist and enqueue a document. Returns (document, created).

    Uploading identical bytes for the same candidate is idempotent: the existing document
    (and its job) is returned instead of creating a duplicate.
    """
    settings = get_settings()
    display_name = sanitize_filename(filename)
    try:
        ext, content_type = validate_upload(display_name, data, settings.max_upload_bytes)
    except ExtractionError as exc:
        raise AppError(_UPLOAD_STATUS.get(exc.code, 400), exc.code, exc.message) from exc

    sha = hashlib.sha256(data).hexdigest()
    existing = db.query(Document).filter_by(candidate_id=candidate.id, sha256=sha).one_or_none()
    if existing:
        return existing, False

    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=candidate.organization_id,
        candidate_id=candidate.id,
        kind=kind.value,
        original_filename=display_name,
        stored_name=f"{uuid.uuid4().hex}{ext}",
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha,
        uploaded_by=principal.id if principal else None,
    )
    path = storage_path(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)

    db.add(doc)
    db.add(
        ProcessingJob(
            organization_id=doc.organization_id,
            document_id=doc.id,
            status=JobState.PENDING.value,
            provider=settings.extraction_provider,
            max_attempts=settings.max_job_attempts,
        )
    )
    audit.record(
        db,
        org_id=doc.organization_id,
        actor=principal,
        entity_type="document",
        entity_id=doc.id,
        candidate_id=candidate.id,
        action="document.uploaded",
        summary=f"Uploaded {kind.value} document '{display_name}'",
        details={"size_bytes": len(data), "content_type": content_type},
    )
    try:
        db.commit()
    except IntegrityError:
        # Concurrent duplicate upload won the race: discard our copy and return theirs.
        db.rollback()
        path.unlink(missing_ok=True)
        existing = db.query(Document).filter_by(candidate_id=candidate.id, sha256=sha).one()
        return existing, False
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    db.refresh(doc)
    return doc, True

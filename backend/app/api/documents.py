from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.api.deps import DB, owned
from app.clock import today
from app.config import get_settings
from app.domain import DocumentKind, JobState
from app.errors import AppError, not_found
from app.models import Candidate, Document, ProcessingJob
from app.schemas import DocumentDetail, DocumentOut, JobOut, ProcessingJobRow, UploadOut
from app.security import CurrentPrincipal, Perm, Principal, require
from app.services import audit
from app.services.documents import storage_path, store_document
from app.services.evaluation import CANDIDATE_LOAD, readiness
from app.services.processing import requeue
from app.services.serializers import (
    UserNames,
    credential_out,
    document_out,
    experience_out,
    qualification_out,
    skill_out,
)

router = APIRouter(tags=["documents"])


@router.post("/candidates/{candidate_id}/documents", response_model=UploadOut, status_code=201)
async def upload_document(
    candidate_id: str,
    db: DB,
    file: UploadFile = File(...),
    kind: DocumentKind = Form(...),
    principal: Principal = require(Perm.UPLOAD_DOCUMENTS),
):  # type: ignore[no-untyped-def]
    candidate = owned(db, Candidate, candidate_id, principal.org_id, "Candidate")
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)  # bounded read: never buffer more than limit + 1 bytes
    if len(data) > limit:
        raise AppError(413, "file_too_large", f"File exceeds the {limit // (1024 * 1024)} MB limit.")
    doc, created = store_document(db, principal, candidate, file.filename or "document", data, kind)
    out = UploadOut(document=document_out(doc, UserNames(db, principal.org_id)), created=created)
    # 200 (not 201) tells the client this exact file was already on record: nothing new was queued.
    return JSONResponse(out.model_dump(mode="json"), status_code=201 if created else 200)


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, principal: CurrentPrincipal, db: DB) -> DocumentDetail:
    doc = owned(db, Document, document_id, principal.org_id, "Document")
    candidate = owned(db, Candidate, doc.candidate_id, principal.org_id, "Candidate", options=CANDIDATE_LOAD)
    users = UserNames(db, principal.org_id)
    r = readiness(candidate, today())
    by_doc = lambda rows: [x for x in rows if x.document_id == doc.id]  # noqa: E731
    exps, quals, skills, creds = by_doc(candidate.experiences), by_doc(candidate.qualifications), by_doc(candidate.skills), by_doc(candidate.credentials)
    counts = {"experience": len(exps), "qualification": len(quals), "skill": len(skills), "credential": len(creds)}
    return DocumentDetail(
        **document_out(doc, users, counts).model_dump(),
        candidate_name=candidate.full_name,
        text=doc.text,
        experiences=[experience_out(e, users, today()) for e in exps],
        qualifications=[qualification_out(q, users) for q in quals],
        skills=[skill_out(s, users) for s in skills],
        credentials=[credential_out(c, users, r) for c in creds],
    )


@router.get("/documents/{document_id}/file")
def download_document(document_id: str, principal: CurrentPrincipal, db: DB) -> FileResponse:
    doc = owned(db, Document, document_id, principal.org_id, "Document")
    path = storage_path(doc)
    if not path.exists():
        raise not_found("Stored file")
    return FileResponse(
        path,
        media_type=doc.content_type,
        filename=doc.original_filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.post("/documents/{document_id}/process", response_model=DocumentOut, status_code=202)
def reprocess_document(document_id: str, db: DB, principal: Principal = require(Perm.UPLOAD_DOCUMENTS)) -> DocumentOut:
    """Retry a failed job or re-run extraction. Idempotent while a job is queued or running."""
    doc = owned(db, Document, document_id, principal.org_id, "Document")
    job = doc.job
    if job is None:
        raise not_found("Processing job")
    if job.status in (JobState.PENDING.value, JobState.PROCESSING.value):
        return document_out(doc, UserNames(db, principal.org_id))
    previous = job.status
    requeue(db, job, reset_attempts=True)
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="document",
        entity_id=doc.id,
        candidate_id=doc.candidate_id,
        action="document.retry_requested" if previous == JobState.FAILED.value else "document.reprocess_requested",
        summary=f"{'Retried' if previous == JobState.FAILED.value else 'Re-ran'} extraction for '{doc.original_filename}'",
        details={"previous_status": previous, "previous_error": job.error_code},
    )
    db.commit()
    db.refresh(doc)
    return document_out(doc, UserNames(db, principal.org_id))


@router.get("/processing-jobs", response_model=list[ProcessingJobRow])
def list_jobs(principal: CurrentPrincipal, db: DB, status: JobState | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[ProcessingJobRow]:
    q = (
        db.query(ProcessingJob, Document, Candidate)
        .join(Document, Document.id == ProcessingJob.document_id)
        .join(Candidate, Candidate.id == Document.candidate_id)
        .filter(ProcessingJob.organization_id == principal.org_id)
    )
    if status:
        q = q.filter(ProcessingJob.status == status.value)
    rows = q.order_by(ProcessingJob.created_at.desc()).limit(limit).all()
    return [
        ProcessingJobRow(
            **JobOut.model_validate(job).model_dump(),
            document_filename=doc.original_filename,
            document_kind=doc.kind,
            candidate_id=cand.id,
            candidate_name=cand.full_name,
        )
        for job, doc, cand in rows
    ]

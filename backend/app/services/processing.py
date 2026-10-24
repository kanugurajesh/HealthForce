"""Document processing jobs: atomic claim, lease reclaim, bounded retries, idempotent apply.

State machine:  pending ──claim──▶ processing ──▶ succeeded
                   ▲                    │
                   └── retryable error ─┤ (attempts < max_attempts, with backoff)
                                        └──▶ failed  (permanent error or attempts exhausted)
A failed job can be re-queued manually (attempt counter resets); a succeeded document can be
re-processed. Re-processing never overwrites claims a person has reviewed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.domain import ClaimSource, DocumentKind, EvidenceStatus, JobState, ReviewState
from app.extraction.errors import ExtractionError
from app.extraction.pipeline import ExtractionPlan, PlannedClaim, build_plan
from app.extraction.providers import ExtractionProvider, get_provider
from app.extraction.text import detect_injection, extract_text, redact_pii
from app.models import Candidate, Credential, Document, Experience, ProcessingJob, Qualification, Skill
from app.services import audit
from app.services.documents import storage_path

log = logging.getLogger("app.processing")

BACKOFF_SECONDS = (5, 30, 120)
LEASE = timedelta(minutes=10)
CLAIM_MODELS: dict[str, type[Any]] = {"experience": Experience, "qualification": Qualification, "skill": Skill, "credential": Credential}


# --------------------------------------------------------------------------- queue operations


def claim(db: Session, job_id: str | None = None) -> str | None:
    """Atomically move one due pending job to processing. Safe under concurrent workers."""
    now = utcnow()
    q = (
        select(ProcessingJob.id)
        .where(ProcessingJob.status == JobState.PENDING.value)
        .where(or_(ProcessingJob.next_attempt_at.is_(None), ProcessingJob.next_attempt_at <= now))
        .order_by(ProcessingJob.created_at)
        .limit(1)
    )
    if job_id:
        q = q.where(ProcessingJob.id == job_id)
    candidate_id = db.scalar(q)
    if not candidate_id:
        return None
    result = db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == candidate_id, ProcessingJob.status == JobState.PENDING.value)
        .values(status=JobState.PROCESSING.value, attempts=ProcessingJob.attempts + 1, locked_at=now, started_at=now)
    )
    db.commit()
    return candidate_id if result.rowcount == 1 else None  # type: ignore[attr-defined]


def reclaim_stale(db: Session) -> int:
    """Jobs whose worker died mid-processing: retry if attempts remain, else fail."""
    cutoff = utcnow() - LEASE
    stale = db.scalars(select(ProcessingJob).where(ProcessingJob.status == JobState.PROCESSING.value, ProcessingJob.locked_at < cutoff)).all()
    for job in stale:
        err = ExtractionError("processing_timeout", "Processing did not finish (the worker stopped or timed out).", retryable=True)
        _fail_or_retry(db, job, err)
    db.commit()
    return len(stale)


def requeue(db: Session, job: ProcessingJob, *, reset_attempts: bool) -> None:
    job.status = JobState.PENDING.value
    job.next_attempt_at = None
    job.locked_at = None
    job.finished_at = None
    if reset_attempts:
        job.attempts = 0
    job.provider = get_settings().extraction_provider


def _fail_or_retry(db: Session, job: ProcessingJob, err: ExtractionError) -> None:
    job.error_code, job.last_error, job.retryable = err.code, err.message, err.retryable
    job.locked_at = None
    if err.retryable and job.attempts < job.max_attempts:
        delay = BACKOFF_SECONDS[min(job.attempts - 1, len(BACKOFF_SECONDS) - 1)]
        job.status = JobState.PENDING.value
        job.next_attempt_at = utcnow() + timedelta(seconds=delay)
        log.warning("job will retry", extra={"job_id": job.id, "code": err.code, "attempt": job.attempts, "delay_s": delay})
        return
    job.status = JobState.FAILED.value
    job.finished_at = utcnow()
    doc = db.get(Document, job.document_id)
    audit.record(
        db,
        org_id=job.organization_id,
        actor=None,
        entity_type="document",
        entity_id=job.document_id,
        candidate_id=doc.candidate_id if doc else None,
        action="document.processing_failed",
        summary=f"Processing failed for '{doc.original_filename if doc else job.document_id}': {err.message}",
        details={"error_code": err.code, "attempts": job.attempts},
    )
    log.error("job failed", extra={"job_id": job.id, "code": err.code, "attempts": job.attempts})


# --------------------------------------------------------------------------- processing


def process_job(job_id: str, provider: ExtractionProvider | None = None, session_factory: Callable[[], Session] = SessionLocal) -> str:
    """Run one claimed job to completion. A job that is not in `processing` is left untouched,
    so a duplicate delivery of the same job id is a no-op."""
    started = time.monotonic()
    with session_factory() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None or job.status != JobState.PROCESSING.value:
            return job.status if job else "missing"
        try:
            provider = provider or get_provider()
            doc = job.document
            if doc.text is None:
                path = storage_path(doc)
                if not path.exists():
                    raise ExtractionError("file_missing", "The stored file is missing. Upload the document again.")
                extracted = extract_text(path.read_bytes(), doc.content_type)
                doc.text, redactions = redact_pii(extracted.text)
                doc.page_count = extracted.page_count
            else:
                redactions = {}
            signals = detect_injection(doc.text)
            doc.injection_suspected, doc.injection_signals = bool(signals), signals

            raw = provider.extract(doc.text, doc.kind)
            plan = build_plan(raw, doc.text, injection_signals=signals)
            applied = apply_plan(db, doc, plan, provider.source)

            job.status = JobState.SUCCEEDED.value
            job.provider = provider.name
            job.finished_at = utcnow()
            job.locked_at = None
            job.error_code = job.last_error = None
            job.retryable = False
            job.warnings = plan.warnings + applied["warnings"]
            job.stats = {**plan.stats, **applied["stats"], "redactions": redactions, "duration_ms": int((time.monotonic() - started) * 1000)}
            audit.record(
                db,
                org_id=doc.organization_id,
                actor=None,
                entity_type="document",
                entity_id=doc.id,
                candidate_id=doc.candidate_id,
                action="document.processed",
                summary=f"Extracted {applied['stats']['inserted']} claim(s) from '{doc.original_filename}' using the {provider.name} provider"
                + (" — instruction-like text detected, review carefully" if signals else ""),
                details={"provider": provider.name, **job.stats},
            )
            db.commit()
            log.info("job succeeded", extra={"job_id": job.id, "provider": provider.name, "claims": applied["stats"]["inserted"]})
        except ExtractionError as err:
            db.rollback()
            job = db.get(ProcessingJob, job_id)
            assert job is not None
            _fail_or_retry(db, job, err)
            db.commit()
        except Exception:
            log.exception("unexpected processing error", extra={"job_id": job_id})
            db.rollback()
            job = db.get(ProcessingJob, job_id)
            assert job is not None
            _fail_or_retry(db, job, ExtractionError("internal_error", "Unexpected processing error.", retryable=True))
            db.commit()
        return job.status


def run_now(job_id: str, provider: ExtractionProvider | None = None) -> str:
    """Synchronously claim and process a specific job (seed script, tests, CLI)."""
    with SessionLocal() as db:
        claimed = claim(db, job_id)
    if not claimed:
        with SessionLocal() as db:
            job = db.get(ProcessingJob, job_id)
            return job.status if job else "missing"
    return process_job(job_id, provider)


# --------------------------------------------------------------------------- applying results


def _row_key(kind: str, row: Any) -> tuple[Any, ...]:
    """Same identity as PlannedClaim.dedupe_key, computed from a stored row."""
    fields = {
        c: getattr(row, c, None) for c in ("type_code", "identifier", "expiration_date", "issue_date", "code", "name", "institution", "title", "start_date")
    }
    return PlannedClaim(kind, fields, None, None, None, EvidenceStatus.NONE).dedupe_key()


def _names_match(document_name: str, candidate_name: str) -> bool:
    doc_tokens = {t.strip(".,").lower() for t in document_name.split()}
    cand_tokens = [t.strip(".,").lower() for t in candidate_name.split()]
    return bool(cand_tokens) and cand_tokens[0] in doc_tokens and cand_tokens[-1] in doc_tokens


def apply_plan(db: Session, doc: Document, plan: ExtractionPlan, source: ClaimSource) -> dict[str, Any]:
    """Replace this document's *unreviewed machine* claims with the new plan, keeping every
    human-reviewed or manual claim. Runs inside the caller's transaction."""
    candidate: Candidate = doc.candidate
    warnings: list[str] = []
    name_flag = None
    if plan.candidate_name and not _names_match(plan.candidate_name, candidate.full_name):
        name_flag = f"Name on the document ('{plan.candidate_name}') does not match the candidate record ('{candidate.full_name}')."
        warnings.append(name_flag)

    kept_keys: set[tuple[Any, ...]] = set()
    removed = 0
    for kind, model in CLAIM_MODELS.items():
        for row in db.scalars(select(model).where(model.document_id == doc.id)).all():
            if row.review_state == ReviewState.UNREVIEWED.value and row.source != ClaimSource.MANUAL.value:
                db.delete(row)
                removed += 1
            else:
                kept_keys.add(_row_key(kind, row))
    db.flush()

    inserted = 0
    for claim in plan.claims:
        if claim.dedupe_key() in kept_keys:
            continue
        flags = ([name_flag] if name_flag else []) + claim.flags
        db.add(
            CLAIM_MODELS[claim.kind](
                organization_id=doc.organization_id,
                candidate_id=candidate.id,
                document_id=doc.id,
                source=source.value,
                evidence_quote=claim.evidence_quote,
                evidence_start=claim.evidence_start,
                evidence_end=claim.evidence_end,
                evidence_status=claim.evidence_status.value,
                review_state=ReviewState.UNREVIEWED.value,
                flags=flags,
                **claim.fields,
            )
        )
        inserted += 1

    if plan.summary and doc.kind == DocumentKind.RESUME.value and not candidate.summary_reviewed:
        candidate.summary = plan.summary
        candidate.summary_source = source.value
    return {"warnings": warnings, "stats": {"inserted": inserted, "replaced": removed, "kept_reviewed": len(kept_keys)}}


# --------------------------------------------------------------------------- background worker


class Worker:
    """Single in-process polling worker (see DECISIONS.md ADR-003)."""

    def __init__(self, poll_seconds: float) -> None:
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_reclaim = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="extraction-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    if time.monotonic() - self._last_reclaim > 30:
                        reclaim_stale(db)
                        self._last_reclaim = time.monotonic()
                    job_id = claim(db)
                if job_id:
                    process_job(job_id)
                    continue
            except Exception:
                log.exception("worker loop error")
            self._stop.wait(self.poll_seconds)

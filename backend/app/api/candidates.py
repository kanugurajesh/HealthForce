from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DB, owned
from app.clock import today
from app.db import utcnow
from app.domain import ClaimSource, Eligibility, EvidenceStatus, ReviewState, VerificationStatus, credential_label
from app.models import AuditEvent, Candidate, CandidateNote, Credential, JobRole
from app.schemas import (
    AuditOut,
    CandidateCreate,
    CandidateDetail,
    CandidateListItem,
    CandidateUpdate,
    ManualCredentialCreate,
    NoteCreate,
    StatusChange,
    SummaryUpdate,
)
from app.security import CurrentPrincipal, Perm, Principal, require
from app.services import audit
from app.services.evaluation import CANDIDATE_LOAD, load_candidates, readiness
from app.services.serializers import audit_out, candidate_detail, candidate_list_item
from app.services.workflow import change_status

router = APIRouter(prefix="/candidates", tags=["candidates"])


def _load(db: DB, principal: Principal, candidate_id: str) -> Candidate:
    return owned(db, Candidate, candidate_id, principal.org_id, "Candidate", options=CANDIDATE_LOAD)


def _detail(db: DB, principal: Principal, candidate_id: str) -> CandidateDetail:
    db.expire_all()
    c = _load(db, principal, candidate_id)
    return candidate_detail(db, c, readiness(c, today()), today())


def _check_job(db: DB, principal: Principal, job_id: str | None) -> None:
    if job_id:
        owned(db, JobRole, job_id, principal.org_id, "Job role")


@router.get("", response_model=dict[str, Any])
def list_candidates(
    principal: CurrentPrincipal,
    db: DB,
    q: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, description="Comma-separated candidate statuses"),
    job_id: str | None = None,
    credential_status: str | None = Query(default=None, description="Comma-separated, any-of: e.g. expired,missing,expiring_soon"),
    eligibility: Eligibility | None = None,
    review: str | None = Query(default=None, pattern="^(needs_review|flagged|reviewed)$"),
    expiring_within: int | None = Query(default=None, ge=0, le=365),
    missing_requirements: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    as_of = today()
    statuses = {s.strip() for s in status.split(",")} if status else None
    wanted_creds = {s.strip() for s in credential_status.split(",")} if credential_status else None
    needle = q.lower().strip() if q else None
    items: list[CandidateListItem] = []
    for c in load_candidates(db, principal.org_id):
        if statuses and c.status not in statuses:
            continue
        if job_id and c.job_id != job_id:
            continue
        if needle and not any(needle in (v or "").lower() for v in (c.full_name, c.headline, c.email, c.location)):
            continue
        r = readiness(c, as_of)
        if wanted_creds:
            held = set(r.credential_statuses)
            if any(a.expiring_soon for a in r.best_by_type.values()):
                held.add("expiring_soon")  # a flag that can co-exist with e.g. pending_review
            if not wanted_creds & held:
                continue
        if eligibility and (not r.match or r.match.eligibility != eligibility):
            continue
        if missing_requirements and (not r.match or r.match.eligibility not in (Eligibility.MISSING_INFORMATION, Eligibility.REQUIREMENT_NOT_MET)):
            continue
        if review == "needs_review" and r.unreviewed_claims == 0:
            continue
        if review == "flagged" and r.flagged_claims == 0:
            continue
        if review == "reviewed" and r.unreviewed_claims > 0:
            continue
        if expiring_within is not None and not (r.nearest_expiration and (r.nearest_expiration[0] - as_of).days <= expiring_within):
            continue
        items.append(candidate_list_item(c, r, as_of))
    return {"items": [i.model_dump(mode="json") for i in items[offset : offset + limit]], "total": len(items)}


@router.post("", response_model=CandidateDetail, status_code=201)
def create_candidate(body: CandidateCreate, db: DB, principal: Principal = require(Perm.MANAGE_CANDIDATES)) -> CandidateDetail:
    _check_job(db, principal, body.job_id)
    c = Candidate(organization_id=principal.org_id, **body.model_dump())
    db.add(c)
    db.flush()
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="candidate",
        entity_id=c.id,
        candidate_id=c.id,
        action="candidate.created",
        summary=f"Created candidate {c.full_name}",
    )
    db.commit()
    return _detail(db, principal, c.id)


@router.get("/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: str, principal: CurrentPrincipal, db: DB) -> CandidateDetail:
    return _detail(db, principal, candidate_id)


@router.patch("/{candidate_id}", response_model=CandidateDetail)
def update_candidate(candidate_id: str, body: CandidateUpdate, db: DB, principal: Principal = require(Perm.MANAGE_CANDIDATES)) -> CandidateDetail:
    c = _load(db, principal, candidate_id)
    changes = body.model_dump(exclude_unset=True)
    if "job_id" in changes:
        _check_job(db, principal, changes["job_id"])
    diff = {k: {"from": getattr(c, k), "to": v} for k, v in changes.items() if getattr(c, k) != v}
    if diff:
        for k, v in changes.items():
            setattr(c, k, v)
        audit.record(
            db,
            org_id=principal.org_id,
            actor=principal,
            entity_type="candidate",
            entity_id=c.id,
            candidate_id=c.id,
            action="candidate.updated",
            summary=f"Updated {', '.join(diff)} for {c.full_name}",
            details=diff,
        )
        db.commit()
    return _detail(db, principal, c.id)


@router.post("/{candidate_id}/status", response_model=CandidateDetail)
def set_status(candidate_id: str, body: StatusChange, db: DB, principal: Principal = require(Perm.MANAGE_CANDIDATES)) -> CandidateDetail:
    c = _load(db, principal, candidate_id)
    change_status(db, principal, c, body.status, body.reason)
    db.commit()
    return _detail(db, principal, c.id)


@router.put("/{candidate_id}/summary", response_model=CandidateDetail)
def review_summary(candidate_id: str, body: SummaryUpdate, db: DB, principal: Principal = require(Perm.REVIEW_CLAIMS)) -> CandidateDetail:
    """Accept (unchanged text) or correct the generated summary. Either way it becomes human-reviewed."""
    c = _load(db, principal, candidate_id)
    edited = body.summary != (c.summary or "")
    c.summary = body.summary
    c.summary_reviewed = True
    if edited:
        c.summary_source = ClaimSource.MANUAL.value
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="candidate",
        entity_id=c.id,
        candidate_id=c.id,
        action="summary.corrected" if edited else "summary.accepted",
        summary=f"{'Corrected' if edited else 'Accepted'} the profile summary for {c.full_name}",
    )
    db.commit()
    return _detail(db, principal, c.id)


@router.post("/{candidate_id}/notes", response_model=CandidateDetail, status_code=201)
def add_note(candidate_id: str, body: NoteCreate, db: DB, principal: Principal = require(Perm.ADD_NOTES)) -> CandidateDetail:
    c = _load(db, principal, candidate_id)
    note = CandidateNote(
        organization_id=principal.org_id,
        candidate_id=c.id,
        author_id=principal.id,
        kind=body.kind.value,
        decision=body.decision.value if body.decision else None,
        body=body.body,
    )
    db.add(note)
    db.flush()
    label = f"Recorded decision '{body.decision.value}'" if body.decision else "Added a note"
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="note",
        entity_id=note.id,
        candidate_id=c.id,
        action="note.decision" if body.decision else "note.added",
        summary=f"{label} for {c.full_name}",
        reason=body.body if body.decision else None,
    )
    db.commit()
    return _detail(db, principal, c.id)


@router.post("/{candidate_id}/credentials", response_model=CandidateDetail, status_code=201)
def add_manual_credential(candidate_id: str, body: ManualCredentialCreate, db: DB, principal: Principal = require(Perm.REVIEW_CLAIMS)) -> CandidateDetail:
    """Manual entry (e.g. after an unreadable scan). Entered by a reviewer, so it starts as accepted
    but unverified; the note records where the information came from."""
    c = _load(db, principal, candidate_id)
    cred = Credential(
        organization_id=principal.org_id,
        candidate_id=c.id,
        source=ClaimSource.MANUAL.value,
        evidence_status=EvidenceStatus.NONE.value,
        review_state=ReviewState.ACCEPTED.value,
        reviewed_by=principal.id,
        reviewed_at=utcnow(),
        review_note=body.note,
        verification_status=VerificationStatus.NOT_STARTED.value,
        name=credential_label(body.type_code),
        flags=[],
        **body.model_dump(exclude={"note"}),
    )
    db.add(cred)
    db.flush()
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="credential",
        entity_id=cred.id,
        candidate_id=c.id,
        action="credential.added_manually",
        summary=f"Manually added {credential_label(body.type_code)} for {c.full_name}",
        reason=body.note,
        details=body.model_dump(exclude={"note"}),
    )
    db.commit()
    return _detail(db, principal, c.id)


@router.get("/{candidate_id}/activity", response_model=list[AuditOut])
def candidate_activity(candidate_id: str, principal: CurrentPrincipal, db: DB, limit: int = Query(default=100, ge=1, le=500)) -> list[AuditOut]:
    c = owned(db, Candidate, candidate_id, principal.org_id, "Candidate")
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.organization_id == principal.org_id, AuditEvent.candidate_id == c.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [audit_out(e, {c.id: c.full_name}) for e in events]

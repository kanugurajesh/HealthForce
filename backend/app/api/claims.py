"""Human review of extracted claims: accept / reject / correct, bulk-accept, and verification."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.api.candidates import _detail
from app.api.deps import DB, owned, validate_body
from app.config import get_settings
from app.db import utcnow
from app.domain import EvidenceStatus, ReviewState, VerificationMethod, VerificationStatus, credential_label
from app.errors import AppError, conflict, not_found
from app.models import Credential, Document, Experience, Qualification, Skill
from app.schemas import (
    CandidateDetail,
    ClaimReview,
    CredentialPatch,
    ExperiencePatch,
    QualificationPatch,
    SkillPatch,
    VerificationIn,
)
from app.security import Perm, Principal, require
from app.services import audit

router = APIRouter(tags=["review"])

KINDS: dict[str, tuple[type[Any], type[Any], str]] = {
    "experiences": (Experience, ExperiencePatch, "experience"),
    "qualifications": (Qualification, QualificationPatch, "qualification"),
    "skills": (Skill, SkillPatch, "skill"),
    "credentials": (Credential, CredentialPatch, "credential"),
}
# Changing any of these on a verified credential invalidates the verification.
VERIFIED_FACTS = {"type_code", "identifier", "jurisdiction", "issue_date", "expiration_date"}


def _claim(db: DB, principal: Principal, kind: str, claim_id: str) -> tuple[Any, str]:
    if kind not in KINDS:
        raise not_found("Claim type")
    model, _, noun = KINDS[kind]
    return owned(db, model, claim_id, principal.org_id, noun.capitalize()), noun


def _describe(row: Any, noun: str) -> str:
    if noun == "credential":
        return credential_label(row.type_code)
    return getattr(row, "title", None) or getattr(row, "name", None) or noun


@router.post("/claims/{kind}/{claim_id}/review", response_model=CandidateDetail)
def review_claim(kind: str, claim_id: str, body: ClaimReview, db: DB, principal: Principal = require(Perm.REVIEW_CLAIMS)) -> CandidateDetail:
    row, noun = _claim(db, principal, kind, claim_id)
    target = ReviewState.ACCEPTED if body.action == "accept" else ReviewState.REJECTED
    if body.action == "accept" and row.evidence_status == EvidenceStatus.NOT_FOUND.value and not body.note:
        raise AppError(422, "note_required", "The evidence for this item could not be located in the document. Explain why you are accepting it.")
    previous = row.review_state
    row.review_state = target.value
    row.reviewed_by, row.reviewed_at = principal.id, utcnow()
    row.review_note = body.note
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type=noun,
        entity_id=row.id,
        candidate_id=row.candidate_id,
        action=f"claim.{target.value}",
        summary=f"{target.value.capitalize()} {noun} '{_describe(row, noun)}'",
        reason=body.note,
        details={"from": previous, "to": target.value, "flags_at_review": row.flags},
    )
    db.commit()
    return _detail(db, principal, row.candidate_id)


@router.patch("/claims/{kind}/{claim_id}", response_model=CandidateDetail)
def correct_claim(kind: str, claim_id: str, db: DB, payload: dict[str, Any] = Body(...), principal: Principal = require(Perm.REVIEW_CLAIMS)) -> CandidateDetail:
    row, noun = _claim(db, principal, kind, claim_id)
    patch = validate_body(KINDS[kind][1], payload)
    changes = patch.model_dump(exclude_unset=True, exclude={"note"})
    if not changes:
        raise AppError(422, "no_changes", "Provide at least one field to correct.")
    diff = {k: {"from": getattr(row, k), "to": v} for k, v in changes.items() if getattr(row, k) != v}
    if not diff:
        raise AppError(422, "no_changes", "The submitted values match the current values.")

    for k, v in changes.items():
        setattr(row, k, v.value if hasattr(v, "value") else ([s.value for s in v] if k == "settings" and v else v))
    if noun == "credential":
        if row.issue_date and row.expiration_date and row.issue_date > row.expiration_date:
            raise AppError(422, "validation_error", "Issue date must be on or before the expiration date.")
        if "expiration_date" in changes:
            row.expiration_text = None
        if row.verification_status != VerificationStatus.NOT_STARTED.value and VERIFIED_FACTS & diff.keys():
            diff["verification"] = {"from": row.verification_status, "to": "reset (facts changed after verification)"}
            row.verification_status = VerificationStatus.NOT_STARTED.value
            row.verification_method = row.verification_reference = row.verified_by = row.verified_at = None
    if noun == "experience":
        if row.start_date and row.end_date and row.end_date < row.start_date:
            raise AppError(422, "validation_error", "End date must be on or after the start date.")
        if changes.get("is_current"):
            row.end_date = None

    resolved_flags = row.flags
    row.review_state = ReviewState.CORRECTED.value
    row.reviewed_by, row.reviewed_at = principal.id, utcnow()
    row.review_note = patch.note  # type: ignore[attr-defined]
    row.flags = []
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type=noun,
        entity_id=row.id,
        candidate_id=row.candidate_id,
        action="claim.corrected",
        summary=f"Corrected {noun} '{_describe(row, noun)}' ({', '.join(k for k in diff if k != 'verification')})",
        reason=patch.note,
        details={"changes": diff, "resolved_flags": resolved_flags},  # type: ignore[attr-defined]
    )
    db.commit()
    return _detail(db, principal, row.candidate_id)


@router.post("/documents/{document_id}/accept-supported", response_model=CandidateDetail)
def accept_supported(document_id: str, db: DB, principal: Principal = require(Perm.REVIEW_CLAIMS)) -> CandidateDetail:
    """Accept, in one step, every unreviewed claim from a document whose evidence was located
    verbatim and which carries no flags. Anything else still needs individual review."""
    doc = owned(db, Document, document_id, principal.org_id, "Document")
    if doc.injection_suspected:
        raise conflict("This document contains instruction-like text. Review each item individually.")
    accepted = 0
    now = utcnow()
    for model, _, _noun in KINDS.values():
        rows = db.query(model).filter(model.document_id == doc.id, model.review_state == ReviewState.UNREVIEWED.value).all()
        for row in rows:
            if row.evidence_status == EvidenceStatus.FOUND.value and not row.flags:
                row.review_state = ReviewState.ACCEPTED.value
                row.reviewed_by, row.reviewed_at = principal.id, now
                accepted += 1
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="document",
        entity_id=doc.id,
        candidate_id=doc.candidate_id,
        action="claims.bulk_accepted",
        summary=f"Accepted {accepted} evidence-supported item(s) from '{doc.original_filename}'",
        details={"accepted": accepted},
    )
    db.commit()
    return _detail(db, principal, doc.candidate_id)


@router.post("/credentials/{credential_id}/verification", response_model=CandidateDetail)
def record_verification(credential_id: str, body: VerificationIn, db: DB, principal: Principal = require(Perm.VERIFY_CREDENTIALS)) -> CandidateDetail:
    cred = owned(db, Credential, credential_id, principal.org_id, "Credential")
    if cred.review_state not in (ReviewState.ACCEPTED.value, ReviewState.CORRECTED.value):
        raise conflict("Review and accept the credential's extracted details before recording verification.")
    if body.method == VerificationMethod.SIMULATED and get_settings().verification_mode != "simulated":
        raise conflict("Simulated verification is disabled on this server.")
    simulated = body.method == VerificationMethod.SIMULATED
    cred.verification_status = VerificationStatus.VERIFIED.value if body.outcome == "verified" else VerificationStatus.FAILED.value
    cred.verification_method = body.method.value
    cred.verification_reference = "SIMULATED — demo only; no external registry was contacted." if simulated else body.reference
    cred.verified_by, cred.verified_at = principal.id, utcnow()
    label = credential_label(cred.type_code)
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="credential",
        entity_id=cred.id,
        candidate_id=cred.candidate_id,
        action="credential.verified" if body.outcome == "verified" else "credential.verification_failed",
        summary=(f"Recorded SIMULATED verification of {label}" if simulated else f"Recorded primary-source verification ({body.outcome}) of {label}"),
        reason=cred.verification_reference,
        details={"method": body.method.value, "outcome": body.outcome},
    )
    db.commit()
    return _detail(db, principal, cred.candidate_id)

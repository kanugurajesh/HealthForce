"""Deterministic credential status rules.

Four independent facts feed a credential's status and are never conflated:
  1. extraction facts   — type, identifier, issue/expiration dates (from a document or manual entry)
  2. reviewer decision  — review_state (unreviewed / accepted / corrected / rejected)
  3. verification       — verification_status + method (manual primary-source attestation or simulated)
  4. time               — expiration date relative to the as-of date

Status precedence (first match wins):
  rejected  >  unable_to_determine (conflicting records)  >  expired
  >  unable_to_determine (no expiration date)  >  pending_review  >  pending_verification
  >  expiring_soon  >  verified

so an expired credential can never look ready because it was reviewed or verified earlier.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from app.domain import (
    CREDENTIAL_CATALOG,
    CredentialStatus,
    ReviewState,
    VerificationMethod,
    VerificationStatus,
    credential_label,
)

DEFAULT_EXPIRING_SOON_DAYS = 60

# Lower is better. Used to pick the best record when a candidate holds several of one type.
STATUS_RANK: dict[CredentialStatus, int] = {
    CredentialStatus.VERIFIED: 0,
    CredentialStatus.EXPIRING_SOON: 1,
    CredentialStatus.PENDING_VERIFICATION: 2,
    CredentialStatus.PENDING_REVIEW: 3,
    CredentialStatus.UNABLE_TO_DETERMINE: 4,
    CredentialStatus.EXPIRED: 5,
    CredentialStatus.REJECTED: 6,
    CredentialStatus.MISSING: 7,
}

# Statuses under which a credential satisfies a requirement today.
SATISFYING_STATUSES = {CredentialStatus.VERIFIED, CredentialStatus.EXPIRING_SOON}
PENDING_STATUSES = {CredentialStatus.PENDING_REVIEW, CredentialStatus.PENDING_VERIFICATION}


@dataclass(frozen=True)
class CredentialFacts:
    id: str
    type_code: str
    identifier: str | None = None
    issue_date: date | None = None
    expiration_date: date | None = None
    expiration_precision: str = "day"  # "day" | "month" | "year", from the printed date
    review_state: ReviewState = ReviewState.UNREVIEWED
    review_note: str | None = None
    verification_status: VerificationStatus = VerificationStatus.NOT_STARTED
    verification_method: VerificationMethod | None = None
    source_document_kind: str | None = None  # "resume" | "credential" | None (manual)
    document_id: str | None = None
    evidence_quote: str | None = None


@dataclass
class CredentialAssessment:
    credential_id: str
    type_code: str
    status: CredentialStatus
    reasons: list[str] = field(default_factory=list)
    expiring_soon: bool = False
    days_until_expiry: int | None = None
    simulated_verification: bool = False
    conflicts_with: list[str] = field(default_factory=list)


def _norm_identifier(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(ch for ch in value.upper() if ch.isalnum())
    return cleaned or None


def _distinct_instances(a: CredentialFacts, b: CredentialFacts) -> bool:
    """True when two records are provably different credential instances (e.g. a renewal)."""
    ida, idb = _norm_identifier(a.identifier), _norm_identifier(b.identifier)
    if ida and idb and ida != idb:
        return True
    return bool(a.issue_date and b.issue_date and a.issue_date != b.issue_date)


def _same_expiry(a: CredentialFacts, b: CredentialFacts) -> bool:
    """Dates agree, allowing for precision: "12/2027" is consistent with Dec 15, 2027."""
    ea, eb = a.expiration_date, b.expiration_date
    if ea is None or eb is None or ea == eb:
        return True
    precisions = {a.expiration_precision, b.expiration_precision}
    if "year" in precisions:
        return ea.year == eb.year
    if "month" in precisions:
        return (ea.year, ea.month) == (eb.year, eb.month)
    return False


def find_conflicts(records: Iterable[CredentialFacts]) -> dict[str, list[str]]:
    """Map credential id -> ids of records that contradict it.

    Two non-rejected records of the same type contradict each other when they disagree on the
    expiration date (beyond the precision printed) and nothing (different identifier or different issue date) shows they are
    separate instances. The system never picks a winner; a reviewer must reject one.
    """
    by_type: dict[str, list[CredentialFacts]] = defaultdict(list)
    for r in records:
        if r.review_state != ReviewState.REJECTED:
            by_type[r.type_code].append(r)
    conflicts: dict[str, list[str]] = defaultdict(list)
    for group in by_type.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if not _same_expiry(a, b) and not _distinct_instances(a, b):
                    conflicts[a.id].append(b.id)
                    conflicts[b.id].append(a.id)
    return dict(conflicts)


def assess_credential(
    c: CredentialFacts,
    as_of: date,
    *,
    conflicts_with: Sequence[str] = (),
    expiring_soon_days: int = DEFAULT_EXPIRING_SOON_DAYS,
) -> CredentialAssessment:
    entry = CREDENTIAL_CATALOG.get(c.type_code)
    requires_expiration = entry.expires if entry else False
    days = (c.expiration_date - as_of).days if c.expiration_date else None
    a = CredentialAssessment(
        credential_id=c.id,
        type_code=c.type_code,
        status=CredentialStatus.VERIFIED,
        days_until_expiry=days,
        expiring_soon=days is not None and 0 <= days <= expiring_soon_days,
        simulated_verification=c.verification_status == VerificationStatus.VERIFIED and c.verification_method == VerificationMethod.SIMULATED,
        conflicts_with=list(conflicts_with),
    )

    if c.review_state == ReviewState.REJECTED:
        a.status = CredentialStatus.REJECTED
        a.reasons.append("Rejected by reviewer" + (f": {c.review_note}" if c.review_note else "."))
    elif c.verification_status == VerificationStatus.FAILED:
        a.status = CredentialStatus.REJECTED
        a.reasons.append("Verification failed — the credential could not be confirmed with the primary source.")
    elif conflicts_with:
        a.status = CredentialStatus.UNABLE_TO_DETERMINE
        a.reasons.append(
            "Another record for this credential shows a different expiration date. Reject the incorrect or outdated record to resolve the conflict."
        )
    elif days is not None and days < 0:
        a.status = CredentialStatus.EXPIRED
        a.reasons.append(f"Expired on {c.expiration_date:%b %d, %Y} ({-days} days ago).")
    elif requires_expiration and c.expiration_date is None:
        a.status = CredentialStatus.UNABLE_TO_DETERMINE
        a.reasons.append("No expiration date could be established from the evidence. Enter it after checking the source.")
    elif c.review_state == ReviewState.UNREVIEWED:
        a.status = CredentialStatus.PENDING_REVIEW
        a.reasons.append("Extracted data has not been reviewed by a person.")
    elif c.verification_status != VerificationStatus.VERIFIED:
        a.status = CredentialStatus.PENDING_VERIFICATION
        a.reasons.append("Reviewed, but not yet verified against a primary source.")
    elif a.expiring_soon:
        a.status = CredentialStatus.EXPIRING_SOON
        a.reasons.append(f"Verified; expires in {days} days ({c.expiration_date:%b %d, %Y}).")
    else:
        a.status = CredentialStatus.VERIFIED
        a.reasons.append("Reviewed and verified" + (f"; valid until {c.expiration_date:%b %d, %Y}." if c.expiration_date else "."))

    if a.simulated_verification and a.status in SATISFYING_STATUSES:
        a.reasons.append("Verification was SIMULATED for the demo — no external registry was contacted.")
    if c.source_document_kind == "resume":
        a.reasons.append("Self-reported on a resume, not taken from a credential document.")
    return a


def assess_all(records: Sequence[CredentialFacts], as_of: date, *, expiring_soon_days: int = DEFAULT_EXPIRING_SOON_DAYS) -> dict[str, CredentialAssessment]:
    conflicts = find_conflicts(records)
    return {r.id: assess_credential(r, as_of, conflicts_with=conflicts.get(r.id, ()), expiring_soon_days=expiring_soon_days) for r in records}


@dataclass
class CredentialRequirementResult:
    status: CredentialStatus  # best status across any-of codes, or MISSING
    best: CredentialAssessment | None
    candidates: list[CredentialAssessment]
    label: str


def best_for_codes(codes: Sequence[str], assessments: Iterable[CredentialAssessment], records_by_id: dict[str, CredentialFacts]) -> CredentialRequirementResult:
    """Pick the best-ranked record among the accepted codes (see key() for tie-breaks)."""
    pool = [a for a in assessments if a.type_code in codes]
    label = " or ".join(credential_label(c) for c in codes)
    if not pool:
        return CredentialRequirementResult(CredentialStatus.MISSING, None, [], label)

    def key(a: CredentialAssessment) -> tuple[int, int, int]:
        rec = records_by_id[a.credential_id]
        exp = rec.expiration_date
        # Ties prefer the later expiration, then a credential document over a resume mention.
        return (STATUS_RANK[a.status], -(exp.toordinal() if exp else 0), 1 if rec.source_document_kind == "resume" else 0)

    pool.sort(key=key)
    return CredentialRequirementResult(pool[0].status, pool[0], pool, label)

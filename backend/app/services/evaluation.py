"""Builds rule inputs from ORM rows and computes readiness/match on read.

Readiness is computed on read (cheap at demo scale and always consistent with the latest
review/verification/time facts). At larger scale this would be materialized and refreshed
on change — see ARCHITECTURE.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.dates import parse_date_text
from app.domain import (
    CandidateStatus,
    CredentialStatus,
    Eligibility,
    JobState,
    RequirementKind,
    RequirementOutcome,
    ReviewState,
    VerificationMethod,
    VerificationStatus,
)
from app.models import Candidate, Document, JobRole
from app.rules.credentials import CredentialAssessment, CredentialFacts, assess_all, best_for_codes
from app.rules.matching import (
    CandidateFacts,
    ClaimFacts,
    ExperienceFacts,
    MatchResult,
    NextAction,
    RequirementSpec,
    evaluate_match,
)

CANDIDATE_LOAD = (
    selectinload(Candidate.documents).selectinload(Document.job),
    selectinload(Candidate.experiences),
    selectinload(Candidate.qualifications),
    selectinload(Candidate.skills),
    selectinload(Candidate.credentials),
    selectinload(Candidate.tasks),
    selectinload(Candidate.job).selectinload(JobRole.requirements),
)


def credential_facts(candidate: Candidate) -> list[CredentialFacts]:
    doc_kind = {d.id: d.kind for d in candidate.documents}
    return [
        CredentialFacts(
            id=c.id,
            type_code=c.type_code,
            identifier=c.identifier,
            issue_date=c.issue_date,
            expiration_date=c.expiration_date,
            expiration_precision=_precision(c.expiration_text),
            review_state=ReviewState(c.review_state),
            review_note=c.review_note,
            verification_status=VerificationStatus(c.verification_status),
            verification_method=VerificationMethod(c.verification_method) if c.verification_method else None,
            source_document_kind=doc_kind.get(c.document_id) if c.document_id else None,
            document_id=c.document_id,
            evidence_quote=c.evidence_quote,
        )
        for c in candidate.credentials
    ]


def _precision(text: str | None) -> str:
    parsed = parse_date_text(text, period_end=True) if text else None
    return parsed.precision if parsed else "day"


def candidate_facts(candidate: Candidate, as_of: date) -> CandidateFacts:
    creds = credential_facts(candidate)
    return CandidateFacts(
        credentials=creds,
        credential_assessments=assess_all(creds, as_of, expiring_soon_days=get_settings().expiring_soon_days),
        qualifications=[ClaimFacts(q.id, q.code, ReviewState(q.review_state), q.evidence_quote, q.document_id) for q in candidate.qualifications],
        skills=[ClaimFacts(s.id, s.code, ReviewState(s.review_state), s.evidence_quote, s.document_id) for s in candidate.skills],
        experiences=[
            ExperienceFacts(
                e.id, e.title, e.start_date, e.end_date, e.is_current, tuple(e.settings or ()), ReviewState(e.review_state), e.evidence_quote, e.document_id
            )
            for e in candidate.experiences
        ],
    )


def requirement_specs(job: JobRole) -> list[RequirementSpec]:
    return [
        RequirementSpec(
            id=r.id,
            kind=RequirementKind(r.kind),
            label=r.label,
            codes=tuple(r.codes or ()),
            is_required=r.is_required,
            weight=r.weight,
            min_years=r.min_years,
            setting=r.setting,
            min_valid_days=r.min_valid_days,
        )
        for r in job.requirements
    ]


def match(candidate: Candidate, job: JobRole, as_of: date, facts: CandidateFacts | None = None) -> MatchResult:
    return evaluate_match(requirement_specs(job), facts or candidate_facts(candidate, as_of), as_of)


@dataclass
class Readiness:
    """Everything the list, dashboard and filters need about one candidate."""

    facts: CandidateFacts
    match: MatchResult | None
    credential_statuses: set[str]  # statuses of held credentials + "missing" for required-but-absent
    missing_credentials: list[str]
    unreviewed_claims: int
    flagged_claims: int
    nearest_expiration: tuple[date, str] | None
    best_by_type: dict[str, CredentialAssessment]
    tasks_total: int
    tasks_done: int
    next_actions: list[NextAction] = field(default_factory=list)

    @property
    def assessments(self) -> dict[str, CredentialAssessment]:
        return self.facts.credential_assessments


def readiness(candidate: Candidate, as_of: date) -> Readiness:
    facts = candidate_facts(candidate, as_of)
    result = match(candidate, candidate.job, as_of, facts) if candidate.job else None
    records = {c.id: c for c in facts.credentials}
    # Status per credential *type* uses the best record, so a weaker duplicate (e.g. an undated
    # resume mention next to a verified license document) does not mislabel the candidate.
    best_by_type: dict[str, CredentialAssessment] = {}
    for code in {c.type_code for c in facts.credentials}:
        best = best_for_codes([code], facts.credential_assessments.values(), records).best
        if best:
            best_by_type[code] = best
    statuses = {a.status.value for a in best_by_type.values()}
    missing: list[str] = []
    if candidate.job:
        for req in candidate.job.requirements:
            if (
                req.kind == RequirementKind.CREDENTIAL.value
                and req.is_required
                and best_for_codes(req.codes, facts.credential_assessments.values(), records).status == CredentialStatus.MISSING
            ):
                missing.append(req.label)
        if missing:
            statuses.add(CredentialStatus.MISSING.value)

    claims: list[Any] = [*candidate.experiences, *candidate.qualifications, *candidate.skills, *candidate.credentials]
    upcoming = [
        (exp, a.type_code)
        for a in best_by_type.values()
        if (exp := records[a.credential_id].expiration_date) and exp >= as_of and a.status != CredentialStatus.REJECTED
    ]
    tasks = candidate.tasks
    status = CandidateStatus(candidate.status)
    actions = [] if status in (CandidateStatus.WITHDRAWN, CandidateStatus.NOT_SELECTED) else list(result.next_actions) if result else []
    if status == CandidateStatus.CLEARED:
        actions = [a for a in actions if a.priority < 100]  # once cleared, only required requirements matter
    actions.extend(pipeline_actions(candidate, result, sum(1 for c in claims if c.review_state == ReviewState.UNREVIEWED.value)))
    actions.sort(key=lambda a: a.priority)
    return Readiness(
        facts=facts,
        match=result,
        credential_statuses=statuses,
        missing_credentials=missing,
        unreviewed_claims=sum(1 for c in claims if c.review_state == ReviewState.UNREVIEWED.value),
        flagged_claims=sum(1 for c in claims if c.flags and c.review_state == ReviewState.UNREVIEWED.value),
        nearest_expiration=min(upcoming) if upcoming else None,
        best_by_type=best_by_type,
        tasks_total=len(tasks),
        tasks_done=sum(1 for t in tasks if t.status in ("done", "waived")),
        next_actions=actions,
    )


def pipeline_actions(candidate: Candidate, result: MatchResult | None, unreviewed: int) -> list[NextAction]:
    """Workflow-level suggestions layered on top of requirement-level actions."""
    status = CandidateStatus(candidate.status)
    if status in (CandidateStatus.WITHDRAWN, CandidateStatus.NOT_SELECTED, CandidateStatus.CLEARED):
        return []
    actions: list[NextAction] = []
    for doc in candidate.documents:
        if doc.job and doc.job.status == JobState.FAILED.value:
            actions.append(NextAction(4, f"Processing failed for '{doc.original_filename}': retry it or enter the details manually."))
    if candidate.job is None:
        actions.append(NextAction(5, "Assign a job role to evaluate this candidate against its requirements."))
    if unreviewed and not any("Review" in a.label for a in (result.next_actions if result else [])):
        actions.append(NextAction(55, f"Review {unreviewed} extracted item(s) awaiting confirmation."))
    if result and result.eligibility == Eligibility.MEETS_ALL_REQUIRED:
        nxt = {
            CandidateStatus.NEW: "Move to screening — all required requirements are met.",
            CandidateStatus.SCREENING: "Schedule an interview — all required requirements are met.",
            CandidateStatus.INTERVIEW: "Record the interview decision and prepare an offer.",
            CandidateStatus.OFFER: "Start onboarding once the offer is accepted.",
        }.get(status)
        if nxt:
            actions.append(NextAction(90, nxt))
    if status == CandidateStatus.ONBOARDING:
        open_tasks = [t for t in candidate.tasks if t.status not in ("done", "waived")]
        if open_tasks:
            actions.append(NextAction(85, f"Complete {len(open_tasks)} remaining onboarding task(s)."))
        elif result and result.eligibility == Eligibility.MEETS_ALL_REQUIRED:
            actions.append(NextAction(80, "All onboarding tasks are complete — mark the candidate cleared to start."))
    return actions


def load_candidates(db: Session, org_id: str) -> list[Candidate]:
    return list(db.query(Candidate).options(*CANDIDATE_LOAD).filter(Candidate.organization_id == org_id).order_by(Candidate.updated_at.desc()).all())


def outcome_counts(result: MatchResult) -> dict[str, int]:
    return {o.value: sum(1 for r in result.requirements if r.outcome == o) for o in RequirementOutcome}

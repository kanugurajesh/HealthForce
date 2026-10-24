"""ORM + computed readiness → API output models."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.domain import ReviewState, credential_label, qualification_label, skill_label
from app.models import (
    AuditEvent,
    Candidate,
    CandidateNote,
    Credential,
    Document,
    Experience,
    JobRole,
    OnboardingTask,
    Qualification,
    Skill,
    User,
)
from app.rules.matching import MatchResult, merged_years
from app.schemas import (
    AuditOut,
    CandidateDetail,
    CandidateListItem,
    CredentialOut,
    DocumentOut,
    EvidenceRefOut,
    ExperienceOut,
    ExpirationOut,
    JobBrief,
    JobOut,
    JobRoleOut,
    MatchOut,
    NextActionOut,
    NoteOut,
    QualificationOut,
    RequirementOut,
    RequirementResultOut,
    SkillOut,
    TaskOut,
    UserBrief,
)
from app.services.evaluation import Readiness
from app.services.workflow import allowed_transitions, clearance_blockers, task_blockers


class UserNames:
    """Resolves user ids to display names with one query per request."""

    def __init__(self, db: Session, org_id: str) -> None:
        self._users = {u.id: u for u in db.query(User).filter(User.organization_id == org_id).all()}

    def name(self, user_id: str | None) -> str | None:
        u = self._users.get(user_id) if user_id else None
        return u.full_name if u else None

    def brief(self, user_id: str | None) -> UserBrief | None:
        u = self._users.get(user_id) if user_id else None
        return UserBrief(id=u.id, full_name=u.full_name, role=u.role) if u else None


def _claim_base(row: Any, users: UserNames) -> dict[str, Any]:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "source": row.source,
        "evidence_quote": row.evidence_quote,
        "evidence_start": row.evidence_start,
        "evidence_end": row.evidence_end,
        "evidence_status": row.evidence_status,
        "review_state": row.review_state,
        "reviewed_by_name": users.name(row.reviewed_by),
        "reviewed_at": row.reviewed_at,
        "review_note": row.review_note,
        "flags": row.flags or [],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def experience_out(e: Experience, users: UserNames, as_of: date) -> ExperienceOut:
    end = as_of if e.is_current else e.end_date
    years = round(merged_years([(e.start_date, end)]), 1) if e.start_date and end and end >= e.start_date else None
    return ExperienceOut(
        **_claim_base(e, users),
        title=e.title,
        employer=e.employer,
        settings=e.settings or [],
        start_date=e.start_date,
        end_date=e.end_date,
        is_current=e.is_current,
        start_text=e.start_text,
        end_text=e.end_text,
        description=e.description,
        duration_years=years,
    )


def qualification_out(q: Qualification, users: UserNames) -> QualificationOut:
    return QualificationOut(
        **_claim_base(q, users), code=q.code, label=qualification_label(q.code), name=q.name, institution=q.institution, completion_year=q.completion_year
    )


def skill_out(s: Skill, users: UserNames) -> SkillOut:
    return SkillOut(**_claim_base(s, users), code=s.code, label=skill_label(s.code) if s.code != "other" else s.name, name=s.name)


def credential_out(c: Credential, users: UserNames, readiness: Readiness | None) -> CredentialOut:
    a = readiness.assessments.get(c.id) if readiness else None
    return CredentialOut(
        **_claim_base(c, users),
        type_code=c.type_code,
        type_label=credential_label(c.type_code) if c.type_code != "OTHER" else f"Other — {c.name}",
        name=c.name,
        issuer=c.issuer,
        identifier=c.identifier,
        jurisdiction=c.jurisdiction,
        issue_date=c.issue_date,
        expiration_date=c.expiration_date,
        expiration_text=c.expiration_text,
        verification_status=c.verification_status,
        verification_method=c.verification_method,
        verification_reference=c.verification_reference,
        verified_at=c.verified_at,
        verified_by_name=users.name(c.verified_by),
        status=a.status.value if a else "",
        status_reasons=a.reasons if a else [],
        expiring_soon=a.expiring_soon if a else False,
        days_until_expiry=a.days_until_expiry if a else None,
        simulated_verification=a.simulated_verification if a else False,
        conflicts_with=a.conflicts_with if a else [],
    )


def job_out(job: Any) -> JobOut | None:
    return JobOut.model_validate(job) if job else None


def document_out(d: Document, users: UserNames, counts: dict[str, int] | None = None) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        candidate_id=d.candidate_id,
        kind=d.kind,
        original_filename=d.original_filename,
        content_type=d.content_type,
        size_bytes=d.size_bytes,
        page_count=d.page_count,
        injection_suspected=d.injection_suspected,
        injection_signals=d.injection_signals or [],
        created_at=d.created_at,
        uploaded_by_name=users.name(d.uploaded_by),
        job=job_out(d.job),
        claim_counts=counts or {},
    )


def match_out(job: JobRole, m: MatchResult) -> MatchOut:
    return MatchOut(
        job=JobBrief(id=job.id, title=job.title),
        score=m.score,
        eligibility=m.eligibility.value,
        eligibility_explanation=m.eligibility_explanation,
        score_explanation=m.score_explanation,
        satisfied=m.satisfied,
        not_satisfied=m.not_satisfied,
        pending=m.pending,
        unknown=m.unknown,
        requirements=[
            RequirementResultOut(
                requirement_id=r.requirement_id,
                kind=r.kind.value,
                label=r.label,
                is_required=r.is_required,
                weight=r.weight,
                outcome=r.outcome.value,
                explanation=r.explanation,
                points_earned=r.points_earned,
                points_possible=r.points_possible,
                next_action=r.next_action,
                evidence=[EvidenceRefOut(**vars(e)) for e in r.evidence],
            )
            for r in m.requirements
        ],
        next_actions=[NextActionOut(**vars(a)) for a in m.next_actions],
    )


def task_out(t: OnboardingTask, candidate: Candidate, users: UserNames, m: MatchResult | None, as_of: date) -> TaskOut:
    return TaskOut(
        id=t.id,
        title=t.title,
        description=t.description,
        kind=t.kind,
        owner_role=t.owner_role,
        owner=users.brief(t.owner_id),
        status=t.status,
        due_date=t.due_date,
        overdue=bool(t.due_date and t.due_date < as_of and t.status not in ("done", "waived")),
        notes=t.notes,
        completed_by_name=users.name(t.completed_by),
        completed_at=t.completed_at,
        waived_reason=t.waived_reason,
        blockers=task_blockers(candidate, t, m),
        position=t.position,
    )


def note_out(n: CandidateNote, users: UserNames) -> NoteOut:
    return NoteOut(id=n.id, kind=n.kind, decision=n.decision, body=n.body, author_name=users.name(n.author_id), created_at=n.created_at)


def audit_out(e: AuditEvent, names: dict[str, str] | None = None) -> AuditOut:
    return AuditOut(
        id=e.id,
        actor_label=e.actor_label,
        entity_type=e.entity_type,
        entity_id=e.entity_id,
        candidate_id=e.candidate_id,
        candidate_name=(names or {}).get(e.candidate_id or ""),
        action=e.action,
        summary=e.summary,
        reason=e.reason,
        details=e.details or {},
        created_at=e.created_at,
    )


def candidate_list_item(c: Candidate, r: Readiness, as_of: date) -> CandidateListItem:
    exp = r.nearest_expiration
    return CandidateListItem(
        id=c.id,
        full_name=c.full_name,
        headline=c.headline,
        location=c.location,
        status=c.status,
        job=JobBrief(id=c.job.id, title=c.job.title) if c.job else None,
        eligibility=r.match.eligibility.value if r.match else None,
        score=r.match.score if r.match else None,
        credential_statuses=sorted(r.credential_statuses),
        missing_credentials=r.missing_credentials,
        unreviewed_claims=r.unreviewed_claims,
        flagged_claims=r.flagged_claims,
        nearest_expiration=ExpirationOut(date=exp[0], type_code=exp[1], type_label=credential_label(exp[1]), days=(exp[0] - as_of).days) if exp else None,
        next_action=r.next_actions[0].label if r.next_actions else None,
        tasks_total=r.tasks_total,
        tasks_done=r.tasks_done,
        updated_at=c.updated_at,
    )


def _doc_counts(c: Candidate) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for kind, rows in (("experience", c.experiences), ("qualification", c.qualifications), ("skill", c.skills), ("credential", c.credentials)):
        for row in rows:
            if row.document_id:
                d = counts.setdefault(row.document_id, {})
                d[kind] = d.get(kind, 0) + 1
                if row.review_state == ReviewState.UNREVIEWED.value:
                    d["unreviewed"] = d.get("unreviewed", 0) + 1
    return counts


def candidate_detail(db: Session, c: Candidate, r: Readiness, as_of: date) -> CandidateDetail:
    users = UserNames(db, c.organization_id)
    counts = _doc_counts(c)
    notes = sorted(c.notes, key=lambda n: n.created_at, reverse=True)
    return CandidateDetail(
        **candidate_list_item(c, r, as_of).model_dump(),
        email=c.email,
        summary=c.summary,
        summary_source=c.summary_source,
        summary_reviewed=c.summary_reviewed,
        allowed_transitions=allowed_transitions(c),
        experiences=[experience_out(e, users, as_of) for e in sorted(c.experiences, key=lambda e: e.start_date or date.min, reverse=True)],
        qualifications=[qualification_out(q, users) for q in c.qualifications],
        skills=[skill_out(s, users) for s in sorted(c.skills, key=lambda s: s.name.lower())],
        credentials=[credential_out(x, users, r) for x in sorted(c.credentials, key=lambda x: (x.type_code, x.expiration_date or date.max))],
        documents=[document_out(d, users, counts.get(d.id)) for d in sorted(c.documents, key=lambda d: d.created_at, reverse=True)],
        match=match_out(c.job, r.match) if c.job and r.match else None,
        next_actions=[NextActionOut(**vars(a)) for a in r.next_actions],
        tasks=[task_out(t, c, users, r.match, as_of) for t in c.tasks],
        notes=[note_out(n, users) for n in notes],
        clearance_blockers=clearance_blockers(c, r.match) if c.status == "onboarding" else [],
        created_at=c.created_at,
    )


def job_role_out(job: JobRole, candidate_count: int = 0) -> JobRoleOut:
    return JobRoleOut(
        id=job.id,
        title=job.title,
        department=job.department,
        location=job.location,
        description=job.description,
        status=job.status,
        requirements=[RequirementOut.model_validate(r) for r in job.requirements],
        candidate_count=candidate_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )

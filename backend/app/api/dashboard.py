from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func

from app.api.deps import DB
from app.clock import today
from app.config import get_settings
from app.domain import CandidateStatus, CredentialStatus, Eligibility, JobState, credential_label
from app.models import AuditEvent, ProcessingJob
from app.schemas import DashboardAction, DashboardMetrics, DashboardOut, UpcomingExpiration
from app.security import CurrentPrincipal
from app.services.evaluation import load_candidates, readiness
from app.services.serializers import audit_out

router = APIRouter(tags=["dashboard"])

INACTIVE = {CandidateStatus.WITHDRAWN.value, CandidateStatus.NOT_SELECTED.value}
ISSUE_STATUSES = {
    CredentialStatus.MISSING.value,
    CredentialStatus.EXPIRED.value,
    CredentialStatus.REJECTED.value,
    CredentialStatus.UNABLE_TO_DETERMINE.value,
}


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(principal: CurrentPrincipal, db: DB) -> DashboardOut:
    as_of = today()
    soon = get_settings().expiring_soon_days
    candidates = load_candidates(db, principal.org_id)
    active = [c for c in candidates if c.status not in INACTIVE]

    awaiting = issues = ready = 0
    expirations: list[UpcomingExpiration] = []
    actions: list[DashboardAction] = []
    for c in active:
        r = readiness(c, as_of)
        awaiting += r.unreviewed_claims > 0
        issues += bool(r.credential_statuses & ISSUE_STATUSES)
        ready += bool(
            r.match
            and r.match.eligibility == Eligibility.MEETS_ALL_REQUIRED
            and c.status in (CandidateStatus.NEW.value, CandidateStatus.SCREENING.value, CandidateStatus.INTERVIEW.value, CandidateStatus.OFFER.value)
        )
        creds = {cred.id: cred for cred in c.credentials}
        for a in r.best_by_type.values():  # one row per credential type: its best record
            cred = creds[a.credential_id]
            if not cred.expiration_date or a.status == CredentialStatus.REJECTED:
                continue
            days = (cred.expiration_date - as_of).days
            if -30 <= days <= soon:
                expirations.append(
                    UpcomingExpiration(
                        candidate_id=c.id,
                        candidate_name=c.full_name,
                        credential_id=cred.id,
                        type_code=cred.type_code,
                        type_label=credential_label(cred.type_code),
                        expiration_date=cred.expiration_date,
                        days_until_expiry=days,
                        status=a.status.value,
                    )
                )
        if r.next_actions:
            top = r.next_actions[0]
            actions.append(DashboardAction(candidate_id=c.id, candidate_name=c.full_name, label=top.label, priority=top.priority))

    job_rows = db.query(ProcessingJob.status, func.count()).filter(ProcessingJob.organization_id == principal.org_id).group_by(ProcessingJob.status).all()
    job_counts = {status: n for status, n in job_rows}
    names = {c.id: c.full_name for c in candidates}
    events = db.query(AuditEvent).filter(AuditEvent.organization_id == principal.org_id).order_by(AuditEvent.created_at.desc()).limit(12).all()
    status_counts = {s.value: 0 for s in CandidateStatus}
    for c in candidates:
        status_counts[c.status] += 1

    return DashboardOut(
        as_of=as_of,
        metrics=DashboardMetrics(
            total_candidates=len(candidates),
            active_candidates=len(active),
            awaiting_review=awaiting,
            credential_issues=issues,
            ready_for_next_step=ready,
            in_onboarding=status_counts[CandidateStatus.ONBOARDING.value],
            cleared=status_counts[CandidateStatus.CLEARED.value],
            failed_jobs=job_counts.get(JobState.FAILED.value, 0),
            queued_jobs=job_counts.get(JobState.PENDING.value, 0) + job_counts.get(JobState.PROCESSING.value, 0),
        ),
        pipeline=[{"status": k, "count": v} for k, v in status_counts.items()],
        upcoming_expirations=sorted(expirations, key=lambda e: e.days_until_expiry)[:15],
        next_actions=sorted(actions, key=lambda a: a.priority)[:10],
        recent_activity=[audit_out(e, names) for e in events],
    )

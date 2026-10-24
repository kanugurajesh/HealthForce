from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.api.deps import DB, owned
from app.clock import today
from app.domain import (
    CandidateStatus,
    RequirementKind,
    credential_label,
    qualification_label,
    skill_label,
)
from app.models import Candidate, JobRequirement, JobRole
from app.rules.matching import ELIGIBILITY_RANK
from app.schemas import CandidateBrief, JobMatchesOut, JobMatchRow, JobRoleIn, JobRoleOut, RequirementIn
from app.security import CurrentPrincipal, Perm, Principal, require
from app.services import audit
from app.services.evaluation import load_candidates, match
from app.services.serializers import job_role_out, match_out

router = APIRouter(prefix="/job-roles", tags=["job roles"])


def default_label(r: RequirementIn) -> str:
    if r.label:
        return r.label
    if r.kind == RequirementKind.CREDENTIAL:
        base = " or ".join(credential_label(c) for c in r.codes)
        return base + (f" (valid ≥ {r.min_valid_days} days)" if r.min_valid_days else "")
    if r.kind == RequirementKind.QUALIFICATION:
        return " or ".join(qualification_label(c) for c in r.codes)
    if r.kind == RequirementKind.SKILL:
        return " or ".join(skill_label(c) for c in r.codes)
    setting = "" if not r.setting or r.setting == "any" else f" {r.setting.replace('_', ' ')}"
    return f"{r.min_years:g}+ years{setting} experience"


def _apply(job: JobRole, body: JobRoleIn) -> None:
    job.title, job.department, job.location = body.title, body.department, body.location
    job.description, job.status = body.description, body.status.value
    job.requirements.clear()
    for i, r in enumerate(body.requirements):
        job.requirements.append(
            JobRequirement(
                kind=r.kind.value,
                codes=r.codes,
                label=default_label(r),
                is_required=r.is_required,
                weight=r.weight,
                min_years=r.min_years,
                setting=r.setting,
                min_valid_days=r.min_valid_days,
                position=i,
            )
        )


def _counts(db: DB, org_id: str) -> dict[str, int]:
    rows = db.query(Candidate.job_id, func.count()).filter(Candidate.organization_id == org_id).group_by(Candidate.job_id).all()
    return {job_id: n for job_id, n in rows if job_id}


@router.get("", response_model=list[JobRoleOut])
def list_jobs(principal: CurrentPrincipal, db: DB) -> list[JobRoleOut]:
    jobs = (
        db.query(JobRole)
        .options(selectinload(JobRole.requirements))
        .filter(JobRole.organization_id == principal.org_id)
        .order_by(JobRole.status, JobRole.title)
        .all()
    )
    counts = _counts(db, principal.org_id)
    return [job_role_out(j, counts.get(j.id, 0)) for j in jobs]


@router.post("", response_model=JobRoleOut, status_code=201)
def create_job(body: JobRoleIn, db: DB, principal: Principal = require(Perm.MANAGE_JOBS)) -> JobRoleOut:
    job = JobRole(organization_id=principal.org_id)
    _apply(job, body)
    db.add(job)
    db.flush()
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="job_role",
        entity_id=job.id,
        action="job_role.created",
        summary=f"Created job role '{job.title}' with {len(job.requirements)} requirement(s)",
    )
    db.commit()
    return job_role_out(job)


@router.get("/{job_id}", response_model=JobRoleOut)
def get_job(job_id: str, principal: CurrentPrincipal, db: DB) -> JobRoleOut:
    job = owned(db, JobRole, job_id, principal.org_id, "Job role")
    return job_role_out(job, _counts(db, principal.org_id).get(job.id, 0))


@router.put("/{job_id}", response_model=JobRoleOut)
def update_job(job_id: str, body: JobRoleIn, db: DB, principal: Principal = require(Perm.MANAGE_JOBS)) -> JobRoleOut:
    job = owned(db, JobRole, job_id, principal.org_id, "Job role")
    before = [r.label for r in job.requirements]
    _apply(job, body)
    db.flush()
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="job_role",
        entity_id=job.id,
        action="job_role.updated",
        summary=f"Updated job role '{job.title}'",
        details={"requirements_before": before, "requirements_after": [r.label for r in job.requirements]},
    )
    db.commit()
    return job_role_out(job, _counts(db, principal.org_id).get(job.id, 0))


@router.get("/{job_id}/matches", response_model=JobMatchesOut)
def job_matches(job_id: str, principal: CurrentPrincipal, db: DB, scope: str = Query(default="all", pattern="^(all|assigned)$")) -> JobMatchesOut:
    """Rank candidates against a role: eligibility tier first, then transparent score."""
    job = owned(db, JobRole, job_id, principal.org_id, "Job role", options=(selectinload(JobRole.requirements),))
    as_of = today()
    rows: list[JobMatchRow] = []
    for c in load_candidates(db, principal.org_id):
        if c.status in (CandidateStatus.WITHDRAWN.value, CandidateStatus.NOT_SELECTED.value):
            continue
        if scope == "assigned" and c.job_id != job.id:
            continue
        m = match(c, job, as_of)
        rows.append(
            JobMatchRow(
                candidate=CandidateBrief(id=c.id, full_name=c.full_name, status=c.status, headline=c.headline, assigned_to_this_job=c.job_id == job.id),
                match=match_out(job, m),
            )
        )
    rows.sort(key=lambda r: (ELIGIBILITY_RANK[r.match.eligibility], -r.match.score, r.candidate.full_name))  # type: ignore[index]
    return JobMatchesOut(job=job_role_out(job, _counts(db, principal.org_id).get(job.id, 0)), results=rows)

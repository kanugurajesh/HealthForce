"""Candidate pipeline transitions and onboarding checklist logic."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import today
from app.db import utcnow
from app.domain import CandidateStatus, Eligibility, RequirementKind, RequirementOutcome, Role, TaskKind, TaskStatus
from app.errors import AppError, conflict, forbidden
from app.models import Candidate, OnboardingTask, OnboardingTemplateTask
from app.rules.matching import MatchResult
from app.security import Perm, Principal
from app.services import audit
from app.services.evaluation import match

S = CandidateStatus
TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]] = {
    S.NEW: {S.SCREENING, S.WITHDRAWN, S.NOT_SELECTED},
    S.SCREENING: {S.INTERVIEW, S.WITHDRAWN, S.NOT_SELECTED},
    S.INTERVIEW: {S.OFFER, S.SCREENING, S.WITHDRAWN, S.NOT_SELECTED},
    S.OFFER: {S.ONBOARDING, S.WITHDRAWN, S.NOT_SELECTED},
    S.ONBOARDING: {S.CLEARED, S.WITHDRAWN},
    S.CLEARED: {S.ONBOARDING},  # e.g. a credential lapsed before start date
    S.WITHDRAWN: {S.SCREENING},
    S.NOT_SELECTED: {S.SCREENING},
}
FORWARD = {S.INTERVIEW, S.OFFER, S.ONBOARDING}
NEEDS_REASON = {S.WITHDRAWN, S.NOT_SELECTED}


def allowed_transitions(candidate: Candidate) -> list[str]:
    return sorted(s.value for s in TRANSITIONS[CandidateStatus(candidate.status)])


def change_status(db: Session, principal: Principal, candidate: Candidate, target: CandidateStatus, reason: str | None) -> None:
    current = CandidateStatus(candidate.status)
    reason = (reason or "").strip() or None
    if target not in TRANSITIONS[current]:
        raise conflict(f"Cannot move a candidate from '{current.value}' to '{target.value}'.", {"allowed": allowed_transitions(candidate)})
    if (target in NEEDS_REASON or current in (S.WITHDRAWN, S.NOT_SELECTED, S.CLEARED)) and not reason:
        raise AppError(422, "reason_required", "A reason is required for this status change.")

    result = match(candidate, candidate.job, today()) if candidate.job else None
    if target in (S.OFFER, S.ONBOARDING, S.CLEARED) and candidate.job is None:
        raise conflict("Assign a job role before moving the candidate to this stage.")
    override = False
    if target in FORWARD and result and result.eligibility == Eligibility.REQUIREMENT_NOT_MET:
        # Decision support, not auto-rejection: a person may proceed, but must say why.
        if not reason:
            raise AppError(
                422,
                "override_reason_required",
                "This candidate has an unmet required requirement. Provide a reason to proceed anyway.",
                {"eligibility": result.eligibility_explanation},
            )
        override = True
    if target == S.CLEARED:
        blockers = clearance_blockers(candidate, result)
        if blockers:
            raise conflict("The candidate cannot be cleared to start yet.", {"blockers": blockers})

    candidate.status = target.value
    created = ensure_onboarding_tasks(db, candidate) if target == S.ONBOARDING else 0
    audit.record(
        db,
        org_id=candidate.organization_id,
        actor=principal,
        entity_type="candidate",
        entity_id=candidate.id,
        candidate_id=candidate.id,
        action="candidate.status_changed",
        summary=f"Moved {candidate.full_name} from {current.value} to {target.value}" + (" (override of unmet requirement)" if override else ""),
        reason=reason,
        details={
            "from": current.value,
            "to": target.value,
            "override": override,
            "tasks_created": created,
            "eligibility": result.eligibility.value if result else None,
        },
    )


def clearance_blockers(candidate: Candidate, result: MatchResult | None) -> list[str]:
    blockers = []
    if result is None:
        blockers.append("No job role assigned.")
    elif result.eligibility != Eligibility.MEETS_ALL_REQUIRED:
        blockers.append(result.eligibility_explanation)
    open_tasks = [t.title for t in candidate.tasks if t.status not in (TaskStatus.DONE.value, TaskStatus.WAIVED.value)]
    if not candidate.tasks:
        blockers.append("The onboarding checklist has not been started.")
    if open_tasks:
        blockers.append("Open onboarding tasks: " + ", ".join(open_tasks) + ".")
    return blockers


# --------------------------------------------------------------------------- onboarding


def ensure_onboarding_tasks(db: Session, candidate: Candidate) -> int:
    """Instantiate the org's active template for the candidate. Idempotent (unique per template task)."""
    existing = {t.template_task_id for t in candidate.tasks}
    templates = db.scalars(
        select(OnboardingTemplateTask)
        .where(OnboardingTemplateTask.organization_id == candidate.organization_id, OnboardingTemplateTask.is_active.is_(True))
        .order_by(OnboardingTemplateTask.position)
    ).all()
    created = 0
    for t in templates:
        if t.id in existing:
            continue
        candidate.tasks.append(
            OnboardingTask(
                organization_id=candidate.organization_id,
                template_task_id=t.id,
                title=t.title,
                description=t.description,
                kind=t.kind,
                owner_role=t.owner_role,
                due_date=today() + timedelta(days=t.due_offset_days),
                position=t.position,
            )
        )
        created += 1
    db.flush()
    return created


def task_blockers(candidate: Candidate, task: OnboardingTask, result: MatchResult | None) -> list[str]:
    """Derived (never stored) reasons a task cannot be completed yet."""
    if task.status in (TaskStatus.DONE.value, TaskStatus.WAIVED.value):
        return []
    blockers: list[str] = []
    kind = TaskKind(task.kind)
    if kind in (TaskKind.CREDENTIAL_CHECK, TaskKind.FINAL_REVIEW):
        if result is None:
            blockers.append("Assign a job role so credential requirements can be evaluated.")
        else:
            for r in result.requirements:
                if r.is_required and r.kind == RequirementKind.CREDENTIAL and r.outcome != RequirementOutcome.MET:
                    blockers.append(f"{r.label}: {r.outcome.value.replace('_', ' ')} — {r.explanation}")
    if kind == TaskKind.FINAL_REVIEW:
        others = [t.title for t in candidate.tasks if t.id != task.id and t.status not in (TaskStatus.DONE.value, TaskStatus.WAIVED.value)]
        if others:
            blockers.append("Complete or waive the other tasks first: " + ", ".join(others) + ".")
        if result and result.eligibility != Eligibility.MEETS_ALL_REQUIRED:
            blockers.append(result.eligibility_explanation)
    return blockers


def update_task(
    db: Session,
    principal: Principal,
    candidate: Candidate,
    task: OnboardingTask,
    *,
    status: TaskStatus | None,
    owner_id: str | None | object,
    due_date: object,
    notes: str | None,
    waived_reason: str | None,
    unset: object,
) -> None:
    changes: dict[str, object] = {}
    if status is not None and status.value != task.status:
        if status in (TaskStatus.DONE, TaskStatus.WAIVED):
            if task.kind == TaskKind.FINAL_REVIEW.value and not principal.can(Perm.FINAL_REVIEW):
                raise forbidden("Only a reviewer or admin can complete the final review.")
            if task.owner_role == Role.REVIEWER.value and principal.role == Role.RECRUITER:
                raise forbidden("This task is owned by the reviewer role.")
        if status == TaskStatus.WAIVED:
            if principal.role not in (Role.ADMIN, Role.REVIEWER) and task.kind != TaskKind.MANUAL.value:
                raise forbidden("Only a reviewer or admin can waive this task.")
            if not (waived_reason or "").strip():
                raise AppError(422, "reason_required", "A reason is required to waive a task.")
            if task.kind == TaskKind.FINAL_REVIEW.value:
                raise conflict("The final review cannot be waived.")
        if status == TaskStatus.DONE:
            result = match(candidate, candidate.job, today()) if candidate.job else None
            blockers = task_blockers(candidate, task, result)
            if blockers:
                raise conflict("This task is blocked.", {"blockers": blockers})
        changes["status"] = (task.status, status.value)
        task.status = status.value
        if status in (TaskStatus.DONE, TaskStatus.WAIVED):
            task.completed_by, task.completed_at = principal.id, utcnow()
            task.waived_reason = waived_reason.strip() if status == TaskStatus.WAIVED and waived_reason else None
        else:
            task.completed_by = task.completed_at = task.waived_reason = None
    if owner_id is not unset and owner_id != task.owner_id:
        changes["owner_id"] = (task.owner_id, owner_id)
        task.owner_id = owner_id  # type: ignore[assignment]
    if due_date is not unset and due_date != task.due_date:
        changes["due_date"] = (task.due_date, due_date)
        task.due_date = due_date  # type: ignore[assignment]
    if notes is not None and notes != task.notes:
        changes["notes"] = ("…", "updated")
        task.notes = notes
    if not changes:
        return
    audit.record(
        db,
        org_id=candidate.organization_id,
        actor=principal,
        entity_type="onboarding_task",
        entity_id=task.id,
        candidate_id=candidate.id,
        action="task.updated",
        summary=f"Updated onboarding task '{task.title}'" + (f": {changes['status'][0]} → {changes['status'][1]}" if "status" in changes else ""),  # type: ignore[index]
        reason=waived_reason if status == TaskStatus.WAIVED else None,
        details={k: {"from": v[0], "to": v[1]} for k, v in changes.items()},  # type: ignore[index]
    )

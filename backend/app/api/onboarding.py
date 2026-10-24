from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.api.candidates import _detail
from app.api.deps import DB, owned, validate_body
from app.models import Candidate, OnboardingTask, OnboardingTemplateTask, User
from app.schemas import CandidateDetail, TaskPatch, TemplateIn, TemplateTaskOut
from app.security import CurrentPrincipal, Perm, Principal, require
from app.services import audit
from app.services.evaluation import CANDIDATE_LOAD
from app.services.workflow import update_task

router = APIRouter(tags=["onboarding"])
_UNSET = object()


@router.get("/onboarding/template", response_model=list[TemplateTaskOut])
def get_template(principal: CurrentPrincipal, db: DB) -> list[TemplateTaskOut]:
    rows = (
        db.query(OnboardingTemplateTask)
        .filter(OnboardingTemplateTask.organization_id == principal.org_id, OnboardingTemplateTask.is_active.is_(True))
        .order_by(OnboardingTemplateTask.position)
        .all()
    )
    return [TemplateTaskOut.model_validate(r) for r in rows]


@router.put("/onboarding/template", response_model=list[TemplateTaskOut])
def put_template(body: TemplateIn, db: DB, principal: Principal = require(Perm.MANAGE_SETTINGS)) -> list[TemplateTaskOut]:
    """Replace the active checklist. Removed tasks are deactivated (not deleted) so existing
    candidate checklists and their history stay intact; changes apply to new onboardings."""
    existing = {t.id: t for t in db.query(OnboardingTemplateTask).filter(OnboardingTemplateTask.organization_id == principal.org_id).all()}
    keep: set[str] = set()
    for i, item in enumerate(body.tasks):
        row = existing.get(item.id) if item.id else None
        if row is None:
            row = OnboardingTemplateTask(organization_id=principal.org_id)
            db.add(row)
        row.title, row.description, row.kind = item.title, item.description, item.kind.value
        row.owner_role, row.due_offset_days, row.position, row.is_active = item.owner_role.value, item.due_offset_days, i, True
        db.flush()
        keep.add(row.id)
    for row in existing.values():
        if row.id not in keep:
            row.is_active = False
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal,
        entity_type="onboarding_template",
        entity_id=principal.org_id,
        action="onboarding_template.updated",
        summary=f"Updated the onboarding checklist template ({len(body.tasks)} tasks)",
        details={"tasks": [t.title for t in body.tasks]},
    )
    db.commit()
    return get_template(principal, db)


@router.patch("/tasks/{task_id}", response_model=CandidateDetail)
def patch_task(task_id: str, db: DB, payload: dict[str, Any] = Body(...), principal: Principal = require(Perm.MANAGE_ONBOARDING)) -> CandidateDetail:
    patch = validate_body(TaskPatch, payload)
    task = owned(db, OnboardingTask, task_id, principal.org_id, "Task")
    candidate = owned(db, Candidate, task.candidate_id, principal.org_id, "Candidate", options=CANDIDATE_LOAD)
    fields = patch.model_fields_set
    owner_id: Any = _UNSET
    if "owner_id" in fields:
        owner_id = patch.owner_id
        if owner_id is not None:
            owned(db, User, owner_id, principal.org_id, "User")
    update_task(
        db,
        principal,
        candidate,
        next(t for t in candidate.tasks if t.id == task.id),
        status=patch.status,
        owner_id=owner_id,
        due_date=patch.due_date if "due_date" in fields else _UNSET,
        notes=patch.notes,
        waived_reason=patch.waived_reason,
        unset=_UNSET,
    )
    db.commit()
    return _detail(db, principal, candidate.id)

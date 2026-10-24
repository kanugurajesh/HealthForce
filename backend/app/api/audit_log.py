from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import DB
from app.models import AuditEvent, Candidate
from app.schemas import AuditOut
from app.security import CurrentPrincipal
from app.services.serializers import audit_out

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditOut])
def list_audit(
    principal: CurrentPrincipal,
    db: DB,
    entity_type: str | None = Query(default=None, max_length=40),
    action: str | None = Query(default=None, max_length=60),
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditOut]:
    q = db.query(AuditEvent).filter(AuditEvent.organization_id == principal.org_id)
    if entity_type:
        q = q.filter(AuditEvent.entity_type == entity_type)
    if action:
        q = q.filter(AuditEvent.action.like(f"{action}%"))
    if entity_id:
        q = q.filter(AuditEvent.entity_id == entity_id)
    events = q.order_by(AuditEvent.created_at.desc()).limit(limit).all()
    rows = db.query(Candidate.id, Candidate.full_name).filter(Candidate.organization_id == principal.org_id).all()
    names = {cid: name for cid, name in rows}
    return [audit_out(e, names) for e in events]

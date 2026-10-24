from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.security import Principal

SYSTEM_ACTOR = "System (document processor)"


def record(
    db: Session,
    *,
    org_id: str,
    actor: Principal | None,
    entity_type: str,
    entity_id: str,
    action: str,
    summary: str,
    candidate_id: str | None = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction (committed with the change it describes)."""
    event = AuditEvent(
        organization_id=org_id,
        actor_id=actor.id if actor else None,
        actor_label=actor.label if actor else SYSTEM_ACTOR,
        entity_type=entity_type,
        entity_id=entity_id,
        candidate_id=candidate_id,
        action=action,
        summary=summary[:500],
        reason=reason,
        details=_jsonable(details or {}),
    )
    db.add(event)
    return event


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

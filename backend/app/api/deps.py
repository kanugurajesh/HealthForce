from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError, not_found

DB = Annotated[Session, Depends(get_db)]


def owned[T](db: Session, model: type[T], obj_id: str, org_id: str, what: str, *, options: tuple[Any, ...] = ()) -> T:
    """Fetch a tenant-owned row or 404. Cross-organization ids are indistinguishable from missing ones."""
    q = db.query(model).filter(model.id == obj_id, model.organization_id == org_id)  # type: ignore[attr-defined]
    if options:
        q = q.options(*options)
    row = q.one_or_none()
    if row is None:
        raise not_found(what)
    return row


def validate_body[M: BaseModel](model: type[M], data: Any) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        raise AppError(422, "validation_error", "Some fields are invalid.", details) from exc

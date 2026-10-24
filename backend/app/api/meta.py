from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import DB
from app.clock import today
from app.config import get_settings
from app.domain import (
    CREDENTIAL_CATALOG,
    EXPERIENCE_REQUIREMENT_SETTINGS,
    QUALIFICATION_CATALOG,
    SKILL_CATALOG,
    CandidateStatus,
    ExperienceSetting,
)
from app.models import User
from app.security import CurrentPrincipal
from app.services.workflow import TRANSITIONS

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta")
def meta(principal: CurrentPrincipal, db: DB) -> dict[str, Any]:
    s = get_settings()
    users = db.query(User).filter(User.organization_id == principal.org_id, User.is_active.is_(True)).order_by(User.full_name).all()
    return {
        "as_of": today().isoformat(),
        "extraction_provider": {
            "name": s.extraction_provider,
            "is_mock": s.extraction_provider == "mock",
            # True when AI extraction is selected but no key is configured: uploads will fail until fixed.
            "misconfigured": s.extraction_provider == "groq" and s.groq_api_key is None,
            "label": "Mock extractor (deterministic heuristics, not AI)" if s.extraction_provider == "mock" else f"Groq · {s.groq_model}",
        },
        "verification_mode": s.verification_mode,
        "expiring_soon_days": s.expiring_soon_days,
        "max_upload_mb": s.max_upload_bytes // (1024 * 1024),
        "credential_types": [
            {"code": e.code, "label": e.label, "expires": e.expires, "verification_source": e.verification_source} for e in CREDENTIAL_CATALOG.values()
        ],
        "qualifications": [{"code": e.code, "label": e.label} for e in QUALIFICATION_CATALOG.values()],
        "skills": [{"code": e.code, "label": e.label} for e in SKILL_CATALOG.values()],
        "experience_settings": [s.value for s in ExperienceSetting],
        "experience_requirement_settings": EXPERIENCE_REQUIREMENT_SETTINGS,
        "candidate_statuses": [s.value for s in CandidateStatus],
        "transitions": {k.value: sorted(v.value for v in vs) for k, vs in TRANSITIONS.items()},
        "users": [{"id": u.id, "full_name": u.full_name, "role": u.role} for u in users],
    }

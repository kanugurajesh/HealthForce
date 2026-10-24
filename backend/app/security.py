"""Authentication (password hashing, JWT sessions) and role-based authorization."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.domain import Role
from app.errors import AppError, forbidden
from app.models import User

COOKIE_NAME = "hf_session"
_PBKDF2_ITERATIONS = 240_000


class Perm(StrEnum):
    VIEW = "view"
    MANAGE_CANDIDATES = "manage_candidates"  # create/edit candidates, move through pipeline, notes
    UPLOAD_DOCUMENTS = "upload_documents"
    MANAGE_JOBS = "manage_jobs"
    REVIEW_CLAIMS = "review_claims"  # accept / correct / reject extracted data
    VERIFY_CREDENTIALS = "verify_credentials"
    MANAGE_ONBOARDING = "manage_onboarding"
    FINAL_REVIEW = "final_review"
    MANAGE_SETTINGS = "manage_settings"
    ADD_NOTES = "add_notes"


# Separation of duties: recruiters move candidates forward; reviewers confirm evidence and
# credentials. Only a reviewer (or admin) can complete the final review.
ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.VIEWER: frozenset({Perm.VIEW}),
    Role.RECRUITER: frozenset({Perm.VIEW, Perm.MANAGE_CANDIDATES, Perm.UPLOAD_DOCUMENTS, Perm.MANAGE_JOBS, Perm.MANAGE_ONBOARDING, Perm.ADD_NOTES}),
    Role.REVIEWER: frozenset(
        {Perm.VIEW, Perm.UPLOAD_DOCUMENTS, Perm.REVIEW_CLAIMS, Perm.VERIFY_CREDENTIALS, Perm.MANAGE_ONBOARDING, Perm.FINAL_REVIEW, Perm.ADD_NOTES}
    ),
    Role.ADMIN: frozenset(Perm),
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


# A real hash used to equalize timing when the email does not exist.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email.strip().lower()).one_or_none()
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def create_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "org": user.organization_id,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=s.jwt_ttl_minutes),
        "iss": "healthforce",
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


@dataclass(frozen=True)
class Principal:
    user: User
    role: Role
    permissions: frozenset[Perm]

    @property
    def org_id(self) -> str:
        return self.user.organization_id

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def label(self) -> str:
        return f"{self.user.full_name} ({self.role.value})"

    def can(self, perm: Perm) -> bool:
        return perm in self.permissions


def _unauthorized(msg: str = "Authentication required.") -> AppError:
    return AppError(401, "unauthorized", msg)


def get_principal(request: Request, db: Annotated[Session, Depends(get_db)]) -> Principal:
    token = request.cookies.get(COOKIE_NAME)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        raise _unauthorized()
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], issuer="healthforce", options={"require": ["exp", "sub", "org"]})
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Your session has expired. Sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid session.") from exc
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active or user.organization_id != claims["org"]:
        raise _unauthorized("Invalid session.")
    role = Role(user.role)  # role is read from the DB, so demotions take effect immediately
    return Principal(user=user, role=role, permissions=ROLE_PERMISSIONS[role])


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(perm: Perm):  # type: ignore[no-untyped-def]
    def dependency(principal: CurrentPrincipal) -> Principal:
        if not principal.can(perm):
            raise forbidden(f"Your role ({principal.role.value}) cannot perform this action.")
        return principal

    return Depends(dependency)

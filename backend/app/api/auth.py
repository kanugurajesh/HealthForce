from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request, Response

from app.api.deps import DB
from app.config import get_settings
from app.domain import Role
from app.errors import AppError
from app.schemas import LoginIn, OrgOut, UserOut
from app.security import COOKIE_NAME, ROLE_PERMISSIONS, CurrentPrincipal, authenticate, create_token

router = APIRouter(prefix="/auth", tags=["auth"])

_WINDOW_S, _MAX_FAILURES = 300, 5
_failures: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _throttle_key(request: Request, email: str) -> str:
    return f"{request.client.host if request.client else '?'}|{email.lower()}"


def _too_many(key: str) -> bool:
    now = time.monotonic()
    with _lock:
        q = _failures[key]
        while q and now - q[0] > _WINDOW_S:
            q.popleft()
        return len(q) >= _MAX_FAILURES


def _record_failure(key: str) -> None:
    with _lock:
        _failures[key].append(time.monotonic())


def user_out(user) -> UserOut:  # type: ignore[no-untyped-def]
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        organization=OrgOut(id=user.organization.id, name=user.organization.name),
        permissions=sorted(p.value for p in ROLE_PERMISSIONS[Role(user.role)]),
    )


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: DB) -> UserOut:
    key = _throttle_key(request, body.email)
    if _too_many(key):
        raise AppError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again in a few minutes.")
    user = authenticate(db, body.email, body.password)
    if user is None:
        _record_failure(key)
        raise AppError(401, "invalid_credentials", "Incorrect email or password.")
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_token(user),
        max_age=s.jwt_ttl_minutes * 60,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )
    return user_out(user)


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    response.delete_cookie(COOKIE_NAME, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(principal: CurrentPrincipal) -> UserOut:
    return user_out(principal.user)

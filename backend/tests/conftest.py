"""Test harness: an isolated SQLite database built with the real Alembic migrations,
two organizations with every role, and helpers that drive the public HTTP API."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="hf-tests-"))
os.environ.update(
    HF_ENVIRONMENT="test",
    HF_DATABASE_URL=f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    HF_UPLOAD_DIR=str(_TMP / "uploads"),
    HF_RUN_WORKER="false",
    HF_EXTRACTION_PROVIDER="mock",
    HF_VERIFICATION_MODE="simulated",
    HF_JWT_SECRET="test-secret-not-for-production-0123456789",
)

import logging  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import clock  # noqa: E402
from app.api import auth as auth_api  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import OnboardingTemplateTask, Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.seed import TEMPLATE, alembic_config  # noqa: E402
from app.services.processing import run_now  # noqa: E402

logging.disable(logging.CRITICAL)
TODAY = date(2026, 10, 23)
PASSWORD = "test-password"
_HASH = hash_password(PASSWORD)  # hashed once; PBKDF2 is deliberately slow


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    command.upgrade(alembic_config(), "head")
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean(_database: None) -> Iterator[None]:
    clock.set_today(TODAY)
    auth_api._failures.clear()
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {table.name}"))
    shutil.rmtree(_TMP / "uploads", ignore_errors=True)
    clock.set_today(None)


@pytest.fixture(scope="session")
def app() -> Any:
    return create_app(start_worker=False)


class Api:
    """A signed-in API client with assertion-friendly helpers."""

    def __init__(self, app: Any, email: str) -> None:
        self.client = TestClient(app)
        self.email = email
        r = self.client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def ok(self, method: str, path: str, status: int | tuple[int, ...] = (200, 201, 202), **kw: Any) -> Any:
        r = getattr(self.client, method)(path, **kw)
        expected = (status,) if isinstance(status, int) else status
        assert r.status_code in expected, f"{method.upper()} {path} -> {r.status_code}: {r.text}"
        return r.json() if r.content else None

    def upload(self, cid: str, name: str, content: str | bytes, kind: str = "resume", process: bool = True) -> dict[str, Any]:
        data = content.encode() if isinstance(content, str) else content
        r = self.client.post(f"/api/candidates/{cid}/documents", files={"file": (name, data, "text/plain")}, data={"kind": kind})
        assert r.status_code in (200, 201), r.text
        doc = r.json()["document"]
        if process:
            run_now(doc["job"]["id"])
        return doc

    def candidate(self, cid: str) -> dict[str, Any]:
        return self.ok("get", f"/api/candidates/{cid}")


class World:
    def __init__(self, app: Any) -> None:
        with SessionLocal() as db:
            self.org_ids = {}
            for slug, name, roles in (
                ("northwind", "Northwind", ["admin", "recruiter", "reviewer", "viewer"]),
                ("lakeside", "Lakeside", ["recruiter", "reviewer"]),
            ):
                org = Organization(name=name, slug=slug)
                db.add(org)
                db.flush()
                self.org_ids[slug] = org.id
                for role in roles:
                    db.add(User(organization_id=org.id, email=f"{role}@{slug}.test", full_name=f"{role.title()} {name}", role=role, password_hash=_HASH))
                for i, (title, desc, kind, owner, offset) in enumerate(TEMPLATE):
                    db.add(
                        OnboardingTemplateTask(
                            organization_id=org.id, title=title, description=desc, kind=kind, owner_role=owner, due_offset_days=offset, position=i
                        )
                    )
            db.commit()
        self.app = app
        self._clients: dict[str, Api] = {}

    def as_(self, role: str, org: str = "northwind") -> Api:
        key = f"{role}@{org}.test"
        if key not in self._clients:
            self._clients[key] = Api(self.app, key)
        return self._clients[key]

    @property
    def recruiter(self) -> Api:
        return self.as_("recruiter")

    @property
    def reviewer(self) -> Api:
        return self.as_("reviewer")


@pytest.fixture
def world(app: Any) -> World:
    return World(app)

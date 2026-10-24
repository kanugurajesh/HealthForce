from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api import audit_log, auth, candidates, claims, dashboard, documents, job_roles, meta, onboarding
from app.config import get_settings
from app.errors import install_error_handlers
from app.services.processing import Worker

_STD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Structured logs. Callers pass ids/counts via `extra`; document content is never logged."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        payload.update({k: v for k, v in vars(record).items() if k not in _STD_ATTRS})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(*, start_worker: bool | None = None) -> FastAPI:
    settings = get_settings()
    if settings.environment == "production" and settings.jwt_secret.startswith("dev-only"):
        raise RuntimeError("HF_JWT_SECRET must be set to a strong secret in production.")
    run_worker = settings.run_worker if start_worker is None else start_worker

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        worker = Worker(settings.worker_poll_seconds) if run_worker else None
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    app = FastAPI(title="HealthForce Intelligence API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)

    access = logging.getLogger("app.access")

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        access.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    for module in (meta, auth, dashboard, candidates, claims, documents, job_roles, onboarding, audit_log):
        app.include_router(module.router, prefix="/api")
    return app


configure_logging()
app = create_app()

"""Consistent error envelope: {"error": {"code", "message", "details"?, "request_id"}}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str = "Resource") -> AppError:
    # Also used for cross-tenant access, so existence in another organization is not revealed.
    return AppError(404, "not_found", f"{what} not found.")


def conflict(message: str, details: Any = None) -> AppError:
    return AppError(409, "conflict", message, details)


def forbidden(message: str = "You do not have permission to perform this action.") -> AppError:
    return AppError(403, "forbidden", message)


def bad_request(message: str, code: str = "bad_request", details: Any = None) -> AppError:
    return AppError(400, code, message, details)


def _body(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}
    if details is not None:
        err["details"] = details
    return {"error": err}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(_body(request, "validation_error", "Some fields are invalid.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(_body(request, code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(
            _body(request, "internal_error", "An unexpected error occurred. Quote the request id when reporting it."),
            status_code=500,
        )

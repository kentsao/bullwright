"""RFC 7807 problem responses (docs/API.md §1). Every error the API emits
goes through Problem so agents can parse failures uniformly."""

from typing import Any

from bullwright_core.ids import new_id
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

ERROR_BASE = "https://bullwright.dev/errors"


class Problem(Exception):  # noqa: N818 — RFC 7807 term of art
    def __init__(
        self,
        status: int,
        title: str,
        *,
        kind: str = "generic",
        detail: str | None = None,
        errors: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.title = title
        self.kind = kind
        self.detail = detail
        self.errors = errors
        self.headers = headers
        super().__init__(title)


def problem_response(request: Request, p: Problem) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{ERROR_BASE}/{p.kind}",
        "title": p.title,
        "status": p.status,
        "instance": getattr(request.state, "request_id", new_id("req")),
    }
    if p.detail:
        body["detail"] = p.detail
    if p.errors:
        body["errors"] = p.errors
    return JSONResponse(body, status_code=p.status, headers=p.headers)


def not_found(entity: str = "resource") -> Problem:
    # S3: same shape whether the entity is missing or merely not yours.
    return Problem(404, f"{entity} not found", kind="not-found")


def validation_problem(errors: list[dict[str, str]]) -> Problem:
    return Problem(
        422,
        "Request failed validation",
        kind="validation",
        detail=errors[0]["msg"] if errors else None,
        errors=errors,
    )


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "loc": ".".join(str(x) for x in e["loc"] if x != "body") or "body",
                "msg": str(e["msg"]),
            }
            for e in exc.errors()
        ]
        return problem_response(request, validation_problem(errors))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals (S8: probes must not 500 with stack traces —
        # and when something IS a bug, the body stays generic).
        return problem_response(request, Problem(500, "Internal error", kind="internal"))

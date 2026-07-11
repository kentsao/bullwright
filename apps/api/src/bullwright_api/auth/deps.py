"""FastAPI dependencies: DB session, authenticated principal, scope guards."""

from collections.abc import Callable, Iterator
from typing import Annotated

from bullwright_core.ids import new_id
from bullwright_db.models import AuditEvent
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from bullwright_api.auth.keys import Principal, authenticate
from bullwright_api.auth.ratelimit import limiter
from bullwright_api.errors import Problem
from bullwright_api.settings import settings


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_principal(request: Request, session: SessionDep) -> Principal:
    auth = request.headers.get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    principal = (
        authenticate(session, token.strip()) if scheme.lower() == "bearer" and token else None
    )
    if principal is None:
        # S10: failed auth is audited (key prefix only, never the token).
        session.add(
            AuditEvent(
                event_id=new_id("evt"),
                actor_kind="system",
                action="auth.denied",
                payload={"path": request.url.path, "key_prefix": token.strip()[:12]},
            )
        )
        session.commit()
        raise Problem(
            401,
            "Missing or invalid API key",
            kind="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_scope(scope: str, *, write: bool = False) -> Callable[..., Principal]:
    def guard(request: Request, principal: PrincipalDep) -> Principal:
        if not principal.has_scope(scope):
            raise Problem(
                403,
                f"Missing required scope: {scope}",
                kind="forbidden",
                detail=f"this endpoint requires the {scope!r} scope",
            )
        cfg = settings()
        bucket = "write" if write else "read"
        limit = cfg.rate_limit_writes_per_min if write else cfg.rate_limit_reads_per_min
        retry_in = limiter.check(principal.key_id, bucket, limit)
        if retry_in > 0:
            raise Problem(
                429,
                "Rate limit exceeded",
                kind="rate-limited",
                headers={"Retry-After": str(int(retry_in) + 1)},
            )
        return principal

    return guard

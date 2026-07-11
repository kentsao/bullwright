"""Idempotency-Key handling (docs/API.md §1): same key + same body within
24h replays the stored response; same key + different body is a 409."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from bullwright_db.models import IdempotencyKey
from sqlalchemy.orm import Session

from bullwright_api.errors import Problem

WINDOW = timedelta(hours=24)


def body_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def check_replay(
    session: Session, idem_key: str, key_id: str, request_hash: str
) -> dict[str, Any] | None:
    """Return the stored response body if this is a replay, else None."""
    row = session.get(IdempotencyKey, (idem_key, key_id))
    if row is None:
        return None
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
    if created < datetime.now(UTC) - WINDOW:
        session.delete(row)
        return None
    if row.request_hash != request_hash:
        raise Problem(
            409,
            "Idempotency-Key reused with a different request body",
            kind="idempotency-conflict",
        )
    return dict(row.response_body)


def store(
    session: Session,
    idem_key: str,
    key_id: str,
    request_hash: str,
    status: int,
    response_body: dict[str, Any],
) -> None:
    session.add(
        IdempotencyKey(
            idem_key=idem_key,
            key_id=key_id,
            request_hash=request_hash,
            response_status=status,
            response_body=response_body,
        )
    )

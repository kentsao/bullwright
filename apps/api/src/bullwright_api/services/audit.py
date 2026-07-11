"""Append-only audit writes (rule S10). One helper, used everywhere."""

from typing import Any

from bullwright_core.ids import new_id
from bullwright_db.models import AuditEvent
from sqlalchemy.orm import Session

from bullwright_api.auth.keys import Principal


def audit(
    session: Session,
    action: str,
    *,
    principal: Principal | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            event_id=new_id("evt"),
            actor_kind="operator"
            if principal and principal.is_admin
            else ("agent" if principal else "system"),
            actor_id=principal.agent_name if principal else None,
            run_id=run_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
    )

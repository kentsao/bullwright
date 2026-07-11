from datetime import UTC, datetime
from typing import Annotated

from bullwright_core.ids import new_id
from bullwright_db.models import AgentRun
from fastapi import APIRouter, Depends

from bullwright_api.auth.deps import SessionDep, require_scope
from bullwright_api.auth.keys import Principal
from bullwright_api.errors import not_found
from bullwright_api.schemas import RunIn, RunOut, RunPatch
from bullwright_api.services.audit import audit

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])

WriteScope = Annotated[Principal, Depends(require_scope("reports:write", write=True))]


def _out(row: AgentRun) -> RunOut:
    return RunOut(
        run_id=row.run_id,
        agent_id=row.agent_id,
        task=row.task,
        status=row.status,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )


@router.post("", status_code=201, response_model=RunOut)
def start_run(payload: RunIn, session: SessionDep, principal: WriteScope) -> RunOut:
    row = AgentRun(
        run_id=new_id("run"),
        agent_id=principal.agent_id,
        task=payload.task,
        input_digest=payload.input_digest,
    )
    session.add(row)
    session.flush()
    audit(
        session,
        "run.start",
        principal=principal,
        entity_type="agent_run",
        entity_id=row.run_id,
        run_id=row.run_id,
        payload={"task": payload.task},
    )
    return _out(row)


@router.patch("/{run_id}", response_model=RunOut)
def finish_run(
    run_id: str, payload: RunPatch, session: SessionDep, principal: WriteScope
) -> RunOut:
    row = session.get(AgentRun, run_id)
    if row is None or (not principal.is_admin and row.agent_id != principal.agent_id):
        raise not_found("agent run")
    row.status = payload.status
    row.summary = payload.summary
    row.tokens_used = payload.tokens_used
    row.ended_at = datetime.now(UTC)
    audit(
        session,
        "run.finish",
        principal=principal,
        entity_type="agent_run",
        entity_id=row.run_id,
        run_id=row.run_id,
        payload={"status": payload.status},
    )
    return _out(row)

from typing import Annotated, Any

from bullwright_core.envelope import ReportCreate
from bullwright_core.status import ReportAction
from bullwright_db.models import Report, Ticker
from fastapi import APIRouter, Depends, Header, Query, Request, Response

from bullwright_api.auth.deps import SessionDep, require_scope
from bullwright_api.auth.keys import Principal
from bullwright_api.schemas import RejectIn, ReportOut, ReportPage
from bullwright_api.services import idempotency
from bullwright_api.services import reports as svc

router = APIRouter(prefix="/reports", tags=["reports"])

WriteScope = Annotated[Principal, Depends(require_scope("reports:write", write=True))]
ReadScope = Annotated[Principal, Depends(require_scope("reports:read"))]
AdminScope = Annotated[Principal, Depends(require_scope("admin", write=True))]


def _out(session: SessionDep, row: Report) -> ReportOut:
    symbol = None
    if row.ticker_id:
        t = session.get(Ticker, row.ticker_id)
        symbol = t.symbol if t else None
    return ReportOut.from_row(row, ticker_symbol=symbol)


@router.post("", status_code=201, response_model=ReportOut)
def create_report(
    payload: ReportCreate,
    session: SessionDep,
    principal: WriteScope,
    response: Response,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    if idempotency_key:
        req_hash = idempotency.body_hash(payload.model_dump(mode="json"))
        replay = idempotency.check_replay(session, idempotency_key, principal.key_id, req_hash)
        if replay is not None:
            return replay
    row = svc.create_report(session, principal, payload)
    out = _out(session, row)
    if idempotency_key:
        idempotency.store(
            session,
            idempotency_key,
            principal.key_id,
            idempotency.body_hash(payload.model_dump(mode="json")),
            201,
            out.model_dump(mode="json"),
        )
    response.headers["Location"] = f"/v1/reports/{row.report_id}"
    return out


@router.get("", response_model=ReportPage)
def list_reports(
    session: SessionDep,
    principal: ReadScope,
    ticker: str | None = None,
    status: str | None = None,
    report_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> ReportPage:
    rows, next_cursor = svc.list_reports(
        session,
        principal,
        ticker=ticker,
        status=status,
        report_type=report_type,
        limit=limit,
        cursor=cursor,
    )
    return ReportPage(items=[_out(session, r) for r in rows], next_cursor=next_cursor)


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: str, session: SessionDep, principal: ReadScope) -> ReportOut:
    return _out(session, svc.get_report(session, principal, report_id))


@router.patch("/{report_id}", response_model=ReportOut)
def patch_report(
    report_id: str, patch: dict[str, Any], session: SessionDep, principal: WriteScope
) -> ReportOut:
    return _out(session, svc.patch_report(session, principal, report_id, patch))


def _transition_route(action: ReportAction):  # type: ignore[no-untyped-def]
    if action in (ReportAction.SUBMIT, ReportAction.REVISE):

        @router.post(f"/{{report_id}}/{action.value}", response_model=ReportOut)
        def agent_route(report_id: str, session: SessionDep, principal: WriteScope) -> ReportOut:
            return _out(session, svc.transition(session, principal, report_id, action))

        agent_route.__name__ = f"report_{action.value}"
        return

    if action is ReportAction.REJECT:

        @router.post(f"/{{report_id}}/{action.value}", response_model=ReportOut)
        def reject_route(
            report_id: str, payload: RejectIn, session: SessionDep, principal: AdminScope
        ) -> ReportOut:
            return _out(
                session,
                svc.transition(session, principal, report_id, action, reason=payload.reason),
            )

        return

    @router.post(f"/{{report_id}}/{action.value}", response_model=ReportOut)
    def admin_route(report_id: str, session: SessionDep, principal: AdminScope) -> ReportOut:
        return _out(session, svc.transition(session, principal, report_id, action))

    admin_route.__name__ = f"report_{action.value}"


for _action in ReportAction:
    _transition_route(_action)

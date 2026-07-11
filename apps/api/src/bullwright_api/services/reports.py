"""Report lifecycle service. Routes stay thin; the rules live here and in
bullwright_core.status (the state machine is imported, never re-encoded)."""

from datetime import UTC, datetime
from typing import Any

from bullwright_core.envelope import ReportCreate, ReportType
from bullwright_core.ids import new_id
from bullwright_core.report_types import BodyValidationError, validate_body
from bullwright_core.status import (
    ReportAction,
    ReportStatus,
    TransitionError,
    check_transition,
    is_owner_only,
    required_scope,
)
from bullwright_db.models import Agent, Job, Report, Ticker
from sqlalchemy import select
from sqlalchemy.orm import Session

from bullwright_api.auth.keys import Principal
from bullwright_api.errors import Problem, not_found, validation_problem
from bullwright_api.services.audit import audit
from bullwright_api.services.idempotency import body_hash
from bullwright_api.settings import settings

OWNER_ONLY_READ_STATUSES = {ReportStatus.DRAFT.value, ReportStatus.SUBMITTED.value}


def _validate_payload(payload: ReportCreate, session: Session) -> str | None:
    """Cross-field rules → 422 problems. Returns resolved ticker_id."""
    errors: list[dict[str, str]] = []
    if not payload.ticker_or_sector_ok():
        errors.append(
            {"loc": "ticker", "msg": "a ticker is required (or a sector for sector_overview)"}
        )
    try:
        validate_body(payload.report_type.value, payload.body)
    except BodyValidationError as e:
        errors.extend({"loc": loc, "msg": msg} for loc, msg in e.errors)

    import json

    if len(json.dumps(payload.body)) > settings().max_report_body_bytes:
        errors.append({"loc": "body", "msg": "report body exceeds size limit"})

    ticker_id: str | None = None
    if payload.ticker is not None:
        ticker = session.scalars(
            select(Ticker).where(Ticker.symbol == payload.ticker.upper())
        ).first()
        if ticker is None:
            errors.append(
                {"loc": "ticker", "msg": f"unknown ticker {payload.ticker!r}: add it first"}
            )
        else:
            ticker_id = ticker.ticker_id
    if payload.report_type is ReportType.THESIS_UPDATE and payload.supersedes is None:
        errors.append({"loc": "supersedes", "msg": "thesis_update must reference a prior report"})
    if payload.supersedes is not None:
        prior = session.get(Report, payload.supersedes)
        if prior is None:
            errors.append({"loc": "supersedes", "msg": "referenced report does not exist"})
    if errors:
        raise validation_problem(errors)
    return ticker_id


def create_report(session: Session, principal: Principal, payload: ReportCreate) -> Report:
    ticker_id = _validate_payload(payload, session)
    agent = session.get(Agent, principal.agent_id)
    if agent is None:  # unreachable: principal implies a live agent row
        raise Problem(500, "authenticated agent row missing", kind="internal")
    report = Report(
        report_id=new_id("rep"),
        ticker_id=ticker_id,
        sector=payload.sector,
        report_type=payload.report_type.value,
        schema_version=payload.schema_version,
        title=payload.title,
        author_agent_id=principal.agent_id,
        author_model=agent.default_model,
        agent_run_id=payload.agent_run_id,
        verdict=payload.verdict.model_dump(mode="json") if payload.verdict else None,
        body=payload.body,
        provenance=[p.model_dump(mode="json") for p in payload.provenance],
        tags=list(payload.tags),
        supersedes_report_id=payload.supersedes,
        content_hash=body_hash(payload.body),
    )
    session.add(report)
    session.flush()
    audit(
        session,
        "report.create",
        principal=principal,
        entity_type="report",
        entity_id=report.report_id,
        run_id=payload.agent_run_id,
    )
    return report


def get_report(session: Session, principal: Principal, report_id: str) -> Report:
    report = session.get(Report, report_id)
    if report is None or not _can_see(principal, report):
        raise not_found("report")  # S3: 404, not 403 — existence isn't leaked
    return report


def _can_see(principal: Principal, report: Report) -> bool:
    if principal.is_admin:
        return True
    if report.status in OWNER_ONLY_READ_STATUSES:
        return report.author_agent_id == principal.agent_id
    return True


def list_reports(
    session: Session,
    principal: Principal,
    *,
    ticker: str | None = None,
    status: str | None = None,
    report_type: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[Report], str | None]:
    q = select(Report).order_by(Report.report_id.desc()).limit(limit + 1)
    if ticker:
        t = session.scalars(select(Ticker).where(Ticker.symbol == ticker.upper())).first()
        q = q.where(Report.ticker_id == (t.ticker_id if t else "__none__"))
    if status:
        q = q.where(Report.status == status)
    if report_type:
        q = q.where(Report.report_type == report_type)
    if cursor:
        q = q.where(Report.report_id < cursor)
    rows = [r for r in session.scalars(q).all() if _can_see(principal, r)]
    next_cursor = rows[limit - 1].report_id if len(rows) > limit else None
    return rows[:limit], next_cursor


PATCHABLE = {"title", "verdict", "body", "provenance", "tags"}


def patch_report(
    session: Session, principal: Principal, report_id: str, patch: dict[str, Any]
) -> Report:
    report = session.get(Report, report_id)
    if report is None or (not principal.is_admin and report.author_agent_id != principal.agent_id):
        raise not_found("report")
    if report.status not in (ReportStatus.DRAFT.value, ReportStatus.SUBMITTED.value):
        raise Problem(409, f"cannot edit a report in status {report.status!r}", kind="conflict")
    unknown = set(patch) - PATCHABLE
    if unknown:
        raise validation_problem(
            [{"loc": k, "msg": "field is not patchable"} for k in sorted(unknown)]
        )
    # Re-validate the merged envelope with the strict models.
    merged = ReportCreate.model_validate(
        {
            "ticker": None,  # ticker/sector/type are immutable post-create
            "sector": report.sector,
            "report_type": report.report_type,
            "schema_version": report.schema_version,
            "title": patch.get("title", report.title),
            "verdict": patch.get("verdict", report.verdict),
            "body": patch.get("body", report.body),
            "provenance": patch.get("provenance", report.provenance),
            "tags": patch.get("tags", report.tags),
            "supersedes": report.supersedes_report_id,
        }
    )
    try:
        validate_body(report.report_type, merged.body)
    except BodyValidationError as e:
        raise validation_problem([{"loc": loc, "msg": msg} for loc, msg in e.errors]) from e

    report.title = merged.title
    report.verdict = merged.verdict.model_dump(mode="json") if merged.verdict else None
    report.body = merged.body
    report.provenance = [p.model_dump(mode="json") for p in merged.provenance]
    report.tags = list(merged.tags)
    report.content_hash = body_hash(merged.body)
    audit(
        session,
        "report.patch",
        principal=principal,
        entity_type="report",
        entity_id=report.report_id,
        payload={"fields": sorted(set(patch))},
    )
    return report


def transition(
    session: Session,
    principal: Principal,
    report_id: str,
    action: ReportAction,
    *,
    reason: str | None = None,
) -> Report:
    report = session.get(Report, report_id)
    owner_only = is_owner_only(action)
    if report is None or (
        owner_only and not principal.is_admin and report.author_agent_id != principal.agent_id
    ):
        raise not_found("report")
    scope = required_scope(action)
    if not principal.has_scope(scope):
        raise Problem(403, f"Missing required scope: {scope}", kind="forbidden")

    try:
        target = check_transition(action, ReportStatus(report.status))
    except TransitionError as e:
        raise Problem(409, str(e), kind="invalid-transition") from e

    if action is ReportAction.SUBMIT:
        errors = []
        if report.verdict is None:
            errors.append({"loc": "verdict", "msg": "a verdict is required to submit"})
        if not report.provenance:
            errors.append(
                {"loc": "provenance", "msg": "at least one provenance entry is required to submit"}
            )
        if errors:
            raise validation_problem(errors)
    if action is ReportAction.REJECT and not (reason and reason.strip()):
        raise validation_problem([{"loc": "reason", "msg": "a rejection reason is required"}])

    report.status = target.value
    if action in (ReportAction.APPROVE, ReportAction.REJECT):
        report.reviewed_by = principal.agent_name
        report.review_note = reason
    if action is ReportAction.PUBLISH:
        report.published_at = datetime.now(UTC)
        session.add(  # blog rebuild is async (docs/ARCHITECTURE.md §4)
            Job(job_id=new_id("job"), kind="blog_export", payload={"report_id": report.report_id})
        )
    audit(
        session,
        f"report.{action.value}",
        principal=principal,
        entity_type="report",
        entity_id=report.report_id,
        payload={"reason": reason} if reason else {},
    )
    return report

"""News, alerts, and schedules endpoints (ADR-0002)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from bullwright_core.ids import new_id
from bullwright_db.models import Alert, NewsItem, Schedule, Ticker
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from bullwright_api.auth.deps import SessionDep, require_scope
from bullwright_api.auth.keys import Principal
from bullwright_api.errors import Problem, not_found, validation_problem
from bullwright_api.services.audit import audit

router = APIRouter(tags=["signals"])

MarketScope = Annotated[Principal, Depends(require_scope("market:read"))]
ScheduleScope = Annotated[Principal, Depends(require_scope("schedules:write", write=True))]
AdminScope = Annotated[Principal, Depends(require_scope("admin", write=True))]

# Agents may only schedule these (ADR-0002 §5); operators may schedule any
# kind the worker knows. Arbitrary strings are rejected for everyone.
AGENT_SCHEDULABLE = {"news_crawl", "sec_sync", "sentiment_analyze", "alert_scan"}
ALL_KINDS = AGENT_SCHEDULABLE | {
    "price_ingest",
    "index_calc",
    "composite_calc",
    "blog_export",
}


@router.get("/news")
def list_news(
    session: SessionDep,
    principal: MarketScope,
    ticker: str | None = None,
    analyzed: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    q = select(NewsItem).order_by(NewsItem.published_at.desc()).limit(limit)
    if ticker:
        t = session.scalars(select(Ticker).where(Ticker.symbol == ticker.upper())).first()
        q = q.where(NewsItem.ticker_id == (t.ticker_id if t else "__none__"))
    if analyzed is True:
        q = q.where(NewsItem.sentiment.is_not(None))
    elif analyzed is False:
        q = q.where(NewsItem.sentiment.is_(None))
    tickers = {t.ticker_id: t.symbol for t in session.scalars(select(Ticker)).all()}
    return [
        {
            "news_id": row.news_id,
            "ticker": tickers.get(row.ticker_id or ""),
            "published_at": row.published_at.isoformat(),
            "title": row.title,
            "url": row.url,
            "source": row.source,
            "sentiment": row.sentiment,
            "relevance": row.relevance,
            "analyzed_by": row.analyzed_by,
        }
        for row in session.scalars(q).all()
    ]


@router.get("/alerts")
def list_alerts(
    session: SessionDep,
    principal: MarketScope,
    include_acknowledged: bool = False,
    hours: Annotated[int, Query(ge=1, le=720)] = 72,
) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    q = select(Alert).where(Alert.created_at >= since).order_by(Alert.created_at.desc())
    if not include_acknowledged:
        q = q.where(Alert.acknowledged_at.is_(None))
    tickers = {t.ticker_id: t.symbol for t in session.scalars(select(Ticker)).all()}
    return [
        {
            "alert_id": row.alert_id,
            "kind": row.kind,
            "severity": row.severity,
            "ticker": tickers.get(row.ticker_id or ""),
            "message": row.message,
            "created_at": row.created_at.isoformat(),
            "acknowledged": row.acknowledged_at is not None,
        }
        for row in session.scalars(q).all()
    ]


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: str, session: SessionDep, principal: AdminScope) -> dict[str, Any]:
    row = session.get(Alert, alert_id)
    if row is None:
        raise not_found("alert")
    row.acknowledged_at = datetime.now(UTC)
    audit(session, "alert.ack", principal=principal, entity_type="alert", entity_id=alert_id)
    return {"alert_id": alert_id, "acknowledged": True}


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    job_kind: str
    interval_minutes: int = Field(ge=5, le=10080)  # 5 min .. 1 week
    payload: dict[str, Any] = Field(default_factory=dict)


def _schedule_out(row: Schedule) -> dict[str, Any]:
    return {
        "schedule_id": row.schedule_id,
        "name": row.name,
        "job_kind": row.job_kind,
        "interval_minutes": row.interval_minutes,
        "payload": row.payload,
        "enabled": row.enabled,
        "next_run_at": row.next_run_at.isoformat(),
        "last_enqueued_at": row.last_enqueued_at.isoformat() if row.last_enqueued_at else None,
        "created_by": row.created_by,
    }


@router.get("/schedules")
def list_schedules(session: SessionDep, principal: MarketScope) -> list[dict[str, Any]]:
    return [
        _schedule_out(row)
        for row in session.scalars(select(Schedule).order_by(Schedule.name)).all()
    ]


@router.post("/schedules", status_code=201)
def create_schedule(
    payload: ScheduleIn, session: SessionDep, principal: ScheduleScope
) -> dict[str, Any]:
    allowed = ALL_KINDS if principal.is_admin else AGENT_SCHEDULABLE
    if payload.job_kind not in allowed:
        raise validation_problem(
            [
                {
                    "loc": "job_kind",
                    "msg": f"kind {payload.job_kind!r} not schedulable by this key "
                    f"(allowed: {sorted(allowed)})",
                }
            ]
        )
    if session.scalars(select(Schedule).where(Schedule.name == payload.name)).first():
        raise Problem(409, f"schedule {payload.name!r} already exists", kind="conflict")
    row = Schedule(
        schedule_id=new_id("job").replace("job_", "sch_", 1),
        name=payload.name,
        job_kind=payload.job_kind,
        payload=payload.payload,
        interval_minutes=payload.interval_minutes,
        next_run_at=datetime.now(UTC),  # first run as soon as the worker ticks
        created_by=principal.agent_name,
    )
    session.add(row)
    session.flush()
    audit(
        session,
        "schedule.create",
        principal=principal,
        entity_type="schedule",
        entity_id=row.schedule_id,
        payload={"kind": payload.job_kind, "interval": payload.interval_minutes},
    )
    return _schedule_out(row)


class SchedulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


@router.patch("/schedules/{schedule_id}")
def toggle_schedule(
    schedule_id: str, payload: SchedulePatch, session: SessionDep, principal: ScheduleScope
) -> dict[str, Any]:
    row = session.get(Schedule, schedule_id)
    if row is None or (not principal.is_admin and row.created_by != principal.agent_name):
        raise not_found("schedule")
    row.enabled = payload.enabled
    if payload.enabled:
        row.next_run_at = datetime.now(UTC)
    audit(
        session,
        "schedule.toggle",
        principal=principal,
        entity_type="schedule",
        entity_id=schedule_id,
        payload={"enabled": payload.enabled},
    )
    return _schedule_out(row)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, session: SessionDep, principal: AdminScope) -> None:
    row = session.get(Schedule, schedule_id)
    if row is None:
        raise not_found("schedule")
    session.delete(row)
    audit(
        session,
        "schedule.delete",
        principal=principal,
        entity_type="schedule",
        entity_id=schedule_id,
    )

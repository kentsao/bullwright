"""Operator dashboard (docs/ARCHITECTURE.md §5b).

Server-rendered, dev-env only, read-only. This is a troubleshooting
surface: the answer to "what state is the system in" without psql.
Mounted exclusively when BW_ENV=dev — see create_app().
"""

import html
from datetime import UTC, datetime
from typing import Any

from bullwright_db.models import (
    Agent,
    AgentRun,
    Alert,
    AuditEvent,
    Job,
    Report,
    Schedule,
    Ticker,
)
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from bullwright_api.auth.deps import SessionDep

router = APIRouter(prefix="/ops", tags=["ops"], include_in_schema=False)

_CSS = """
:root { --bg:#101216; --fg:#e7e9ee; --muted:#9aa1ad; --card:#191c22;
        --border:#2a2e37; --accent:#f59e0b; --bad:#f87171; --good:#34d399; }
@media (prefers-color-scheme: light) {
  :root { --bg:#fff; --fg:#1a1d23; --muted:#6b7280; --card:#f6f7f9;
          --border:#e5e7eb; --accent:#b45309; --bad:#b91c1c; --good:#047857; } }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--fg);
  font:14px/1.5 ui-sans-serif,system-ui,sans-serif; }
main { max-width:72rem; margin:0 auto; padding:1.5rem; }
h1 { font-size:1.3rem; } h2 { font-size:1.05rem; margin-top:2rem; }
a { color:var(--accent); text-decoration:none; }
table { border-collapse:collapse; width:100%; font-size:0.85rem; }
th,td { text-align:left; padding:0.35rem 0.6rem; border-bottom:1px solid var(--border);
  vertical-align:top; }
th { color:var(--muted); font-weight:600; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(10rem,1fr)); gap:0.7rem; }
.card { background:var(--card); border:1px solid var(--border); border-radius:8px;
  padding:0.7rem 0.9rem; }
.card .n { font-size:1.5rem; font-weight:800; } .card .l { color:var(--muted);
  font-size:0.8rem; }
.bad { color:var(--bad); } .good { color:var(--good); } .muted { color:var(--muted); }
code { font-family:ui-monospace,Menlo,monospace; font-size:0.8rem; }
nav a { margin-right:1rem; }
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='robots' content='noindex'><title>{html.escape(title)} · bw ops</title>"
        f"<style>{_CSS}</style></head><body><main>"
        "<nav><a href='/ops'>overview</a><a href='/ops/queue'>review queue</a>"
        "<a href='/ops/jobs'>jobs</a><a href='/ops/runs'>runs</a>"
        "<a href='/ops/audit'>audit</a>"
        "<a href='/ops/alerts'>alerts</a><a href='/ops/schedules'>schedules</a></nav>"
        f"<h1>{html.escape(title)}</h1>{body}"
        "<p class='muted' style='margin-top:3rem'>bw ops · dev-only surface · "
        "reads the live DB, writes nothing</p></main></body></html>"
    )


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "<p class='muted'>nothing here</p>"
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{cell if isinstance(cell, str) and cell.startswith('<') else _esc(cell)}</td>"
            for cell in row
        )
        + "</tr>"
        for row in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"


def _ago(dt: datetime | None) -> str:
    if dt is None:
        return ""
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    s = int((datetime.now(UTC) - dt).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s // size}{unit} ago"
    return f"{s}s ago"


@router.get("", response_class=HTMLResponse)
def overview(session: SessionDep) -> HTMLResponse:
    def count(q: Any) -> int:
        return session.scalar(q) or 0

    report_counts: dict[str, int] = {
        status: n
        for status, n in session.execute(
            select(Report.status, func.count()).group_by(Report.status)
        )
    }
    job_counts: dict[str, int] = {
        status: n
        for status, n in session.execute(select(Job.status, func.count()).group_by(Job.status))
    }
    cards = ""
    for label, n, cls in [
        ("tickers", count(select(func.count()).select_from(Ticker)), ""),
        ("agents", count(select(func.count()).select_from(Agent)), ""),
        ("drafts", report_counts.get("draft", 0), ""),
        (
            "awaiting review",
            report_counts.get("submitted", 0),
            "bad" if report_counts.get("submitted") else "good",
        ),
        ("published", report_counts.get("published", 0), "good"),
        ("jobs queued", job_counts.get("queued", 0), ""),
        (
            "jobs failed",
            job_counts.get("failed", 0),
            "bad" if job_counts.get("failed") else "good",
        ),
        (
            "runs (24h fails)",
            count(select(func.count()).select_from(AgentRun).where(AgentRun.status == "failed")),
            "",
        ),
    ]:
        cards += (
            f"<div class='card'><div class='n {cls}'>{n}</div>"
            f"<div class='l'>{_esc(label)}</div></div>"
        )

    recent_fail_rows = session.scalars(
        select(Job).where(Job.status == "failed").order_by(Job.created_at.desc()).limit(5)
    ).all()
    fails = _table(
        ["job", "kind", "attempts", "error"],
        [[j.job_id, j.kind, j.attempts, (j.error or "")[:200]] for j in recent_fail_rows],
    )
    return _page("overview", f"<div class='cards'>{cards}</div><h2>recent job failures</h2>{fails}")


@router.get("/queue", response_class=HTMLResponse)
def review_queue(session: SessionDep) -> HTMLResponse:
    rows = session.scalars(
        select(Report).where(Report.status == "submitted").order_by(Report.updated_at)
    ).all()
    table = _table(
        ["report", "type", "title", "author", "verdict", "waiting"],
        [
            [
                r.report_id,
                r.report_type,
                r.title,
                r.author_agent_id,
                (r.verdict or {}).get("rating", ""),
                _ago(r.updated_at),
            ]
            for r in rows
        ],
    )
    hint = (
        "<p class='muted'>approve/reject via API or CLI — this surface is read-only "
        "by design (publishing must stay a deliberate act).</p>"
    )
    return _page("review queue", table + hint)


@router.get("/jobs", response_class=HTMLResponse)
def jobs(session: SessionDep) -> HTMLResponse:
    rows = session.scalars(select(Job).order_by(Job.created_at.desc()).limit(50)).all()
    return _page(
        "jobs (last 50)",
        _table(
            ["job", "kind", "status", "attempts", "created", "error"],
            [
                [
                    j.job_id,
                    j.kind,
                    j.status,
                    f"{j.attempts}/{j.max_attempts}",
                    _ago(j.created_at),
                    (j.error or "")[:160],
                ]
                for j in rows
            ],
        ),
    )


@router.get("/runs", response_class=HTMLResponse)
def runs(session: SessionDep) -> HTMLResponse:
    rows = session.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(50)).all()
    return _page(
        "agent runs (last 50)",
        _table(
            ["run", "agent", "task", "status", "started", "summary"],
            [
                [
                    r.run_id,
                    r.agent_id,
                    r.task,
                    r.status,
                    _ago(r.started_at),
                    (r.summary or "")[:160],
                ]
                for r in rows
            ],
        ),
    )


@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(session: SessionDep) -> HTMLResponse:
    tickers = {t.ticker_id: t.symbol for t in session.scalars(select(Ticker)).all()}
    rows = session.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(100)).all()
    return _page(
        "alerts (last 100)",
        _table(
            ["when", "severity", "kind", "ticker", "message", "ack"],
            [
                [
                    _ago(a.created_at),
                    a.severity,
                    a.kind,
                    tickers.get(a.ticker_id or "", ""),
                    a.message,
                    "yes" if a.acknowledged_at else "",
                ]
                for a in rows
            ],
        ),
    )


@router.get("/schedules", response_class=HTMLResponse)
def schedules_page(session: SessionDep) -> HTMLResponse:
    rows = session.scalars(select(Schedule).order_by(Schedule.name)).all()
    return _page(
        "schedules",
        _table(
            ["name", "kind", "every", "enabled", "next run", "last enqueued", "by"],
            [
                [
                    s.name,
                    s.job_kind,
                    f"{s.interval_minutes}m",
                    "on" if s.enabled else "PAUSED",
                    _ago(s.next_run_at) if s.next_run_at else "",
                    _ago(s.last_enqueued_at),
                    s.created_by,
                ]
                for s in rows
            ],
        )
        + "<p class='muted'>manage via `bw schedules` or POST /v1/schedules</p>",
    )


@router.get("/audit", response_class=HTMLResponse)
def audit_tail(session: SessionDep, action: str | None = None) -> HTMLResponse:
    q = select(AuditEvent).order_by(AuditEvent.at.desc()).limit(100)
    if action:
        q = q.where(AuditEvent.action == action)
    rows = session.scalars(q).all()
    return _page(
        "audit tail (last 100)",
        _table(
            ["at", "actor", "action", "entity", "payload"],
            [
                [
                    _ago(e.at),
                    f"{e.actor_kind}:{e.actor_id or '-'}",
                    e.action,
                    f"{e.entity_type or ''} {e.entity_id or ''}",
                    str(e.payload)[:160],
                ]
                for e in rows
            ],
        ),
    )

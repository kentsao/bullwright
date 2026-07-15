"""Signal pipeline (ADR-0002): crawl -> dedupe -> analyze -> index ->
alerts -> schedules. All offline via fixtures."""

from datetime import UTC, date, datetime, timedelta

import pytest
from bullwright_core.ids import new_id
from bullwright_db import make_session_factory, session_scope
from bullwright_db.models import Alert, NewsItem, Schedule, Ticker
from bullwright_news import FakeSentimentAnalyzer, FilingRecord, FixtureEdgarClient
from bullwright_news.providers import FixtureNewsProvider, NewsRecord
from bullwright_worker.signal_jobs import (
    alert_scan,
    make_sec_sync,
    make_sentiment_analyze,
    news_crawl,
)
from sqlalchemy import select

from tests.integration.api.conftest import auth

pytestmark = pytest.mark.integration


def _records(symbol: str, n: int, tone: str) -> list[NewsRecord]:
    now = datetime.now(UTC)
    return [
        NewsRecord(
            ticker=symbol,
            published_at=now - timedelta(hours=i),
            title=f"{symbol} {tone} headline number {i}",
            summary=None,
            url=f"https://example.com/{symbol}/{tone}/{i}",
            source="fixture",
        )
        for i in range(n)
    ]


@pytest.fixture()
def factory(engine, nvda, monkeypatch):  # type: ignore[no-untyped-def]
    records = _records("NVDA", 4, "beats expectations with record growth")

    import bullwright_worker.signal_jobs as sj

    monkeypatch.setattr(sj, "get_news_provider", lambda name, **kw: FixtureNewsProvider(records))
    return make_session_factory(engine)


def test_crawl_dedupes_on_rerun(factory) -> None:  # type: ignore[no-untyped-def]
    with session_scope(factory) as s:
        first = news_crawl(s, {"provider": "fixture"})
        assert first and "inserted 4" in first
    with session_scope(factory) as s:
        second = news_crawl(s, {"provider": "fixture"})
        assert second and "inserted 0" in second  # idempotent
        assert len(s.scalars(select(NewsItem)).all()) == 4


def test_analyze_then_spike_alert(factory) -> None:  # type: ignore[no-untyped-def]
    with session_scope(factory) as s:
        news_crawl(s, {"provider": "fixture"})
        note = make_sentiment_analyze(FakeSentimentAnalyzer())(s, {"batch": 50})
        assert note and "analyzed 4/4" in note
        items = s.scalars(select(NewsItem)).all()
        assert all(i.sentiment is not None and i.sentiment > 0 for i in items)

        result = alert_scan(s, {})
        assert result and "raised" in result
        alerts = s.scalars(select(Alert).where(Alert.kind == "sentiment_spike")).all()
        assert len(alerts) == 1
        assert "bullish" in alerts[0].message

        # re-scan: dedupe key blocks duplicates
        alert_scan(s, {})
        assert len(s.scalars(select(Alert)).all()) == len(s.scalars(select(Alert).distinct()).all())
        assert len(s.scalars(select(Alert).where(Alert.kind == "sentiment_spike")).all()) == 1


def test_sec_sync_and_filing_alert(engine, factory, nvda) -> None:  # type: ignore[no-untyped-def]
    filings = {
        "NVDA": [
            FilingRecord("0001-26-000042", "NVDA", "8-K", date.today(), "Material event", None),
            FilingRecord("0001-26-000043", "NVDA", "424B2", date.today(), "Prospectus", None),
        ]
    }
    with session_scope(factory) as s:
        note = make_sec_sync(FixtureEdgarClient(filings))(s, {})
        assert note and "inserted 2" in note
        # idempotent
        again = make_sec_sync(FixtureEdgarClient(filings))(s, {})
        assert again and "inserted 0" in again

        alert_scan(s, {})
        filing_alerts = s.scalars(select(Alert).where(Alert.kind == "filing")).all()
        assert len(filing_alerts) == 1  # only the important 8-K
        assert filing_alerts[0].severity == "high"
        assert "8-K" in filing_alerts[0].message


def test_scheduler_tick_enqueues_and_advances(engine, factory) -> None:  # type: ignore[no-untyped-def]
    from bullwright_db.models import Job
    from bullwright_worker.runner import tick_schedules

    past = datetime.now(UTC) - timedelta(minutes=90)
    with session_scope(factory) as s:
        s.add(
            Schedule(
                schedule_id=new_id("job").replace("job_", "sch_", 1),
                name="crawl-hourly",
                job_kind="news_crawl",
                payload={"provider": "fixture"},
                interval_minutes=60,
                next_run_at=past,
                created_by="operator",
            )
        )
    with session_scope(factory) as s:
        assert tick_schedules(s) == 1
    with session_scope(factory) as s:
        jobs = s.scalars(select(Job).where(Job.kind == "news_crawl")).all()
        assert len(jobs) == 1
        sched = s.scalars(select(Schedule)).one()
        assert sched.next_run_at.replace(tzinfo=UTC) > datetime.now(UTC)  # advanced, no backfill
        assert tick_schedules(s) == 0  # not due again


def test_news_sentiment_feeds_composite(engine, factory, nvda) -> None:  # type: ignore[no-untyped-def]
    """The sixth index appears in index_scores once news is analyzed."""
    from bullwright_db.models import IndexScore, PriceBar
    from bullwright_quant import compute_index_scores, sync_index_definitions

    today = date.today()
    with session_scope(factory) as s:
        ticker = s.scalars(select(Ticker).where(Ticker.symbol == "NVDA")).one()
        day = today - timedelta(days=200)
        price = 100.0
        while day <= today:
            if day.weekday() < 5:
                price *= 1.001
                s.add(
                    PriceBar(
                        ticker_id=ticker.ticker_id,
                        bar_date=day,
                        close=price,
                        adj_close=price,
                        volume=1000,
                        snapshot_id="snap_t",
                    )
                )
            day += timedelta(days=1)
        news_crawl(s, {"provider": "fixture"})
        make_sentiment_analyze(FakeSentimentAnalyzer())(s, {"batch": 50})
        sync_index_definitions(s)
        compute_index_scores(s, [today])
    with session_scope(factory) as s:
        row = s.scalars(select(IndexScore).where(IndexScore.index_key == "news_sentiment")).first()
        assert row is not None
        assert row.raw_value is not None and row.raw_value > 0  # bullish fixture tone
        assert 0.0 <= row.score <= 100.0


def test_schedule_api_scope_rules(client, engine) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.api.conftest import _mint

    agent_key = _mint(engine, "sched-agent", "cloud", ["schedules:write", "market:read"])
    admin_key = _mint(engine, "sched-admin", "human", ["admin"])

    ok = {"name": "agent-crawl", "job_kind": "news_crawl", "interval_minutes": 30}
    r = client.post("/v1/schedules", json=ok, headers=auth(agent_key))
    assert r.status_code == 201, r.text
    schedule_id = r.json()["schedule_id"]

    # agents cannot schedule non-whitelisted kinds
    bad = {"name": "agent-ingest", "job_kind": "price_ingest", "interval_minutes": 30}
    assert client.post("/v1/schedules", json=bad, headers=auth(agent_key)).status_code == 422
    # admin can
    bad["name"] = "admin-ingest"
    assert client.post("/v1/schedules", json=bad, headers=auth(admin_key)).status_code == 201
    # nobody schedules arbitrary kinds
    evil = {"name": "evil", "job_kind": "shell_exec", "interval_minutes": 30}
    assert client.post("/v1/schedules", json=evil, headers=auth(admin_key)).status_code == 422
    # interval floor
    fast = {"name": "toofast", "job_kind": "news_crawl", "interval_minutes": 1}
    assert client.post("/v1/schedules", json=fast, headers=auth(agent_key)).status_code == 422

    # pause/resume own schedule
    r = client.patch(
        f"/v1/schedules/{schedule_id}", json={"enabled": False}, headers=auth(agent_key)
    )
    assert r.status_code == 200 and r.json()["enabled"] is False
    # list visible with market:read
    assert any(
        s["schedule_id"] == schedule_id
        for s in client.get("/v1/schedules", headers=auth(agent_key)).json()
    )
    # delete is admin-only
    assert client.delete(f"/v1/schedules/{schedule_id}", headers=auth(agent_key)).status_code == 403
    assert client.delete(f"/v1/schedules/{schedule_id}", headers=auth(admin_key)).status_code == 204


def test_news_and_alerts_endpoints(client, engine, factory) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.api.conftest import _mint

    key = _mint(engine, "sig-reader", "cloud", ["market:read"])
    with session_scope(factory) as s:
        news_crawl(s, {"provider": "fixture"})
        make_sentiment_analyze(FakeSentimentAnalyzer())(s, {"batch": 50})
        alert_scan(s, {})

    news = client.get("/v1/news?ticker=NVDA&analyzed=true", headers=auth(key)).json()
    assert news and all(n["sentiment"] is not None for n in news)
    alerts = client.get("/v1/alerts", headers=auth(key)).json()
    assert alerts and alerts[0]["kind"] in {"sentiment_spike", "filing", "rank_jump"}

"""Scorecard engine + endpoint: direction rules, checkpoints, calibration."""

from datetime import UTC, date, datetime, timedelta

import pytest
from bullwright_core.ids import new_id
from bullwright_db import make_session_factory, session_scope
from bullwright_db.models import Agent, PriceBar, Report, Ticker
from bullwright_quant import compute_scorecard

from tests.integration.api.conftest import auth

pytestmark = pytest.mark.integration

AS_OF = date(2026, 7, 1)


def _seed(engine, moves: list[tuple[str, str, float, float]]) -> None:  # type: ignore[no-untyped-def]
    """moves: (ticker, rating, confidence, return_over_period)."""
    factory = make_session_factory(engine)
    pub = AS_OF - timedelta(days=95)
    with session_scope(factory) as s:
        agent = Agent(agent_id=new_id("agt"), name="graded-agent", kind="cloud")
        s.add(agent)
        s.flush()
        for i, (symbol, rating, confidence, total_move) in enumerate(moves):
            t = Ticker(ticker_id=new_id("tkr"), symbol=symbol, exchange="TEST")
            s.add(t)
            s.flush()
            # simple linear price path over ~100 days, weekdays only
            base = 100.0
            day = pub - timedelta(days=2)
            n_days = 110
            j = 0
            while day <= AS_OF:
                if day.weekday() < 5:
                    price = base * (1.0 + total_move * (j / n_days))
                    s.add(
                        PriceBar(
                            ticker_id=t.ticker_id,
                            bar_date=day,
                            close=price,
                            adj_close=price,
                            volume=1000,
                            snapshot_id="snap_test",
                        )
                    )
                    j += 1
                day += timedelta(days=1)
            s.add(
                Report(
                    report_id=new_id("rep"),
                    ticker_id=t.ticker_id,
                    report_type="news_flash",
                    title=f"Call {i} on {symbol}",
                    author_agent_id=agent.agent_id,
                    status="published",
                    published_at=datetime(pub.year, pub.month, pub.day, tzinfo=UTC),
                    verdict={
                        "rating": rating,
                        "confidence": confidence,
                        "horizon_days": 60,
                        "one_liner": "x",
                    },
                    body={"event": "e", "impact": "i", "urgency": "low"},
                    content_hash="x",
                )
            )


def test_direction_rules_and_checkpoints(engine) -> None:  # type: ignore[no-untyped-def]
    _seed(
        engine,
        [
            ("UPUP", "buy", 0.8, 0.30),  # bullish + rose -> hits
            ("DOWN", "buy", 0.9, -0.25),  # bullish + fell -> misses
            ("SHRT", "sell", 0.7, -0.20),  # bearish + fell -> hits
            ("FLAT", "hold", 0.4, 0.01),  # hold + flat -> hits
        ],
    )
    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        card = compute_scorecard(s, "graded-agent", AS_OF)
    # 3 checkpoints elapsed per report (30, 60=horizon, 90)
    assert len(card.evaluations) == 12
    summary = card.summary()
    per_ticker: dict[str, list[bool]] = {}
    for e in card.evaluations:
        per_ticker.setdefault(e.ticker, []).append(e.hit)
    assert all(per_ticker["UPUP"]) and all(per_ticker["SHRT"])
    assert not any(per_ticker["DOWN"])
    assert all(per_ticker["FLAT"])
    assert summary["hit_rate"] == 0.75
    buckets = {b["bucket"]: b for b in summary["calibration"]}
    assert buckets["high(>0.75)"]["n"] == 6  # UPUP 0.8 + DOWN 0.9, 3 checkpoints each
    assert buckets["high(>0.75)"]["hit_rate"] == 0.5  # overconfident agent exposed


def test_unelapsed_checkpoints_excluded(engine) -> None:  # type: ignore[no-untyped-def]
    _seed(engine, [("NEWW", "buy", 0.6, 0.10)])
    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        # as_of only 35 days after publish: 30d checkpoint only
        card = compute_scorecard(s, "graded-agent", AS_OF - timedelta(days=60))
    assert {e.checkpoint_days for e in card.evaluations} == {30}


def test_scorecard_endpoint(client, engine) -> None:  # type: ignore[no-untyped-def]
    _seed(engine, [("APIX", "buy", 0.8, 0.15)])
    from tests.integration.api.conftest import _mint

    key = _mint(engine, "reader", "cloud", ["market:read"])
    r = client.get("/v1/agents/graded-agent/scorecard", headers=auth(key))
    assert r.status_code == 200
    body = r.json()
    assert body["evaluated"] > 0 and body["hit_rate"] == 1.0
    assert body["evaluations"][0]["ticker"] == "APIX"
    empty = client.get("/v1/agents/nobody/scorecard", headers=auth(key)).json()
    assert empty["evaluated"] == 0 and empty["hit_rate"] is None

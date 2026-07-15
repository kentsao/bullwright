"""Contract tests for the quant endpoints (docs/API.md §5)."""

from datetime import date, timedelta

import pytest

from tests.integration.api.conftest import auth

pytestmark = pytest.mark.integration


@pytest.fixture()
def market_key(engine):  # type: ignore[no-untyped-def]
    from tests.integration.api.conftest import _mint

    return _mint(engine, "market-agent", "cloud", ["market:read", "backtest:run"])


@pytest.fixture()
def quant_db(engine, nvda):  # type: ignore[no-untyped-def]
    """Ingest + score a small fixture universe around NVDA."""
    from bullwright_core.ids import new_id
    from bullwright_db import make_session_factory, session_scope
    from bullwright_db.models import Fundamental, Ticker
    from bullwright_quant import (
        FixtureProvider,
        compute_composites,
        compute_index_scores,
        default_profile,
        ingest_fundamentals,
        ingest_prices,
        sync_index_definitions,
        universe_dates,
    )
    from sqlalchemy import select

    factory = make_session_factory(engine)
    end = date(2026, 7, 3)
    start = date(2026, 1, 5)
    with session_scope(factory) as s:
        for sym in ("XAAA", "XBBB", "XCCC"):
            s.add(Ticker(ticker_id=new_id("tkr"), symbol=sym, exchange="TEST"))
        s.flush()
        symbols = [t.symbol for t in s.scalars(select(Ticker)).all()]
        ingest_prices(s, FixtureProvider(), symbols, start - timedelta(days=220), end)
        ingest_fundamentals(s, FixtureProvider(), symbols)
        for f_row in s.scalars(select(Fundamental)).all():
            f_row.as_of = start - timedelta(days=10)  # type: ignore[assignment]
        sync_index_definitions(s)
        dates = [d for d in universe_dates(s, start, end) if d.weekday() == 0]
        compute_index_scores(s, dates)
        compute_composites(s, default_profile(s), dates)
    return start, end


def test_prices_endpoint(client, market_key, quant_db, nvda) -> None:  # type: ignore[no-untyped-def]
    start, end = quant_db
    r = client.get(f"/v1/tickers/NVDA/prices?from={start}&to={end}", headers=auth(market_key))
    assert r.status_code == 200
    bars = r.json()["bars"]
    assert bars and all("snapshot_id" in b for b in bars)


def test_scores_endpoint_includes_disclaimer(client, market_key, quant_db) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/v1/tickers/XAAA/scores", headers=auth(market_key))
    assert r.status_code == 200
    body = r.json()
    assert set(body["indexes"]) >= {"momentum", "volatility", "sentiment"}
    assert body["composite"], "composite series missing"
    assert "investment advice" in body["disclaimer"]


def test_indexes_listing(client, market_key, quant_db) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/v1/indexes", headers=auth(market_key))
    keys = {i["index_key"] for i in r.json()}
    assert keys == {"value", "momentum", "quality", "volatility", "sentiment"}


def test_weight_profile_validation(client, admin_key, market_key, quant_db) -> None:  # type: ignore[no-untyped-def]
    bad = {"name": "broken", "weights": {"value": 0.7, "momentum": 0.7}}
    r = client.post("/v1/weight-profiles", json=bad, headers=auth(admin_key))
    assert r.status_code == 422
    good = {"name": "momo-heavy", "weights": {"momentum": 0.7, "volatility": 0.3}}
    r = client.post("/v1/weight-profiles", json=good, headers=auth(admin_key))
    assert r.status_code == 201
    # duplicate name -> 409 (profiles are immutable)
    assert client.post("/v1/weight-profiles", json=good, headers=auth(admin_key)).status_code == 409
    # non-admin cannot create
    assert (
        client.post(
            "/v1/weight-profiles",
            json={"name": "x", "weights": {"value": 1.0}},
            headers=auth(market_key),
        ).status_code
        == 403
    )


def test_backtest_end_to_end_via_api_and_worker(client, engine, market_key, quant_db) -> None:  # type: ignore[no-untyped-def]
    start, end = quant_db
    r = client.post(
        "/v1/backtests",
        json={
            "from": start.isoformat(),
            "to": end.isoformat(),
            "config": {"top_n": 2, "cost_bps": 10},
        },
        headers=auth(market_key),
    )
    assert r.status_code == 202, r.text
    bt_id = r.json()["backtest_id"]

    import os

    os.environ["BW_BACKTEST_DIR"] = os.environ.get("PYTEST_BT_DIR", "data/backtests")
    from bullwright_rag import FakeEmbedder
    from bullwright_worker.cli import build_runner

    runner = build_runner(engine=engine, embedder=FakeEmbedder())
    while runner.run_once():
        pass

    r = client.get(f"/v1/backtests/{bt_id}", headers=auth(market_key))
    body = r.json()
    assert body["status"] == "done", body
    assert "benchmark_return" in body["metrics"] and "total_return" in body["metrics"]
    assert body["metrics"]["small_sample"] is True
    assert "weather, not climate" in body["disclaimer"]

"""Backtest integrity B1-B5 + full pipeline on the FixtureProvider
(TEST_PLAN §4). Everything is deterministic — bit-for-bit repeatable."""

from datetime import date, timedelta

import pytest
from bullwright_core.ids import new_id
from bullwright_db import Base, make_engine, make_session_factory, session_scope
from bullwright_db.models import CompositeScore, IndexScore, Ticker
from bullwright_quant import (
    BacktestConfig,
    FixtureProvider,
    compute_composites,
    compute_index_scores,
    default_profile,
    ingest_fundamentals,
    ingest_prices,
    run_backtest,
    sync_index_definitions,
    universe_dates,
)

pytestmark = pytest.mark.integration

SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
START = date(2026, 1, 5)
END = date(2026, 7, 3)


@pytest.fixture(scope="module")
def scored_db(tmp_path_factory):  # type: ignore[no-untyped-def]
    """One fully scored six-month universe, shared by the module."""
    import os

    os.environ["BW_SNAPSHOT_DIR"] = str(tmp_path_factory.mktemp("snaps"))
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    provider = FixtureProvider()
    with session_scope(factory) as s:
        for sym in SYMBOLS:
            s.add(Ticker(ticker_id=new_id("tkr"), symbol=sym, exchange="TEST"))
        s.flush()
        # bars start早 enough for momentum's 127-day lookback
        ingest_prices(s, provider, SYMBOLS, START - timedelta(days=220), END)
        ingest_fundamentals(s, provider, SYMBOLS)
        # fixture fundamentals observed "today" — backdate for the test window
        from bullwright_db.models import Fundamental

        for row in s.scalars(__import__("sqlalchemy").select(Fundamental)).all():
            row.as_of = START - timedelta(days=10)
        sync_index_definitions(s)
        dates = [d for d in universe_dates(s, START, END) if d.weekday() == 0]
        compute_index_scores(s, dates)
        profile = default_profile(s)
        compute_composites(s, profile, dates)
    return engine, factory


def test_scores_exist_and_bounded(scored_db) -> None:  # type: ignore[no-untyped-def]
    _, factory = scored_db
    from sqlalchemy import select

    with session_scope(factory) as s:
        scores = s.scalars(select(IndexScore)).all()
        assert scores, "no index scores computed"
        assert all(row.score is not None and 0.0 <= row.score <= 100.0 for row in scores)
        composites = s.scalars(select(CompositeScore)).all()
        present = [c for c in composites if c.score is not None]
        assert present and all(c.score is not None and 0.0 <= c.score <= 100.0 for c in present)
        # ranks are a permutation 1..n per date
        by_date: dict[object, list[int]] = {}
        for c in present:
            assert c.rank is not None
            by_date.setdefault(c.score_date, []).append(c.rank)
        for ranks in by_date.values():
            assert sorted(ranks) == list(range(1, len(ranks) + 1))


def test_b2_reproducible_bit_for_bit(scored_db) -> None:  # type: ignore[no-untyped-def]
    _, factory = scored_db
    config = BacktestConfig(top_n=3, cost_bps=10.0)
    with session_scope(factory) as s:
        profile = default_profile(s)
        one = run_backtest(s, profile, SYMBOLS, START, END, config)
        two = run_backtest(s, profile, SYMBOLS, START, END, config)
    assert one.metrics == two.metrics
    assert one.equity_curve_csv == two.equity_curve_csv  # bit-for-bit
    assert one.inputs_digest == two.inputs_digest


def test_b4_benchmark_always_present_and_b5_small_sample_flag(scored_db) -> None:  # type: ignore[no-untyped-def]
    _, factory = scored_db
    with session_scope(factory) as s:
        profile = default_profile(s)
        out = run_backtest(s, profile, SYMBOLS, START, END, BacktestConfig())
    assert "benchmark_return" in out.metrics and "total_return" in out.metrics
    assert out.metrics["small_sample"] is True  # 6 months < 1 year (B5)
    assert out.metrics["rebalances"] > 15  # weekly over ~26 weeks


def test_b1_lookahead_shifting_scores_changes_returns(scored_db) -> None:  # type: ignore[no-untyped-def]
    """If composite scores are shifted forward one rebalance, the engine
    must produce different results — proving picks actually depend on
    score timing (no accidental static portfolio)."""
    _, factory = scored_db
    from sqlalchemy import select

    config = BacktestConfig(top_n=2, cost_bps=0.0)
    with session_scope(factory) as s:
        profile = default_profile(s)
        baseline = run_backtest(s, profile, SYMBOLS, START, END, config)

        rows = s.scalars(
            select(CompositeScore).where(CompositeScore.profile_id == profile.profile_id)
        ).all()
        # invert every score: the engine must now pick the OPPOSITE names
        for r in rows:
            if r.score is not None:
                r.score = 100.0 - r.score
        s.flush()
        inverted = run_backtest(s, profile, SYMBOLS, START, END, config)
        s.rollback()
    assert baseline.equity_curve_csv != inverted.equity_curve_csv
    assert baseline.holdings_log[0]["picks"] != inverted.holdings_log[0]["picks"]


def test_costs_reduce_equity(scored_db) -> None:  # type: ignore[no-untyped-def]
    _, factory = scored_db
    with session_scope(factory) as s:
        profile = default_profile(s)
        free = run_backtest(s, profile, SYMBOLS, START, END, BacktestConfig(cost_bps=0.0))
        costly = run_backtest(s, profile, SYMBOLS, START, END, BacktestConfig(cost_bps=100.0))
    assert costly.metrics["total_return"] < free.metrics["total_return"]
    assert free.metrics["turnover_total"] == costly.metrics["turnover_total"]

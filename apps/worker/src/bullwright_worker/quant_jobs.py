"""Quant job handlers (docs/ARCHITECTURE.md §4): price_ingest,
index_calc, composite_calc, backtest."""

import os
from datetime import date, timedelta
from typing import Any

from bullwright_db.models import BacktestRun, Ticker, WeightProfile
from bullwright_quant import (
    BacktestConfig,
    compute_composites,
    compute_index_scores,
    default_profile,
    get_provider,
    ingest_fundamentals,
    ingest_prices,
    run_backtest,
    sync_index_definitions,
    universe_dates,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


def _active_symbols(session: Session) -> list[str]:
    return [t.symbol for t in session.scalars(select(Ticker).where(Ticker.is_active)).all()]


def price_ingest(session: Session, payload: dict[str, Any]) -> str:
    provider = get_provider(
        payload.get("provider", os.environ.get("BW_MARKET_PROVIDER", "fixture"))
    )
    symbols = payload.get("symbols") or _active_symbols(session)
    days = int(payload.get("days", 400))
    end = date.today()
    counts = ingest_prices(session, provider, symbols, end - timedelta(days=days), end)
    n_fund = ingest_fundamentals(session, provider, symbols)
    return f"bars: {counts}; fundamentals rows: {n_fund}"


def index_calc(session: Session, payload: dict[str, Any]) -> str:
    sync_index_definitions(session)
    start = date.fromisoformat(payload["from"])
    end = date.fromisoformat(payload["to"])
    cadence = payload.get("cadence", "weekly")
    dates = universe_dates(session, start, end)
    if cadence == "weekly":
        dates = [d for d in dates if d.weekday() == 0]
    n = compute_index_scores(session, dates)
    return f"wrote {n} index scores over {len(dates)} dates"


def composite_calc(session: Session, payload: dict[str, Any]) -> str:
    profile = (
        session.get(WeightProfile, payload["profile_id"])
        if payload.get("profile_id")
        else default_profile(session)
    )
    if profile is None:
        raise RuntimeError("weight profile not found")
    start = date.fromisoformat(payload["from"])
    end = date.fromisoformat(payload["to"])
    dates = universe_dates(session, start, end)
    if payload.get("cadence", "weekly") == "weekly":
        dates = [d for d in dates if d.weekday() == 0]
    n = compute_composites(session, profile, dates)
    return f"wrote {n} composite scores"


def backtest_job(session: Session, payload: dict[str, Any]) -> str:
    run = session.get(BacktestRun, payload["backtest_id"])
    if run is None:
        raise RuntimeError(f"backtest {payload.get('backtest_id')!r} not found")
    profile = session.get(WeightProfile, run.profile_id)
    if profile is None:
        raise RuntimeError("weight profile not found")
    run.status = "running"
    session.flush()
    try:
        cfg = BacktestConfig(
            top_n=int(run.config.get("top_n", 5)),
            cost_bps=float(run.config.get("cost_bps", 10.0)),
        )
        out = run_backtest(
            session,
            profile,
            [str(s) for s in run.universe],
            run.from_date,
            run.to_date,
            cfg,
        )
        artifact_dir = os.environ.get("BW_BACKTEST_DIR", "data/backtests")
        from pathlib import Path

        d = Path(artifact_dir) / run.backtest_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "equity_curve.csv").write_text(out.equity_curve_csv, encoding="utf-8")
        import json

        (d / "holdings.json").write_text(json.dumps(out.holdings_log, indent=1))
        run.metrics = out.metrics
        run.artifact_path = str(d)
        run.snapshot_id = out.inputs_digest
        run.status = "done"
        # backtested profiles become immutable (docs/INDEXES.md §4)
        profile.is_locked = True
        return f"metrics: {out.metrics}"
    except Exception:
        run.status = "failed"
        raise

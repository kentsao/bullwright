"""Backtest engine (docs/INDEXES.md §5). Deliberately simple v1:
weekly Monday rebalance into the top-N by composite score, equal weight,
transaction costs on turnover, benchmark = equal-weight universe.

Integrity rules implemented here and tested in tests/integration/quant:
B1 point-in-time (scores at rebalance t use data <= t — guaranteed by the
scoring layer), B2 reproducible (pure function of DB rows + config),
B3 dated universe, B4 benchmark always in metrics, B5 small-sample flag.
"""

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from bullwright_db.models import CompositeScore, PriceBar, Ticker, WeightProfile
from sqlalchemy import select
from sqlalchemy.orm import Session

TRADING_DAYS = 252.0


@dataclass(frozen=True)
class BacktestConfig:
    top_n: int = 5
    cost_bps: float = 10.0
    rebalance: str = "weekly"  # v1: weekly only


@dataclass
class BacktestOutput:
    metrics: dict[str, Any]
    equity_curve_csv: str
    holdings_log: list[dict[str, Any]]
    inputs_digest: str


def _load_frame(
    session: Session, symbols: list[str], start: date, end: date
) -> tuple[list[date], dict[str, dict[date, float]]]:
    tickers = {
        t.ticker_id: t.symbol
        for t in session.scalars(select(Ticker).where(Ticker.symbol.in_(symbols))).all()
    }
    closes: dict[str, dict[date, float]] = {s: {} for s in symbols}
    dates: set[date] = set()
    for row in session.scalars(
        select(PriceBar).where(
            PriceBar.ticker_id.in_(tickers),
            PriceBar.bar_date >= start,
            PriceBar.bar_date <= end,
        )
    ).all():
        symbol = tickers[row.ticker_id]
        closes[symbol][row.bar_date] = float(row.adj_close)
        dates.add(row.bar_date)
    return sorted(dates), closes


def _scores_on(
    session: Session, profile_id: str, as_of: date, symbols: list[str]
) -> dict[str, float]:
    tickers = {
        t.ticker_id: t.symbol
        for t in session.scalars(select(Ticker).where(Ticker.symbol.in_(symbols))).all()
    }
    out: dict[str, float] = {}
    for row in session.scalars(
        select(CompositeScore).where(
            CompositeScore.profile_id == profile_id,
            CompositeScore.score_date == as_of,
            CompositeScore.score.is_not(None),
        )
    ).all():
        if row.ticker_id in tickers:
            out[tickers[row.ticker_id]] = float(row.score)  # type: ignore[arg-type]
    return out


def run_backtest(
    session: Session,
    profile: WeightProfile,
    symbols: list[str],
    start: date,
    end: date,
    config: BacktestConfig,
) -> BacktestOutput:
    dates, closes = _load_frame(session, symbols, start, end)
    if len(dates) < 10:
        raise ValueError("not enough price history in the window to backtest")

    rebalance_dates = {
        d for i, d in enumerate(dates) if d.weekday() == 0 or i == 0
    }  # Mondays + first day

    holdings: dict[str, float] = {}  # symbol -> weight
    equity = 1.0
    bench_equity = 1.0
    equity_rows: list[tuple[date, float, float]] = []
    holdings_log: list[dict[str, Any]] = []
    total_turnover = 0.0

    for i, day in enumerate(dates):
        # 1) apply daily returns to current holdings (and benchmark)
        if i > 0:
            prev = dates[i - 1]
            port_ret = 0.0
            for symbol, weight in holdings.items():
                p0, p1 = closes[symbol].get(prev), closes[symbol].get(day)
                if p0 and p1 and p0 > 0:
                    port_ret += weight * (p1 / p0 - 1.0)
            equity *= 1.0 + port_ret

            bench_rets = [
                closes[s][day] / closes[s][prev] - 1.0
                for s in symbols
                if closes[s].get(prev) and closes[s].get(day)
            ]
            if bench_rets:
                bench_equity *= 1.0 + sum(bench_rets) / len(bench_rets)

        # 2) rebalance at close using scores computed for this date (<= day data)
        if day in rebalance_dates:
            scores = _scores_on(session, profile.profile_id, day, symbols)
            picks = sorted(scores, key=lambda s: -scores[s])[: config.top_n]
            new_holdings = dict.fromkeys(picks, 1.0 / len(picks)) if picks else {}
            turnover = (
                sum(
                    abs(new_holdings.get(s, 0.0) - holdings.get(s, 0.0))
                    for s in set(new_holdings) | set(holdings)
                )
                / 2.0
            )
            cost = turnover * config.cost_bps / 10_000.0
            equity *= 1.0 - cost
            total_turnover += turnover
            holdings = new_holdings
            holdings_log.append(
                {"date": day.isoformat(), "picks": picks, "turnover": round(turnover, 4)}
            )

        equity_rows.append((day, equity, bench_equity))

    daily = np.array([e for _, e, _ in equity_rows])
    rets = daily[1:] / daily[:-1] - 1.0
    n_days = len(dates)
    total_return = float(daily[-1] / daily[0] - 1.0)
    bench_return = float(equity_rows[-1][2] / equity_rows[0][2] - 1.0)
    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * np.sqrt(TRADING_DAYS))
        if len(rets) > 2 and rets.std(ddof=1) > 0
        else 0.0
    )
    running_max = np.maximum.accumulate(daily)
    max_drawdown = float(((daily - running_max) / running_max).min())

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "equity", "benchmark_equity"])
    for day, e, b in equity_rows:
        writer.writerow([day.isoformat(), f"{e:.8f}", f"{b:.8f}"])
    curve_csv = buf.getvalue()

    digest_src = f"{profile.profile_id}:{sorted(symbols)}:{start}:{end}:{config}"
    metrics: dict[str, Any] = {
        "total_return": round(total_return, 6),
        "benchmark_return": round(bench_return, 6),  # B4: never one without the other
        "excess_return": round(total_return - bench_return, 6),
        "cagr": round(float((daily[-1] / daily[0]) ** (TRADING_DAYS / n_days) - 1.0), 6),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown, 6),
        "turnover_total": round(total_turnover, 4),
        "rebalances": len(holdings_log),
        "trading_days": n_days,
        "small_sample": n_days < TRADING_DAYS,  # B5: "weather, not climate"
    }
    return BacktestOutput(
        metrics=metrics,
        equity_curve_csv=curve_csv,
        holdings_log=holdings_log,
        inputs_digest=hashlib.sha256(digest_src.encode()).hexdigest()[:16],
    )

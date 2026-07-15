"""Price/fundamentals ingestion with content-addressed snapshots: every
bar row records which snapshot it came from, so any downstream number can
name its exact inputs (docs/SPEC.md §8 reproducibility)."""

import csv
import hashlib
import io
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from bullwright_db.models import Fundamental, PriceBar, Ticker
from sqlalchemy import select
from sqlalchemy.orm import Session

from bullwright_quant.providers import Bar, MarketDataProvider

SNAPSHOT_DIR = Path(os.environ.get("BW_SNAPSHOT_DIR", "data/snapshots"))


def _snapshot_bars(symbol: str, bars: list[Bar]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "open", "high", "low", "close", "adj_close", "volume"])
    for b in sorted(bars, key=lambda x: x.bar_date):
        writer.writerow([b.bar_date, b.open, b.high, b.low, b.close, b.adj_close, b.volume])
    content = buf.getvalue()
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    snap_id = f"snap_{symbol.lower()}_{digest}"
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{snap_id}.csv"
    if not path.exists():  # content-addressed: identical data never rewritten
        path.write_text(content, encoding="utf-8")
    return snap_id


def ingest_prices(
    session: Session, provider: MarketDataProvider, symbols: list[str], start: date, end: date
) -> dict[str, int]:
    """Fetch daily bars and upsert. Returns {symbol: bar_count}."""
    tickers = {
        t.symbol: t for t in session.scalars(select(Ticker).where(Ticker.symbol.in_(symbols))).all()
    }
    missing = set(symbols) - set(tickers)
    if missing:
        raise ValueError(f"symbols not on the watchlist: {sorted(missing)} — add them first")

    fetched = provider.fetch_daily(symbols, start, end)
    counts: dict[str, int] = {}
    for symbol, bars in fetched.items():
        ticker = tickers[symbol]
        snap_id = _snapshot_bars(symbol, bars)
        existing = {
            row.bar_date
            for row in session.scalars(
                select(PriceBar).where(PriceBar.ticker_id == ticker.ticker_id)
            ).all()
        }
        n = 0
        for b in bars:
            if b.bar_date in existing:
                continue
            session.add(
                PriceBar(
                    ticker_id=ticker.ticker_id,
                    bar_date=b.bar_date,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    adj_close=b.adj_close,
                    volume=b.volume,
                    snapshot_id=snap_id,
                )
            )
            n += 1
        counts[symbol] = n
    return counts


def ingest_fundamentals(session: Session, provider: MarketDataProvider, symbols: list[str]) -> int:
    """Store today's fundamentals observation per symbol (point-in-time)."""
    tickers = {
        t.symbol: t for t in session.scalars(select(Ticker).where(Ticker.symbol.in_(symbols))).all()
    }
    data = provider.fetch_fundamentals([s for s in symbols if s in tickers])
    today = datetime.now(UTC).date()
    n = 0
    for symbol, metrics in data.items():
        clean: dict[str, Any] = {
            k: (float(v) if isinstance(v, int | float) else None) for k, v in metrics.items()
        }
        digest = hashlib.sha256(repr(sorted(clean.items())).encode()).hexdigest()[:16]
        existing = session.get(Fundamental, (tickers[symbol].ticker_id, today))
        if existing is not None:
            continue
        session.add(
            Fundamental(
                ticker_id=tickers[symbol].ticker_id,
                as_of=today,
                metrics=clean,
                snapshot_id=f"fund_{provider.name}_{digest}",
            )
        )
        n += 1
    return n

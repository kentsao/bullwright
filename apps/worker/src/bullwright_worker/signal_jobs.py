"""Signal jobs (ADR-0002): news_crawl, sec_sync, sentiment_analyze,
alert_scan. Handlers with external clients are factories so tests inject
fixtures and CI stays offline."""

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from bullwright_core.ids import new_id
from bullwright_db.models import Alert, CompositeScore, Filing, NewsItem, Ticker, WeightProfile
from bullwright_news import FilingRecord, SentimentAnalyzer, get_news_provider
from sqlalchemy import func, select
from sqlalchemy.orm import Session

Handler = Callable[[Session, dict[str, Any]], str | None]

SEVERE_FORMS = {"10-K", "10-Q", "8-K"}
SPIKE_THRESHOLD = 0.5
SPIKE_MIN_ITEMS = 3
RANK_JUMP = 3


class EdgarLike(Protocol):
    def recent_filings(self, symbol: str) -> list[FilingRecord]: ...


def _watchlist(session: Session) -> dict[str, Ticker]:
    return {t.symbol: t for t in session.scalars(select(Ticker).where(Ticker.is_active)).all()}


def news_crawl(session: Session, payload: dict[str, Any]) -> str:
    provider = get_news_provider(
        payload.get("provider", os.environ.get("BW_NEWS_PROVIDER", "fixture"))
    )
    tickers = _watchlist(session)
    symbols = payload.get("symbols") or sorted(tickers)
    records = provider.fetch([s for s in symbols if s in tickers])
    existing = {
        h
        for (h,) in session.execute(
            select(NewsItem.content_hash).where(
                NewsItem.content_hash.in_([r.content_hash for r in records])
            )
        )
    }
    inserted = 0
    for record in records:
        if record.content_hash in existing:
            continue
        existing.add(record.content_hash)
        session.add(
            NewsItem(
                news_id=new_id("evt").replace("evt_", "nws_", 1),
                ticker_id=tickers[record.ticker].ticker_id,
                published_at=record.published_at,
                title=record.title,
                summary=record.summary,
                url=record.url,
                source=record.source,
                provider=provider.name,
                content_hash=record.content_hash,
            )
        )
        inserted += 1
    return f"fetched {len(records)}, inserted {inserted} new items"


def make_sec_sync(edgar: EdgarLike) -> Handler:
    def sec_sync(session: Session, payload: dict[str, Any]) -> str:
        tickers = _watchlist(session)
        symbols = payload.get("symbols") or sorted(tickers)
        inserted = 0
        for symbol in symbols:
            if symbol not in tickers:
                continue
            for record in edgar.recent_filings(symbol):
                if session.get(Filing, record.accession_no) is not None:
                    continue
                session.add(
                    Filing(
                        accession_no=record.accession_no,
                        ticker_id=tickers[symbol].ticker_id,
                        form_type=record.form_type,
                        filed_at=record.filed_at,
                        title=record.title,
                        url=record.url,
                        is_important=record.is_important,
                    )
                )
                inserted += 1
        return f"inserted {inserted} new filings"

    return sec_sync


def make_sentiment_analyze(analyzer: SentimentAnalyzer) -> Handler:
    def sentiment_analyze(session: Session, payload: dict[str, Any]) -> str:
        batch = int(payload.get("batch", 20))
        rows = session.scalars(
            select(NewsItem)
            .where(NewsItem.sentiment.is_(None))
            .order_by(NewsItem.published_at.desc())
            .limit(batch)
        ).all()
        done = 0
        errors = 0
        for row in rows:
            ticker = session.get(Ticker, row.ticker_id) if row.ticker_id else None
            symbol = ticker.symbol if ticker else "the market"
            text = row.title + ("\n" + row.summary if row.summary else "")
            try:
                result = analyzer.analyze(symbol, text)
            except Exception:
                errors += 1
                continue
            row.sentiment = result.sentiment
            row.relevance = result.relevance
            row.analyzed_by = analyzer.model
            row.analyzed_at = datetime.now(UTC)
            done += 1
        return f"analyzed {done}/{len(rows)} items ({errors} errors)"

    return sentiment_analyze


def _raise_alert(
    session: Session,
    kind: str,
    severity: str,
    ticker_id: str | None,
    message: str,
    dedupe_key: str,
    payload: dict[str, Any],
) -> bool:
    exists = session.scalars(select(Alert).where(Alert.dedupe_key == dedupe_key)).first()
    if exists:
        return False
    session.add(
        Alert(
            alert_id=new_id("evt").replace("evt_", "alr_", 1),
            kind=kind,
            severity=severity,
            ticker_id=ticker_id,
            message=message,
            dedupe_key=dedupe_key,
            payload=payload,
        )
    )
    return True


def alert_scan(session: Session, payload: dict[str, Any]) -> str:
    now = datetime.now(UTC)
    lookback = now - timedelta(hours=float(payload.get("lookback_hours", 26)))
    raised = 0
    tickers = {t.ticker_id: t.symbol for t in _watchlist(session).values()}

    # Rule 1: new important filings
    for filing in session.scalars(
        select(Filing).where(Filing.is_important, Filing.created_at >= lookback)
    ).all():
        symbol = tickers.get(filing.ticker_id, "?")
        severity = "high" if filing.form_type in SEVERE_FORMS else "warn"
        raised += _raise_alert(
            session,
            "filing",
            severity,
            filing.ticker_id,
            f"{symbol}: new {filing.form_type} filed {filing.filed_at:%Y-%m-%d}"
            + (f" — {filing.title}" if filing.title else ""),
            f"filing:{filing.accession_no}",
            {"accession_no": filing.accession_no, "url": filing.url},
        )

    # Rule 2: 24h news-sentiment spike
    day_ago = now - timedelta(hours=24)
    rows = session.execute(
        select(
            NewsItem.ticker_id,
            func.count(),
            func.avg(NewsItem.sentiment),
        )
        .where(NewsItem.analyzed_at.is_not(None), NewsItem.published_at >= day_ago)
        .group_by(NewsItem.ticker_id)
    ).all()
    for ticker_id, n, mean in rows:
        if ticker_id is None or n < SPIKE_MIN_ITEMS or mean is None:
            continue
        if abs(mean) < SPIKE_THRESHOLD:
            continue
        symbol = tickers.get(ticker_id, "?")
        direction = "bullish" if mean > 0 else "bearish"
        raised += _raise_alert(
            session,
            "sentiment_spike",
            "warn",
            ticker_id,
            f"{symbol}: {direction} news spike — mean sentiment {mean:+.2f} over {n} items (24h)",
            f"spike:{symbol}:{now:%Y-%m-%d}:{direction}",
            {"mean": round(float(mean), 3), "n": int(n)},
        )

    # Rule 3: composite rank jump between the last two score dates
    profile = session.scalars(select(WeightProfile).where(WeightProfile.is_default)).first()
    if profile:
        dates = [
            d
            for (d,) in session.execute(
                select(CompositeScore.score_date)
                .where(CompositeScore.profile_id == profile.profile_id)
                .distinct()
                .order_by(CompositeScore.score_date.desc())
                .limit(2)
            )
        ]
        if len(dates) == 2:
            latest, prev = dates
            ranks: dict[str, dict[str, int]] = {}
            for row in session.scalars(
                select(CompositeScore).where(
                    CompositeScore.profile_id == profile.profile_id,
                    CompositeScore.score_date.in_([latest, prev]),
                    CompositeScore.rank.is_not(None),
                )
            ).all():
                slot = "latest" if row.score_date == latest else "prev"
                ranks.setdefault(row.ticker_id, {})[slot] = int(row.rank)  # type: ignore[arg-type]
            for ticker_id, slots in ranks.items():
                if "latest" not in slots or "prev" not in slots:
                    continue
                jump = slots["prev"] - slots["latest"]  # positive = climbed
                if abs(jump) < RANK_JUMP:
                    continue
                symbol = tickers.get(ticker_id, "?")
                verb = "climbed" if jump > 0 else "dropped"
                raised += _raise_alert(
                    session,
                    "rank_jump",
                    "info",
                    ticker_id,
                    f"{symbol}: {verb} {abs(jump)} places to rank #{slots['latest']}",
                    f"rank:{symbol}:{latest}",
                    {"from": slots["prev"], "to": slots["latest"]},
                )
    return f"raised {raised} alerts"

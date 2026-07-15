"""Export chart/score data for the blog build (docs/PLAN.md phase 4).

Writes JSON to apps/web/src/data/generated/ — consumed at Astro build
time, so the published site stays fully static with zero client-side
data fetching. Only data derived from PUBLISHED reports and computed
scores leaves the DB.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bullwright_db.models import (
    Agent,
    CompositeScore,
    IndexDefinition,
    IndexScore,
    PriceBar,
    Report,
    Ticker,
    WeightProfile,
)
from bullwright_quant import all_scorecards
from sqlalchemy import select
from sqlalchemy.orm import Session

PRICE_POINTS = 130  # ~6 months of trading days on the chart


def _ticker_payload(
    session: Session, ticker: Ticker, profile: WeightProfile | None
) -> dict[str, Any]:
    bars = session.scalars(
        select(PriceBar)
        .where(PriceBar.ticker_id == ticker.ticker_id)
        .order_by(PriceBar.bar_date.desc())
        .limit(PRICE_POINTS)
    ).all()
    prices = [[b.bar_date.isoformat(), float(b.adj_close)] for b in reversed(bars)]

    composite: list[list[Any]] = []
    latest_rank: int | None = None
    latest_score: float | None = None
    prev_score: float | None = None
    if profile:
        rows = session.scalars(
            select(CompositeScore)
            .where(
                CompositeScore.ticker_id == ticker.ticker_id,
                CompositeScore.profile_id == profile.profile_id,
                CompositeScore.score.is_not(None),
            )
            .order_by(CompositeScore.score_date)
        ).all()
        composite = [[r.score_date.isoformat(), r.score, r.rank] for r in rows]
        if rows:
            latest_rank = rows[-1].rank
            latest_score = rows[-1].score
            if len(rows) > 1:
                prev_score = rows[-2].score

    latest_indexes: dict[str, float] = {}
    for row in session.scalars(
        select(IndexScore)
        .where(IndexScore.ticker_id == ticker.ticker_id)
        .order_by(IndexScore.score_date.desc())
    ).all():
        if row.index_key not in latest_indexes:
            latest_indexes[row.index_key] = row.score

    # latest PUBLISHED verdict per agent -> consensus diff
    verdicts: list[dict[str, Any]] = []
    seen_agents: set[str] = set()
    for report in session.scalars(
        select(Report)
        .where(
            Report.ticker_id == ticker.ticker_id,
            Report.status == "published",
            Report.verdict.is_not(None),
        )
        .order_by(Report.published_at.desc())
    ).all():
        agent = session.get(Agent, report.author_agent_id)
        if agent is None or agent.name in seen_agents:
            continue
        seen_agents.add(agent.name)
        if report.verdict is None or report.published_at is None:
            continue  # unreachable: query filters ensure both
        verdicts.append(
            {
                "agent": agent.name,
                "model": report.author_model,
                "rating": report.verdict.get("rating"),
                "confidence": report.verdict.get("confidence"),
                "one_liner": report.verdict.get("one_liner"),
                "published": report.published_at.date().isoformat(),
                "report_id": report.report_id,
            }
        )

    return {
        "symbol": ticker.symbol,
        "name": ticker.name,
        "sector": ticker.sector,
        "prices": prices,
        "composite": composite,
        "latest_indexes": latest_indexes,
        "latest_rank": latest_rank,
        "latest_score": latest_score,
        "prev_score": prev_score,
        "verdicts": verdicts,
    }


def export_site_data(session: Session, out_dir: Path) -> dict[str, int]:
    generated = out_dir / "data" / "generated"
    generated.mkdir(parents=True, exist_ok=True)

    profile = session.scalars(select(WeightProfile).where(WeightProfile.is_default)).first()
    tickers = session.scalars(select(Ticker).where(Ticker.is_active).order_by(Ticker.symbol)).all()
    ticker_payloads = [_ticker_payload(session, t, profile) for t in tickers]

    indexes = [
        {
            "index_key": row.index_key,
            "version": row.version,
            "direction": row.direction,
            "description": row.description,
        }
        for row in session.scalars(
            select(IndexDefinition).order_by(IndexDefinition.index_key)
        ).all()
    ]
    scorecards = all_scorecards(session, datetime.now(UTC).date())

    (generated / "tickers.json").write_text(json.dumps(ticker_payloads, indent=1))
    (generated / "indexes.json").write_text(json.dumps(indexes, indent=1))
    (generated / "scorecards.json").write_text(json.dumps(scorecards, indent=1))
    (generated / "meta.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "profile": profile.name if profile else None,
            }
        )
    )
    return {"tickers": len(ticker_payloads), "indexes": len(indexes), "scorecards": len(scorecards)}

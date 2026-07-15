"""Scoring engine: cross-sectional normalization + weighted composites
(docs/INDEXES.md §1, §4). Pure functions first, DB plumbing second."""

import hashlib
from datetime import date

import numpy as np
from bullwright_core.indexes import INDEX_REGISTRY, IndexContext, VerdictObs
from bullwright_core.indexes.protocol import Direction
from bullwright_db.models import (
    CompositeScore,
    Fundamental,
    IndexDefinition,
    IndexScore,
    PriceBar,
    Report,
    Ticker,
    WeightProfile,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

# --- pure functions ---------------------------------------------------------


def normalize(raw: dict[str, float | None], direction: Direction) -> dict[str, float | None]:
    """Winsorized (p5/p95) min-max to 0-100 across one date's universe.
    None stays None; all-equal values -> 50 for everyone present."""
    present = {k: v for k, v in raw.items() if v is not None}
    if not present:
        return dict.fromkeys(raw)
    values = np.array(list(present.values()), dtype=np.float64)
    lo, hi = np.percentile(values, 5.0), np.percentile(values, 95.0)
    clipped = np.clip(values, lo, hi)
    span = clipped.max() - clipped.min()
    out: dict[str, float | None] = dict.fromkeys(raw)
    for key, val in zip(present, clipped, strict=True):
        score = 50.0 if span == 0 else 100.0 * (val - clipped.min()) / span
        if direction is Direction.LOWER_BETTER:
            score = 100.0 - score
        out[key] = round(float(score), 4)
    return out


class WeightError(ValueError):
    pass


def validate_weights(weights: dict[str, float]) -> None:
    unknown = set(weights) - set(INDEX_REGISTRY)
    if unknown:
        raise WeightError(f"unknown index keys: {sorted(unknown)}")
    if any(w < 0 for w in weights.values()):
        raise WeightError("weights must be >= 0")
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9:
        raise WeightError(f"weights must sum to 1.0 (got {total})")


def compose(weights: dict[str, float], scores: dict[str, float | None]) -> float | None:
    """Weighted composite with pro-rata redistribution for missing index
    scores; None when >50% of total weight is missing (never a fake 50)."""
    present_weight = sum(w for k, w in weights.items() if scores.get(k) is not None)
    if present_weight <= 0.5:
        return None
    total = 0.0
    for key, w in weights.items():
        s = scores.get(key)
        if s is not None:
            total += s * (w / present_weight)
    return round(total, 4)


# --- DB plumbing --------------------------------------------------------------


def sync_index_definitions(session: Session) -> int:
    for idx in INDEX_REGISTRY.values():
        row = session.get(IndexDefinition, idx.key)
        if row is None:
            session.add(
                IndexDefinition(
                    index_key=idx.key,
                    version=idx.version,
                    direction=idx.direction.value,
                    description=idx.description,
                )
            )
        else:
            row.version = idx.version
            row.direction = idx.direction.value
            row.description = idx.description
    return len(INDEX_REGISTRY)


def _build_context(session: Session, ticker: Ticker, as_of: date) -> IndexContext:
    bars = [
        (row.bar_date, float(row.adj_close))
        for row in session.scalars(
            select(PriceBar).where(
                PriceBar.ticker_id == ticker.ticker_id, PriceBar.bar_date <= as_of
            )
        ).all()
    ]
    fundamentals = [
        (row.as_of, dict(row.metrics))
        for row in session.scalars(
            select(Fundamental).where(
                Fundamental.ticker_id == ticker.ticker_id, Fundamental.as_of <= as_of
            )
        ).all()
    ]
    verdicts = []
    for r in session.scalars(
        select(Report).where(
            Report.ticker_id == ticker.ticker_id,
            Report.status == "published",
            Report.verdict.is_not(None),
        )
    ).all():
        if r.published_at is None or r.verdict is None:
            continue
        if r.published_at.date() > as_of:
            continue
        verdicts.append(
            VerdictObs(
                r.published_at.date(),
                str(r.verdict["rating"]),
                float(r.verdict.get("confidence", 0.5)),
            )
        )
    return IndexContext(ticker.symbol, as_of, bars, fundamentals, verdicts)  # type: ignore[arg-type]


def compute_index_scores(session: Session, score_dates: list[date]) -> int:
    """Compute + normalize every registered index for every active ticker
    on the given dates. Idempotent per (ticker, index, date)."""
    tickers = session.scalars(select(Ticker).where(Ticker.is_active)).all()
    written = 0
    for as_of in score_dates:
        contexts = {t.ticker_id: _build_context(session, t, as_of) for t in tickers}
        for idx in INDEX_REGISTRY.values():
            raw = {tid: idx.compute(ctx) for tid, ctx in contexts.items()}
            scores = normalize(raw, idx.direction)
            if idx.key == "sentiment":
                # no coverage = neutral, not missing (docs/INDEXES.md §2)
                scores = {k: (50.0 if v is None else v) for k, v in scores.items()}
            for tid in contexts:
                if scores[tid] is None:
                    continue
                digest = hashlib.sha256(
                    f"{idx.key}:{idx.version}:{tid}:{as_of}:{raw[tid]}".encode()
                ).hexdigest()[:16]
                session.merge(
                    IndexScore(
                        ticker_id=tid,
                        index_key=idx.key,
                        score_date=as_of,
                        raw_value=raw[tid],
                        score=scores[tid],
                        inputs_digest=digest,
                    )
                )
                written += 1
    return written


def compute_composites(session: Session, profile: WeightProfile, score_dates: list[date]) -> int:
    weights = {k: float(v) for k, v in profile.weights.items()}
    validate_weights(weights)
    written = 0
    for as_of in score_dates:
        rows = session.scalars(select(IndexScore).where(IndexScore.score_date == as_of)).all()
        by_ticker: dict[str, dict[str, float | None]] = {}
        for row in rows:
            by_ticker.setdefault(row.ticker_id, {})[row.index_key] = row.score
        composites = {tid: compose(weights, scores) for tid, scores in by_ticker.items()}
        ranked = sorted(
            (tid for tid, s in composites.items() if s is not None),
            key=lambda tid: -composites[tid],  # type: ignore[operator]
        )
        ranks = {tid: i + 1 for i, tid in enumerate(ranked)}
        session.execute(
            delete(CompositeScore).where(
                CompositeScore.profile_id == profile.profile_id,
                CompositeScore.score_date == as_of,
            )
        )
        for tid, score in composites.items():
            session.add(
                CompositeScore(
                    ticker_id=tid,
                    profile_id=profile.profile_id,
                    score_date=as_of,
                    score=score,
                    rank=ranks.get(tid),
                )
            )
            written += 1
    return written


def default_profile(session: Session, created_by: str = "operator") -> WeightProfile:
    """Get-or-create the default weight profile (docs/INDEXES.md §4)."""
    existing = session.scalars(select(WeightProfile).where(WeightProfile.name == "default")).first()
    if existing:
        return existing
    from bullwright_core.ids import new_id

    profile = WeightProfile(
        profile_id=new_id("wp"),
        name="default",
        weights={
            "value": 0.20,
            "momentum": 0.25,
            "quality": 0.25,
            "volatility": 0.10,
            "sentiment": 0.20,
        },
        is_default=True,
        created_by=created_by,
    )
    session.add(profile)
    session.flush()
    return profile


def universe_dates(session: Session, start: date, end: date) -> list[date]:
    """Trading dates observed in price_bars within [start, end]."""
    rows = session.execute(
        select(PriceBar.bar_date)
        .where(PriceBar.bar_date >= start, PriceBar.bar_date <= end)
        .distinct()
        .order_by(PriceBar.bar_date)
    ).scalars()
    return list(rows)

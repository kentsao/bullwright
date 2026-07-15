"""Quant endpoints (docs/API.md §5): prices, scores, indexes, weight
profiles, backtests."""

from datetime import date, datetime
from typing import Annotated, Any

from bullwright_core.ids import new_id
from bullwright_db.models import (
    BacktestRun,
    CompositeScore,
    IndexDefinition,
    IndexScore,
    Job,
    PriceBar,
    Ticker,
    WeightProfile,
)
from bullwright_quant import WeightError, validate_weights
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from bullwright_api.auth.deps import SessionDep, require_scope
from bullwright_api.auth.keys import Principal
from bullwright_api.errors import Problem, not_found, validation_problem
from bullwright_api.services.audit import audit

router = APIRouter(tags=["quant"])

MarketScope = Annotated[Principal, Depends(require_scope("market:read"))]
BacktestScope = Annotated[Principal, Depends(require_scope("backtest:run", write=True))]
AdminScope = Annotated[Principal, Depends(require_scope("admin", write=True))]


def _ticker_or_404(session: SessionDep, symbol: str) -> Ticker:
    row = session.scalars(select(Ticker).where(Ticker.symbol == symbol.upper())).first()
    if row is None:
        raise not_found("ticker")
    return row


@router.get("/tickers/{symbol}/prices")
def get_prices(
    symbol: str,
    session: SessionDep,
    principal: MarketScope,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> dict[str, Any]:
    ticker = _ticker_or_404(session, symbol)
    q = select(PriceBar).where(PriceBar.ticker_id == ticker.ticker_id).order_by(PriceBar.bar_date)
    if from_:
        q = q.where(PriceBar.bar_date >= from_)
    if to:
        q = q.where(PriceBar.bar_date <= to)
    bars = [
        {
            "date": row.bar_date.isoformat(),
            "close": float(row.close),
            "adj_close": float(row.adj_close),
            "volume": row.volume,
            "snapshot_id": row.snapshot_id,
        }
        for row in session.scalars(q).all()
    ]
    return {"symbol": ticker.symbol, "bars": bars}


@router.get("/tickers/{symbol}/scores")
def get_scores(
    symbol: str,
    session: SessionDep,
    principal: MarketScope,
    profile: str = "default",
) -> dict[str, Any]:
    ticker = _ticker_or_404(session, symbol)
    wp = session.scalars(select(WeightProfile).where(WeightProfile.name == profile)).first()
    index_rows = session.scalars(
        select(IndexScore)
        .where(IndexScore.ticker_id == ticker.ticker_id)
        .order_by(IndexScore.score_date)
    ).all()
    series: dict[str, list[dict[str, Any]]] = {}
    for row in index_rows:
        series.setdefault(row.index_key, []).append(
            {"date": row.score_date.isoformat(), "score": row.score, "raw": row.raw_value}
        )
    composite: list[dict[str, Any]] = []
    if wp:
        for comp_row in session.scalars(
            select(CompositeScore)
            .where(
                CompositeScore.ticker_id == ticker.ticker_id,
                CompositeScore.profile_id == wp.profile_id,
            )
            .order_by(CompositeScore.score_date)
        ).all():
            composite.append(
                {
                    "date": comp_row.score_date.isoformat(),
                    "score": comp_row.score,
                    "rank": comp_row.rank,
                }
            )
    return {
        "symbol": ticker.symbol,
        "profile": profile if wp else None,
        "indexes": series,
        "composite": composite,
        "disclaimer": "Bullwright is a research toy. Nothing here is investment advice.",
    }


@router.get("/indexes")
def list_indexes(session: SessionDep, principal: MarketScope) -> list[dict[str, Any]]:
    return [
        {
            "index_key": row.index_key,
            "version": row.version,
            "direction": row.direction,
            "description": row.description,
        }
        for row in session.scalars(select(IndexDefinition).order_by(IndexDefinition.index_key))
    ]


class WeightProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    weights: dict[str, float]


@router.get("/weight-profiles")
def list_profiles(session: SessionDep, principal: MarketScope) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": p.profile_id,
            "name": p.name,
            "weights": p.weights,
            "is_default": p.is_default,
            "is_locked": p.is_locked,
        }
        for p in session.scalars(select(WeightProfile).order_by(WeightProfile.created_at))
    ]


@router.post("/weight-profiles", status_code=201)
def create_profile(
    payload: WeightProfileIn, session: SessionDep, principal: AdminScope
) -> dict[str, Any]:
    try:
        validate_weights(payload.weights)
    except WeightError as e:
        raise validation_problem([{"loc": "weights", "msg": str(e)}]) from e
    if session.scalars(select(WeightProfile).where(WeightProfile.name == payload.name)).first():
        raise Problem(
            409,
            f"profile {payload.name!r} already exists — profiles are immutable, create a new name",
            kind="conflict",
        )
    row = WeightProfile(
        profile_id=new_id("wp"),
        name=payload.name,
        weights=payload.weights,
        created_by=principal.agent_name,
    )
    session.add(row)
    session.flush()
    audit(
        session,
        "weight_profile.create",
        principal=principal,
        entity_type="weight_profile",
        entity_id=row.profile_id,
    )
    return {"profile_id": row.profile_id, "name": row.name, "weights": row.weights}


class BacktestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight_profile: str = "default"
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    universe: list[str] | None = None  # None = whole watchlist
    config: dict[str, Any] = Field(default_factory=dict)


@router.post("/backtests", status_code=202)
def create_backtest(
    payload: BacktestIn, session: SessionDep, principal: BacktestScope
) -> dict[str, Any]:
    profile = session.scalars(
        select(WeightProfile).where(WeightProfile.name == payload.weight_profile)
    ).first()
    if profile is None:
        raise validation_problem(
            [{"loc": "weight_profile", "msg": f"unknown profile {payload.weight_profile!r}"}]
        )
    if payload.from_date >= payload.to_date:
        raise validation_problem([{"loc": "from", "msg": "from must be before to"}])
    universe = payload.universe or [
        t.symbol for t in session.scalars(select(Ticker).where(Ticker.is_active)).all()
    ]
    run = BacktestRun(
        backtest_id=new_id("bt"),
        profile_id=profile.profile_id,
        from_date=payload.from_date,
        to_date=payload.to_date,
        universe=universe,
        config={
            "top_n": payload.config.get("top_n", 5),
            "cost_bps": payload.config.get("cost_bps", 10.0),
        },
        snapshot_id="pending",
        code_version="v0.3",
    )
    session.add(run)
    session.add(
        Job(job_id=new_id("job"), kind="backtest", payload={"backtest_id": run.backtest_id})
    )
    session.flush()
    audit(
        session,
        "backtest.enqueue",
        principal=principal,
        entity_type="backtest",
        entity_id=run.backtest_id,
    )
    return {"backtest_id": run.backtest_id, "status": "queued"}


@router.get("/backtests/{backtest_id}")
def get_backtest(backtest_id: str, session: SessionDep, principal: MarketScope) -> dict[str, Any]:
    run = session.get(BacktestRun, backtest_id)
    if run is None:
        raise not_found("backtest")

    def _d(v: date | datetime) -> str:
        return v.isoformat()

    return {
        "backtest_id": run.backtest_id,
        "status": run.status,
        "profile_id": run.profile_id,
        "from": _d(run.from_date),
        "to": _d(run.to_date),
        "universe": run.universe,
        "config": run.config,
        "metrics": run.metrics,
        "artifact_path": run.artifact_path,
        "snapshot_id": run.snapshot_id,
        "code_version": run.code_version,
        "disclaimer": "3-6 month backtests are weather, not climate.",
    }

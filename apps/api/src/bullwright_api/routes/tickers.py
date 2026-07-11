from typing import Annotated

from bullwright_core.ids import new_id
from bullwright_db.models import Ticker
from fastapi import APIRouter, Depends
from sqlalchemy import select

from bullwright_api.auth.deps import SessionDep, require_scope
from bullwright_api.auth.keys import Principal
from bullwright_api.errors import Problem, not_found
from bullwright_api.schemas import TickerIn, TickerOut
from bullwright_api.services.audit import audit

router = APIRouter(prefix="/tickers", tags=["tickers"])

MarketScope = Annotated[Principal, Depends(require_scope("market:read"))]
AdminScope = Annotated[Principal, Depends(require_scope("admin", write=True))]


@router.post("", status_code=201, response_model=TickerOut)
def add_ticker(payload: TickerIn, session: SessionDep, principal: AdminScope) -> TickerOut:
    symbol = payload.symbol.upper()
    exists = session.scalars(
        select(Ticker).where(Ticker.symbol == symbol, Ticker.exchange == payload.exchange)
    ).first()
    if exists:
        raise Problem(409, f"ticker {symbol} already on the watchlist", kind="conflict")
    row = Ticker(
        ticker_id=new_id("tkr"),
        symbol=symbol,
        exchange=payload.exchange,
        name=payload.name,
        sector=payload.sector,
        industry=payload.industry,
        currency=payload.currency.upper(),
    )
    session.add(row)
    session.flush()
    audit(
        session,
        "ticker.add",
        principal=principal,
        entity_type="ticker",
        entity_id=row.ticker_id,
        payload={"symbol": symbol},
    )
    return TickerOut.from_row(row)


@router.get("", response_model=list[TickerOut])
def list_tickers(session: SessionDep, principal: MarketScope) -> list[TickerOut]:
    rows = session.scalars(select(Ticker).where(Ticker.is_active).order_by(Ticker.symbol)).all()
    return [TickerOut.from_row(r) for r in rows]


@router.get("/{symbol}", response_model=TickerOut)
def get_ticker(symbol: str, session: SessionDep, principal: MarketScope) -> TickerOut:
    row = session.scalars(select(Ticker).where(Ticker.symbol == symbol.upper())).first()
    if row is None:
        raise not_found("ticker")
    return TickerOut.from_row(row)

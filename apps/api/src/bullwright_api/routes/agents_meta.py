"""Agent scorecard endpoint (docs/AGENT_SKILLS.md §6)."""

from datetime import UTC, datetime
from typing import Annotated, Any

from bullwright_quant import all_scorecards, compute_scorecard
from fastapi import APIRouter, Depends

from bullwright_api.auth.deps import SessionDep, require_scope
from bullwright_api.auth.keys import Principal

router = APIRouter(prefix="/agents", tags=["agents"])

MarketScope = Annotated[Principal, Depends(require_scope("market:read"))]


@router.get("/scorecards")
def list_scorecards(session: SessionDep, principal: MarketScope) -> list[dict[str, Any]]:
    return all_scorecards(session, datetime.now(UTC).date())


@router.get("/{name}/scorecard")
def get_scorecard(name: str, session: SessionDep, principal: MarketScope) -> dict[str, Any]:
    card = compute_scorecard(session, name, datetime.now(UTC).date())
    result = card.summary()
    result["evaluations"] = [
        {
            "report_id": e.report_id,
            "ticker": e.ticker,
            "rating": e.rating,
            "confidence": e.confidence,
            "published": e.published.isoformat(),
            "checkpoint_days": e.checkpoint_days,
            "realized_return": e.realized_return,
            "hit": e.hit,
        }
        for e in card.evaluations
    ]
    return result

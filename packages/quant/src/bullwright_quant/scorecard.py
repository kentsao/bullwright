"""Agent scorecard (docs/AGENT_SKILLS.md §6): because verdicts are
structured, we can grade each agent against what prices actually did.

For every published report with a verdict and a ticker, evaluate the
realized adjusted-close move at fixed checkpoints (30d, 90d) and at the
verdict's own horizon — whichever have elapsed. Direction rules:
buy-ish verdicts are hits when the move is positive, sell-ish when
negative; hold is a hit inside a ±5% band. Calibration compares stated
confidence to realized accuracy per confidence bucket.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from bullwright_db.models import Agent, PriceBar, Report, Ticker
from sqlalchemy import select
from sqlalchemy.orm import Session

HOLD_BAND = 0.05
CHECKPOINTS = (30, 90)

BULLISH = {"strong_buy", "buy"}
BEARISH = {"strong_sell", "sell"}


@dataclass
class VerdictEval:
    report_id: str
    ticker: str
    rating: str
    confidence: float
    published: date
    checkpoint_days: int
    realized_return: float
    hit: bool


@dataclass
class Scorecard:
    agent: str
    evaluations: list[VerdictEval] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        if not self.evaluations:
            return {
                "agent": self.agent,
                "evaluated": 0,
                "hit_rate": None,
                "confidence_weighted_return": None,
                "calibration": [],
            }
        hits = [e for e in self.evaluations if e.hit]
        cw_num = sum(e.realized_return * e.confidence * _sign(e.rating) for e in self.evaluations)
        cw_den = sum(e.confidence for e in self.evaluations)
        buckets: dict[str, list[bool]] = {"low(<0.5)": [], "mid(0.5-0.75)": [], "high(>0.75)": []}
        for e in self.evaluations:
            if e.confidence < 0.5:
                buckets["low(<0.5)"].append(e.hit)
            elif e.confidence <= 0.75:
                buckets["mid(0.5-0.75)"].append(e.hit)
            else:
                buckets["high(>0.75)"].append(e.hit)
        return {
            "agent": self.agent,
            "evaluated": len(self.evaluations),
            "hit_rate": round(len(hits) / len(self.evaluations), 4),
            "confidence_weighted_return": round(cw_num / cw_den, 6) if cw_den else None,
            "calibration": [
                {
                    "bucket": name,
                    "n": len(vals),
                    "hit_rate": round(sum(vals) / len(vals), 4) if vals else None,
                }
                for name, vals in buckets.items()
            ],
            "checkpoints": sorted({e.checkpoint_days for e in self.evaluations}),
        }


def _sign(rating: str) -> float:
    if rating in BULLISH:
        return 1.0
    if rating in BEARISH:
        return -1.0
    return 0.0


def _is_hit(rating: str, realized: float) -> bool:
    if rating in BULLISH:
        return realized > 0
    if rating in BEARISH:
        return realized < 0
    return abs(realized) <= HOLD_BAND  # hold


def _close_on_or_after(bars: dict[date, float], target: date, limit_days: int = 7) -> float | None:
    """Adj close on target or the next trading day within a week."""
    for offset in range(limit_days):
        found = bars.get(target + timedelta(days=offset))
        if found is not None:
            return found
    return None


def compute_scorecard(session: Session, agent_name: str, as_of: date) -> Scorecard:
    agent = session.scalars(select(Agent).where(Agent.name == agent_name)).first()
    card = Scorecard(agent=agent_name)
    if agent is None:
        return card
    reports = session.scalars(
        select(Report).where(
            Report.author_agent_id == agent.agent_id,
            Report.status == "published",
            Report.verdict.is_not(None),
            Report.ticker_id.is_not(None),
        )
    ).all()
    for report in reports:
        if report.published_at is None or report.verdict is None:
            continue
        ticker = session.get(Ticker, report.ticker_id)
        if ticker is None:
            continue
        bars = {
            row.bar_date: float(row.adj_close)
            for row in session.scalars(
                select(PriceBar).where(PriceBar.ticker_id == ticker.ticker_id)
            ).all()
        }
        pub_date = report.published_at.date()
        base = _close_on_or_after(bars, pub_date)
        if base is None or base <= 0:
            continue
        horizon = int(report.verdict.get("horizon_days", 90))
        for checkpoint in sorted({*CHECKPOINTS, horizon}):
            target = pub_date + timedelta(days=checkpoint)
            if target > as_of:
                continue  # not elapsed yet
            end = _close_on_or_after(bars, target)
            if end is None:
                continue
            realized = end / base - 1.0
            rating = str(report.verdict["rating"])
            card.evaluations.append(
                VerdictEval(
                    report_id=report.report_id,
                    ticker=ticker.symbol,
                    rating=rating,
                    confidence=float(report.verdict.get("confidence", 0.5)),
                    published=pub_date,
                    checkpoint_days=checkpoint,
                    realized_return=round(realized, 6),
                    hit=_is_hit(rating, realized),
                )
            )
    return card


def all_scorecards(session: Session, as_of: date) -> list[dict[str, Any]]:
    agents = session.scalars(select(Agent).where(Agent.kind != "human")).all()
    return [compute_scorecard(session, a.name, as_of).summary() for a in agents]

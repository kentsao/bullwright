"""Point-in-time data view for one (ticker, as_of date).

The constructor FILTERS everything to observations <= as_of. Index code
physically cannot see the future — the look-ahead canary test poisons
future rows and asserts outputs are unchanged.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class VerdictObs:
    published: date
    rating: str
    confidence: float


@dataclass(frozen=True)
class NewsObs:
    """One analyzed news item: model-scored sentiment and relevance."""

    published: date
    sentiment: float  # -1..1
    relevance: float  # 0..1


class IndexContext:
    def __init__(
        self,
        ticker: str,
        as_of: date,
        bars: list[tuple[date, float]],  # (bar_date, adj_close), any order
        fundamentals: list[tuple[date, dict[str, Any]]] | None = None,
        verdicts: list[VerdictObs] | None = None,
        news: list[NewsObs] | None = None,
    ) -> None:
        self.ticker = ticker
        self.as_of = as_of
        self._bars = sorted(((d, c) for d, c in bars if d <= as_of), key=lambda x: x[0])
        fundamentals = fundamentals or []
        past_fundamentals = sorted(
            ((d, m) for d, m in fundamentals if d <= as_of), key=lambda x: x[0]
        )
        self._latest_fundamentals = past_fundamentals[-1][1] if past_fundamentals else None
        self._verdicts = [v for v in (verdicts or []) if v.published <= as_of]
        self._news = [n for n in (news or []) if n.published <= as_of]

    def closes(self, n: int) -> list[float]:
        """Last n adjusted closes up to as_of (oldest first); may be shorter."""
        return [c for _, c in self._bars[-n:]]

    def history_days(self) -> int:
        return len(self._bars)

    def fundamentals(self) -> dict[str, Any] | None:
        """Most recent fundamentals snapshot observed on or before as_of."""
        return self._latest_fundamentals

    def verdicts(self) -> list[VerdictObs]:
        """Published report verdicts up to as_of."""
        return list(self._verdicts)

    def news(self) -> list[NewsObs]:
        """Analyzed news items up to as_of."""
        return list(self._news)

"""The five v1 indexes (docs/INDEXES.md §2). Pure stdlib math — vector
work happens in the scoring engine, not here."""

import itertools
import math

from bullwright_core.indexes.context import IndexContext
from bullwright_core.indexes.protocol import Direction

RATING_VALUE = {"strong_buy": 2.0, "buy": 1.0, "hold": 0.0, "sell": -1.0, "strong_sell": -2.0}
SENTIMENT_HALF_LIFE_DAYS = 90.0
NEWS_HALF_LIFE_DAYS = 10.0


def _finite(x: float) -> float | None:
    return x if math.isfinite(x) else None


class MomentumIndex:
    """126-day return skipping the most recent 21 days (12-1 style,
    halved for our horizon)."""

    key = "momentum"
    version = "1.0"
    direction = Direction.HIGHER_BETTER
    requires = frozenset({"price_bars"})
    min_history_days = 127
    description = "126-day price return skipping the most recent 21 trading days."

    def compute(self, ctx: IndexContext) -> float | None:
        closes = ctx.closes(127)
        if len(closes) < 127:
            return None
        start, end = closes[0], closes[-22]
        if start <= 0:
            return None
        return _finite(end / start - 1.0)


class VolatilityIndex:
    key = "volatility"
    version = "1.0"
    direction = Direction.LOWER_BETTER
    requires = frozenset({"price_bars"})
    min_history_days = 64
    description = "63-day annualized standard deviation of daily log returns."

    def compute(self, ctx: IndexContext) -> float | None:
        closes = ctx.closes(64)
        if len(closes) < 64:
            return None
        rets = []
        for prev, cur in itertools.pairwise(closes):
            if prev <= 0 or cur <= 0:
                return None
            rets.append(math.log(cur / prev))
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return _finite(math.sqrt(var) * math.sqrt(252.0))


class ValueIndex:
    """Mean of available yields: 1/PE, 1/PS, 1/(EV/EBITDA). Missing
    components are dropped with reweighting; all-missing -> None.
    (v1 note: yields-mean stands in for the spec's blended rank so the
    index stays a pure per-ticker function; ranks are cross-sectional
    and belong to the normalization stage.)"""

    key = "value"
    version = "1.0"
    direction = Direction.HIGHER_BETTER  # yields: higher = cheaper
    requires = frozenset({"fundamentals"})
    min_history_days = 0
    description = "Blend of earnings/sales/EBITDA yields from the latest fundamentals."

    def compute(self, ctx: IndexContext) -> float | None:
        f = ctx.fundamentals()
        if not f:
            return None
        yields = []
        for field in ("pe", "ps", "ev_ebitda"):
            v = f.get(field)
            if isinstance(v, int | float) and v > 0:
                yields.append(1.0 / float(v))
        if not yields:
            return None
        return _finite(sum(yields) / len(yields))


class QualityIndex:
    key = "quality"
    version = "1.0"
    direction = Direction.HIGHER_BETTER
    requires = frozenset({"fundamentals"})
    min_history_days = 0
    description = "Blend of ROE, gross margin, and inverse leverage."

    def compute(self, ctx: IndexContext) -> float | None:
        f = ctx.fundamentals()
        if not f:
            return None
        parts = []
        roe = f.get("roe")
        if isinstance(roe, int | float):
            parts.append(float(roe))
        gm = f.get("gross_margin")
        if isinstance(gm, int | float):
            parts.append(float(gm))
        de = f.get("debt_to_equity")
        if isinstance(de, int | float) and de >= 0:
            parts.append(1.0 / (1.0 + float(de)))
        if not parts:
            return None
        return _finite(sum(parts) / len(parts))


class NewsSentimentIndex:
    """Relevance- and recency-weighted mean of model-analyzed news item
    sentiment (ADR-0002). Fast half-life (10d): news is weather. None
    when no analyzed items — weight redistribution handles absence."""

    key = "news_sentiment"
    version = "1.0"
    direction = Direction.HIGHER_BETTER
    requires = frozenset({"news"})
    min_history_days = 0
    description = "Model-analyzed news sentiment, relevance-weighted, 10-day half-life."

    def compute(self, ctx: IndexContext) -> float | None:
        items = ctx.news()
        if not items:
            return None
        num = 0.0
        den = 0.0
        for item in items:
            age_days = (ctx.as_of - item.published).days
            if age_days > 45:  # stale news carries ~0 weight anyway; cut the tail
                continue
            decay = 0.5 ** (age_days / NEWS_HALF_LIFE_DAYS)
            w = max(0.0, min(1.0, item.relevance)) * decay
            num += max(-1.0, min(1.0, item.sentiment)) * w
            den += w
        if den <= 0:
            return None
        return _finite(num / den)


class SentimentIndex:
    """Confidence-weighted mean of published verdict ratings with a
    90-day half-life decay. No coverage -> None raw value; the scoring
    engine maps missing sentiment to the neutral 50 after normalization
    (docs/INDEXES.md §2)."""

    key = "sentiment"
    version = "1.0"
    direction = Direction.HIGHER_BETTER
    requires = frozenset({"reports"})
    min_history_days = 0
    description = "Decay-weighted mean of published agent verdicts (90d half-life)."

    def compute(self, ctx: IndexContext) -> float | None:
        verdicts = ctx.verdicts()
        if not verdicts:
            return None
        num = 0.0
        den = 0.0
        for v in verdicts:
            rating = RATING_VALUE.get(v.rating)
            if rating is None:
                continue
            age_days = (ctx.as_of - v.published).days
            decay = 0.5 ** (age_days / SENTIMENT_HALF_LIFE_DAYS)
            w = max(0.0, min(1.0, v.confidence)) * decay
            num += rating * w
            den += w
        if den <= 0:
            return None
        return _finite(num / den)

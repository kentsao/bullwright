"""Protocol contract suite (docs/INDEXES.md §3): every registered index —
present and future — passes determinism, short-history None, no-NaN, and
the look-ahead canary. Plus hand-computed fixtures per v1 index."""

import math
from datetime import date, timedelta

import pytest
from bullwright_core.indexes import INDEX_REGISTRY, IndexContext, NewsObs, VerdictObs
from bullwright_core.indexes.protocol import Direction, Index


def synth_bars(days: int, start_price: float = 100.0, drift: float = 0.001) -> list:  # type: ignore[type-arg]
    """Deterministic synthetic daily bars ending 2026-06-30."""
    end = date(2026, 6, 30)
    bars = []
    price = start_price
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        price *= 1.0 + drift + 0.004 * math.sin(i)  # wiggle, deterministic
        bars.append((d, round(price, 6)))
    return bars


def full_context(as_of: date = date(2026, 6, 30)) -> IndexContext:
    return IndexContext(
        ticker="TEST",
        as_of=as_of,
        bars=synth_bars(200),
        fundamentals=[
            (
                date(2026, 6, 1),
                {
                    "pe": 20.0,
                    "ps": 5.0,
                    "ev_ebitda": 15.0,
                    "roe": 0.25,
                    "gross_margin": 0.6,
                    "debt_to_equity": 0.5,
                },
            )
        ],
        verdicts=[
            VerdictObs(date(2026, 6, 15), "buy", 0.8),
            VerdictObs(date(2026, 4, 1), "hold", 0.5),
        ],
        news=[
            NewsObs(date(2026, 6, 28), 0.6, 0.9),
            NewsObs(date(2026, 6, 20), -0.2, 0.5),
        ],
    )


ALL_INDEXES = sorted(INDEX_REGISTRY.values(), key=lambda i: i.key)


@pytest.mark.parametrize("idx", ALL_INDEXES, ids=lambda i: i.key)
def test_satisfies_protocol(idx: Index) -> None:
    assert isinstance(idx, Index)
    assert idx.direction in (Direction.HIGHER_BETTER, Direction.LOWER_BETTER)
    assert idx.requires <= {"price_bars", "fundamentals", "reports", "news"}


@pytest.mark.parametrize("idx", ALL_INDEXES, ids=lambda i: i.key)
def test_deterministic(idx: Index) -> None:
    a, b = idx.compute(full_context()), idx.compute(full_context())
    assert a == b


@pytest.mark.parametrize("idx", ALL_INDEXES, ids=lambda i: i.key)
def test_none_on_empty_context(idx: Index) -> None:
    empty = IndexContext("TEST", date(2026, 6, 30), bars=[])
    assert idx.compute(empty) is None


@pytest.mark.parametrize("idx", ALL_INDEXES, ids=lambda i: i.key)
def test_never_nan_or_inf(idx: Index) -> None:
    value = idx.compute(full_context())
    if value is not None:
        assert math.isfinite(value)


@pytest.mark.parametrize("idx", ALL_INDEXES, ids=lambda i: i.key)
def test_lookahead_canary(idx: Index) -> None:
    """Poisoned future data must not change the output — the context
    filters it, so this guards the CONSTRUCTOR forever."""
    as_of = date(2026, 3, 31)
    clean = IndexContext(
        "TEST",
        as_of,
        bars=synth_bars(200),
        fundamentals=[(date(2026, 3, 1), {"pe": 20.0, "roe": 0.25})],
        verdicts=[VerdictObs(date(2026, 3, 15), "buy", 0.8)],
        news=[NewsObs(date(2026, 3, 20), 0.4, 0.8)],
    )
    poisoned = IndexContext(
        "TEST",
        as_of,
        bars=[*synth_bars(200), (date(2026, 4, 1), 999999.0), (date(2026, 5, 1), 0.000001)],
        fundamentals=[
            (date(2026, 3, 1), {"pe": 20.0, "roe": 0.25}),
            (date(2026, 4, 2), {"pe": 0.01, "roe": 99.0}),
        ],
        verdicts=[
            VerdictObs(date(2026, 3, 15), "buy", 0.8),
            VerdictObs(date(2026, 4, 3), "strong_sell", 1.0),
        ],
        news=[
            NewsObs(date(2026, 3, 20), 0.4, 0.8),
            NewsObs(date(2026, 4, 5), -1.0, 1.0),
        ],
    )
    assert idx.compute(clean) == idx.compute(poisoned)


# --- hand-computed fixtures ------------------------------------------------


def test_momentum_exact() -> None:
    # flat then +1%/day: use simple bars we can compute by hand
    end = date(2026, 6, 30)
    bars = [(end - timedelta(days=200 - i), 100.0 * (1.01**i)) for i in range(200)]
    ctx = IndexContext("T", end, bars=bars)
    got = INDEX_REGISTRY["momentum"].compute(ctx)
    # closes(127)[0] is i=73; [-22] is i=178 -> (1.01^178)/(1.01^73) - 1
    expected = 1.01 ** (178 - 73) - 1
    assert got is not None and abs(got - expected) < 1e-9


def test_volatility_zero_for_constant_prices() -> None:
    end = date(2026, 6, 30)
    bars = [(end - timedelta(days=99 - i), 50.0) for i in range(100)]
    got = INDEX_REGISTRY["volatility"].compute(IndexContext("T", end, bars=bars))
    assert got == 0.0


def test_value_drops_missing_components() -> None:
    ctx = IndexContext(
        "T",
        date(2026, 6, 30),
        bars=[],
        fundamentals=[(date(2026, 6, 1), {"pe": 25.0, "ps": None, "ev_ebitda": -3.0})],
    )
    got = INDEX_REGISTRY["value"].compute(ctx)
    assert got is not None and abs(got - (1 / 25.0)) < 1e-12  # only PE usable


def test_sentiment_decay_and_confidence_weighting() -> None:
    as_of = date(2026, 6, 30)
    ctx = IndexContext(
        "T",
        as_of,
        bars=[],
        verdicts=[
            VerdictObs(as_of, "strong_buy", 1.0),  # weight 1.0, value 2
            VerdictObs(as_of - timedelta(days=90), "strong_sell", 1.0),  # weight .5, value -2
        ],
    )
    got = INDEX_REGISTRY["sentiment"].compute(ctx)
    expected = (2.0 * 1.0 + (-2.0) * 0.5) / 1.5  # = 0.666...
    assert got is not None and abs(got - expected) < 1e-9


def test_quality_exact() -> None:
    ctx = IndexContext(
        "T",
        date(2026, 6, 30),
        bars=[],
        fundamentals=[(date(2026, 6, 1), {"roe": 0.3, "gross_margin": 0.6, "debt_to_equity": 1.0})],
    )
    got = INDEX_REGISTRY["quality"].compute(ctx)
    assert got is not None and abs(got - (0.3 + 0.6 + 0.5) / 3) < 1e-12

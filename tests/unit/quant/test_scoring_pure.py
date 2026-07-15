"""Pure scoring functions: normalization edges + weight math (TEST_PLAN §4)."""

import pytest
from bullwright_core.indexes import INDEX_REGISTRY
from bullwright_core.indexes.protocol import Direction
from bullwright_quant import WeightError, compose, normalize, validate_weights
from hypothesis import given
from hypothesis import strategies as st


def test_normalize_basic_and_direction_flip() -> None:
    raw: dict[str, float | None] = {"a": 1.0, "b": 2.0, "c": 3.0}
    up = normalize(raw, Direction.HIGHER_BETTER)
    assert up["a"] == 0.0 and up["c"] == 100.0
    down = normalize(raw, Direction.LOWER_BETTER)
    assert down["a"] == 100.0 and down["c"] == 0.0


def test_normalize_constant_universe_is_50() -> None:
    consts: dict[str, float | None] = {"a": 7.0, "b": 7.0, "c": 7.0}
    out = normalize(consts, Direction.HIGHER_BETTER)
    assert all(v == 50.0 for v in out.values())


def test_normalize_preserves_none_and_winsorizes_outliers() -> None:
    raw: dict[str, float | None] = {f"t{i}": float(i) for i in range(20)}
    raw["outlier"] = 1_000_000.0
    raw["missing"] = None
    out = normalize(raw, Direction.HIGHER_BETTER)
    assert out["missing"] is None
    # winsorization: the outlier caps at p95, so t19 shouldn't be crushed to ~0
    assert out["t19"] is not None and out["t19"] > 80.0


def test_normalize_single_ticker() -> None:
    single: dict[str, float | None] = {"only": 42.0}
    out = normalize(single, Direction.HIGHER_BETTER)
    assert out["only"] == 50.0


@pytest.mark.parametrize(
    "weights",
    [
        {"value": 0.5, "momentum": 0.6},  # sums > 1
        {"value": -0.2, "momentum": 1.2},  # negative
        {"value": 0.5, "meme_factor": 0.5},  # unknown key
    ],
)
def test_bad_weights_rejected(weights: dict[str, float]) -> None:
    with pytest.raises(WeightError):
        validate_weights(weights)


def test_missing_scores_redistribute_pro_rata() -> None:
    weights = {"value": 0.25, "momentum": 0.25, "quality": 0.25, "volatility": 0.25}
    scores: dict[str, float | None] = {
        "value": 80.0,
        "momentum": 60.0,
        "quality": None,
        "volatility": None,
    }
    # 50% present — NOT strictly more than half -> insufficient
    assert compose(weights, scores) is None
    scores["quality"] = 40.0  # 75% present now
    got = compose(weights, scores)
    assert got is not None
    assert abs(got - (80 + 60 + 40) / 3) < 1e-9  # equal thirds after redistribution


def test_mostly_missing_composite_is_none_not_fifty() -> None:
    weights = {"value": 0.9, "momentum": 0.1}
    assert compose(weights, {"value": None, "momentum": 100.0}) is None


valid_keys = sorted(INDEX_REGISTRY)


@given(
    st.dictionaries(
        st.sampled_from(valid_keys),
        st.one_of(st.none(), st.floats(min_value=0, max_value=100)),
        min_size=len(valid_keys),
        max_size=len(valid_keys),
    )
)
def test_property_composite_in_range_or_none(scores: dict[str, float | None]) -> None:
    weights = {k: 1.0 / len(valid_keys) for k in valid_keys}
    got = compose(weights, scores)
    assert got is None or 0.0 <= got <= 100.0


@given(st.lists(st.floats(min_value=-1e6, max_value=1e6), min_size=2, max_size=40, unique=True))
def test_property_normalize_bounds_and_rank_order(values: list[float]) -> None:
    raw: dict[str, float | None] = {f"t{i}": v for i, v in enumerate(values)}
    out = normalize(raw, Direction.HIGHER_BETTER)
    nums = [v for v in out.values() if v is not None]
    assert all(0.0 <= v <= 100.0 for v in nums)
    # rank order preserved (winsorization may tie the tails, so ordering
    # must be non-strict but never inverted)
    pairs = sorted(raw.items(), key=lambda kv: kv[1] if kv[1] is not None else 0.0)
    scores_in_raw_order = [out[k] for k, _ in pairs]
    import itertools

    assert all(
        a <= b + 1e-9  # type: ignore[operator]
        for a, b in itertools.pairwise(scores_in_raw_order)
    )

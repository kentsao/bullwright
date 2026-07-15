"""Bullwright quant engine (docs/INDEXES.md)."""

from bullwright_quant.backtest import BacktestConfig, BacktestOutput, run_backtest
from bullwright_quant.ingest import ingest_fundamentals, ingest_prices
from bullwright_quant.providers import (
    Bar,
    FixtureProvider,
    MarketDataProvider,
    YFinanceProvider,
    get_provider,
)
from bullwright_quant.scoring import (
    WeightError,
    compose,
    compute_composites,
    compute_index_scores,
    default_profile,
    normalize,
    sync_index_definitions,
    universe_dates,
    validate_weights,
)

__all__ = [
    "BacktestConfig",
    "BacktestOutput",
    "Bar",
    "FixtureProvider",
    "MarketDataProvider",
    "WeightError",
    "YFinanceProvider",
    "compose",
    "compute_composites",
    "compute_index_scores",
    "default_profile",
    "get_provider",
    "ingest_fundamentals",
    "ingest_prices",
    "normalize",
    "run_backtest",
    "sync_index_definitions",
    "universe_dates",
    "validate_weights",
]

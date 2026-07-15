from enum import StrEnum
from typing import Protocol, runtime_checkable

from bullwright_core.indexes.context import IndexContext


class Direction(StrEnum):
    HIGHER_BETTER = "higher_better"
    LOWER_BETTER = "lower_better"


@runtime_checkable
class Index(Protocol):
    """Contract every index must satisfy (docs/INDEXES.md §3).

    Rules: pure function of the context — no I/O, no DB, no randomness.
    Return None when history/inputs are insufficient; never NaN/inf.
    Bump `version` whenever the formula changes (forces recompute)."""

    key: str
    version: str
    direction: Direction
    requires: frozenset[str]  # subset of {"price_bars", "fundamentals", "reports"}
    min_history_days: int
    description: str

    def compute(self, ctx: IndexContext) -> float | None: ...

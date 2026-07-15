"""Quant index protocol (docs/INDEXES.md §3).

An Index turns point-in-time data for one (ticker, date) into a raw
value; cross-sectional normalization to 0-100 happens in the scoring
engine (bullwright-quant), not here. Adding an index = write a class,
append it to INDEX_REGISTRY, run `bw indexes sync`.

Look-ahead is structurally impossible: IndexContext exposes only data
observed on or before its `as_of` date — there is no API for the future.
"""

from bullwright_core.indexes.context import IndexContext, VerdictObs
from bullwright_core.indexes.protocol import Direction, Index
from bullwright_core.indexes.registry import INDEX_REGISTRY, get_index

__all__ = [
    "INDEX_REGISTRY",
    "Direction",
    "Index",
    "IndexContext",
    "VerdictObs",
    "get_index",
]

from bullwright_core.indexes.core_indexes import (
    MomentumIndex,
    QualityIndex,
    SentimentIndex,
    ValueIndex,
    VolatilityIndex,
)
from bullwright_core.indexes.protocol import Index

INDEX_REGISTRY: dict[str, Index] = {
    idx.key: idx
    for idx in (
        ValueIndex(),
        MomentumIndex(),
        QualityIndex(),
        VolatilityIndex(),
        SentimentIndex(),
    )
}


def get_index(key: str) -> Index:
    try:
        return INDEX_REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown index {key!r}; registered: {sorted(INDEX_REGISTRY)}") from None

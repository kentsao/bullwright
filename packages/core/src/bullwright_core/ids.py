"""ULID-based identifiers: sortable, collision-free without coordination.

Prefixes are the id's type tag (docs/API.md §1): rep_, tkr_, agt_, key_,
run_, evt_, job_, bt_, wp_, req_.
"""

from ulid import ULID

PREFIXES = frozenset(
    {"rep", "tkr", "agt", "key", "run", "evt", "job", "bt", "wp", "req", "sub", "chk"}
)


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix!r}")
    return f"{prefix}_{ULID()}"

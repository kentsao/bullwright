"""Bullwright persistence layer. Written to ONLY by apps/api and
apps/worker (docs/ARCHITECTURE.md §2)."""

from bullwright_db.engine import make_engine, make_session_factory, session_scope
from bullwright_db.models import Base

__all__ = ["Base", "make_engine", "make_session_factory", "session_scope"]

"""Engine/session factory. BW_DB_URL decides the backend (12-factor)."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "sqlite:///data/bullwright.db"


def db_url() -> str:
    return os.environ.get("BW_DB_URL", DEFAULT_URL)


def make_engine(url: str | None = None) -> Engine:
    url = url or db_url()
    engine = create_engine(url, future=True)
    if url.startswith("sqlite"):
        # WAL + enforced FKs make dev-SQLite behave like a grown-up DB.
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

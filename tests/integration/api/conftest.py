"""Fixtures for API contract/security tests.

DB matrix: SQLite in-memory by default; set BW_TEST_DB_URL (CI does, to a
Postgres service) to run the identical suite against Postgres.
"""

import os
from collections.abc import Iterator
from typing import Any

import pytest
from bullwright_api.app import create_app
from bullwright_api.auth.keys import mint_key
from bullwright_api.auth.ratelimit import limiter
from bullwright_core.ids import new_id
from bullwright_db import Base, make_engine, make_session_factory, session_scope
from bullwright_db.models import Agent, Ticker
from fastapi.testclient import TestClient


@pytest.fixture()
def engine():  # type: ignore[no-untyped-def]
    url = os.environ.get("BW_TEST_DB_URL") or "sqlite://"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def client(engine) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    limiter.reset()
    with TestClient(create_app(engine), raise_server_exceptions=False) as c:
        yield c


def _mint(engine, name: str, kind: str, scopes: list[str]) -> str:  # type: ignore[no-untyped-def]
    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        agent = Agent(agent_id=new_id("agt"), name=name, kind=kind, default_model="test-model")
        s.add(agent)
        s.flush()
        plaintext, _ = mint_key(s, agent, scopes, env="test")
    return plaintext


@pytest.fixture()
def agent_key(engine) -> str:  # type: ignore[no-untyped-def]
    return _mint(engine, "agent-a", "cloud", ["reports:write", "reports:read", "search:read"])


@pytest.fixture()
def agent_b_key(engine) -> str:  # type: ignore[no-untyped-def]
    return _mint(engine, "agent-b", "cloud", ["reports:write", "reports:read"])


@pytest.fixture()
def admin_key(engine) -> str:  # type: ignore[no-untyped-def]
    return _mint(engine, "operator", "human", ["admin"])


@pytest.fixture()
def nvda(engine) -> str:  # type: ignore[no-untyped-def]
    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        s.add(Ticker(ticker_id=new_id("tkr"), symbol="NVDA", exchange="NASDAQ", sector="semis"))
    return "NVDA"


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def flash_payload(ticker: str = "NVDA") -> dict[str, Any]:
    return {
        "ticker": ticker,
        "report_type": "news_flash",
        "title": "Datacenter order surge reported",
        "verdict": {
            "rating": "buy",
            "confidence": 0.6,
            "horizon_days": 90,
            "one_liner": "Demand signal strengthens the thesis.",
        },
        "body": {
            "event": "A major cloud provider disclosed a large order on 2026-07-10.",
            "impact": "Supports the datacenter growth thesis into the next two quarters.",
            "urgency": "medium",
        },
        "provenance": [{"kind": "url", "ref": "https://example.com/news/1"}],
        "tags": ["semis"],
    }

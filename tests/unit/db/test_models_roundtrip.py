"""Schema sanity: create all tables on in-memory SQLite, round-trip the
core entities, exercise FK enforcement and JSON columns."""

import pytest
from bullwright_core.ids import new_id
from bullwright_db import Base, make_engine, make_session_factory, session_scope
from bullwright_db.models import Agent, ApiKey, AuditEvent, Report, Ticker
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@pytest.fixture()
def factory():  # type: ignore[no-untyped-def]
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def test_report_roundtrip_with_json_fields(factory) -> None:  # type: ignore[no-untyped-def]
    agent_id, ticker_id, report_id = new_id("agt"), new_id("tkr"), new_id("rep")
    with session_scope(factory) as s:
        s.add(Agent(agent_id=agent_id, name="claude", kind="cloud"))
        s.add(Ticker(ticker_id=ticker_id, symbol="NVDA", exchange="NASDAQ"))
        # No ORM relationships (by design — thin models), so parents must be
        # flushed before children referencing them by raw FK.
        s.flush()
        s.add(
            Report(
                report_id=report_id,
                ticker_id=ticker_id,
                report_type="news_flash",
                title="A headline",
                author_agent_id=agent_id,
                body={"event": "x", "impact": "y", "urgency": "low"},
                tags=["semis", "ai-capex"],
                verdict={"rating": "buy", "confidence": 0.7},
                content_hash="sha256:abc",
            )
        )
    with session_scope(factory) as s:
        r = s.scalars(select(Report)).one()
        assert r.status == "draft"
        assert r.tags == ["semis", "ai-capex"]
        assert r.verdict is not None and r.verdict["rating"] == "buy"
        assert r.created_at is not None


def test_foreign_keys_enforced_on_sqlite(factory) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(IntegrityError), session_scope(factory) as s:
        s.add(
            Report(
                report_id=new_id("rep"),
                ticker_id="tkr_does_not_exist",
                report_type="news_flash",
                title="Orphan",
                author_agent_id="agt_ghost",
                body={},
                content_hash="sha256:x",
            )
        )


def test_scopes_json_and_unique_agent_name(factory) -> None:  # type: ignore[no-untyped-def]
    agent_id = new_id("agt")
    with session_scope(factory) as s:
        s.add(Agent(agent_id=agent_id, name="gemma-local", kind="local"))
        s.add(
            ApiKey(
                key_id=new_id("key"),
                agent_id=agent_id,
                key_prefix="bw_live_ab12",
                key_hash="argon2id$...",
                scopes=["reports:write", "search:read"],
            )
        )
    with session_scope(factory) as s:
        k = s.scalars(select(ApiKey)).one()
        assert k.scopes == ["reports:write", "search:read"]
    with pytest.raises(IntegrityError), session_scope(factory) as s:
        s.add(Agent(agent_id=new_id("agt"), name="gemma-local", kind="local"))


def test_audit_event_defaults(factory) -> None:  # type: ignore[no-untyped-def]
    with session_scope(factory) as s:
        s.add(
            AuditEvent(
                event_id=new_id("evt"),
                actor_kind="system",
                action="test.event",
                payload={"k": "v"},
            )
        )
    with session_scope(factory) as s:
        e = s.scalars(select(AuditEvent)).one()
        assert e.at is not None and e.payload == {"k": "v"}

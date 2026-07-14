"""End-to-end RAG pipeline: submit -> worker embeds -> /v1/search cites.
Uses FakeEmbedder (word-overlap vectors) so ranking assertions are real
but no Ollama is needed. The live-model eval is tests/integration/rag/
LIVE_EVAL.md."""

import pytest
from bullwright_api.app import create_app
from bullwright_rag import FakeEmbedder
from bullwright_worker.cli import build_runner
from fastapi.testclient import TestClient

from tests.integration.api.conftest import auth, flash_payload

pytestmark = pytest.mark.integration


@pytest.fixture()
def rag_client(engine):  # type: ignore[no-untyped-def]
    from bullwright_api.auth.ratelimit import limiter

    limiter.reset()
    with TestClient(
        create_app(engine, embedder=FakeEmbedder()), raise_server_exceptions=False
    ) as c:
        yield c


def _submit(client, key, title: str, event: str, impact: str) -> str:  # type: ignore[no-untyped-def]
    payload = flash_payload()
    payload["title"] = title
    payload["body"]["event"] = event
    payload["body"]["impact"] = impact
    r = client.post("/v1/reports", json=payload, headers=auth(key))
    assert r.status_code == 201, r.text
    rid: str = r.json()["report_id"]
    assert client.post(f"/v1/reports/{rid}/submit", headers=auth(key)).status_code == 200
    return rid


def test_submit_embed_search_cycle(rag_client, engine, agent_key, nvda) -> None:  # type: ignore[no-untyped-def]
    rid_gpu = _submit(
        rag_client,
        agent_key,
        "Datacenter capacity expansion announced",
        "The company announced a massive datacenter gpu cluster expansion in Texas.",
        "More gpu capacity supports training demand through next year.",
    )
    rid_div = _submit(
        rag_client,
        agent_key,
        "Dividend policy update",
        "The board approved a dividend increase and a new buyback program.",
        "Capital return signals confidence in free cash flow durability.",
    )

    runner = build_runner(engine=engine, embedder=FakeEmbedder())
    processed = 0
    while runner.run_once():
        processed += 1
    assert processed >= 2  # two embed_report jobs

    r = rag_client.get("/v1/search?q=gpu datacenter capacity", headers=auth(agent_key))
    assert r.status_code == 200, r.text
    hits = r.json()["hits"]
    assert hits, "expected search hits"
    assert hits[0]["report_id"] == rid_gpu
    assert "#" in hits[0]["citation"]

    r = rag_client.get("/v1/search?q=dividend buyback capital return", headers=auth(agent_key))
    assert r.json()["hits"][0]["report_id"] == rid_div


def test_search_scope_required(rag_client, agent_b_key) -> None:  # type: ignore[no-untyped-def]
    # agent B has no search:read
    r = rag_client.get("/v1/search?q=anything", headers=auth(agent_b_key))
    assert r.status_code == 403


def test_search_503_when_embedder_down(engine, agent_key) -> None:  # type: ignore[no-untyped-def]
    from bullwright_api.auth.ratelimit import limiter
    from bullwright_rag import OllamaEmbedder

    limiter.reset()
    dead = OllamaEmbedder(url="http://127.0.0.1:1")  # nothing listens
    with TestClient(create_app(engine, embedder=dead), raise_server_exceptions=False) as c:
        r = c.get("/v1/search?q=anything at all", headers=auth(agent_key))
        assert r.status_code == 503
        assert "Retry-After" in r.headers


def test_failed_job_retries_then_fails(engine, rag_client, agent_key, nvda) -> None:  # type: ignore[no-untyped-def]
    """Worker resilience: a handler that always raises exhausts attempts
    and lands in failed (visible on /ops/jobs), never crashes the loop."""
    from bullwright_db import make_session_factory, session_scope
    from bullwright_db.models import Job
    from bullwright_worker.runner import JobRunner
    from sqlalchemy import select

    factory = make_session_factory(engine)
    from bullwright_core.ids import new_id

    with session_scope(factory) as s:
        s.add(Job(job_id=new_id("job"), kind="explodes", payload={}, max_attempts=2))

    def boom(session, payload):  # type: ignore[no-untyped-def]
        raise RuntimeError("kaboom")

    runner = JobRunner(engine, handlers={"explodes": boom})
    while runner.run_once():
        pass
    with session_scope(factory) as s:
        job = s.scalars(select(Job).where(Job.kind == "explodes")).one()
        assert job.status == "failed"
        assert job.attempts == 2
        assert "kaboom" in (job.error or "")

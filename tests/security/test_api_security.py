"""Security rules S1-S10 (docs/API.md §6) — one named test per rule.
S9 (Stripe webhook) is deferred with billing (ADR-0001)."""

import time

import pytest
from bullwright_api.auth.keys import mint_key
from bullwright_db import make_session_factory, session_scope
from bullwright_db.models import Agent, ApiKey, AuditEvent
from sqlalchemy import select

from tests.integration.api.conftest import auth, flash_payload

pytestmark = [pytest.mark.integration, pytest.mark.security]


def test_s1_all_endpoints_require_auth(client) -> None:  # type: ignore[no-untyped-def]
    endpoints = [
        ("GET", "/v1/reports"),
        ("POST", "/v1/reports"),
        ("GET", "/v1/reports/rep_x"),
        ("PATCH", "/v1/reports/rep_x"),
        ("POST", "/v1/reports/rep_x/submit"),
        ("POST", "/v1/reports/rep_x/publish"),
        ("GET", "/v1/tickers"),
        ("POST", "/v1/tickers"),
        ("POST", "/v1/agent-runs"),
    ]
    for method, path in endpoints:
        r = client.request(method, path)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
        assert r.headers.get("WWW-Authenticate") == "Bearer"
    # health/version stay open
    assert client.get("/v1/healthz").status_code == 200
    assert client.get("/v1/version").status_code == 200


def test_s2_scope_violation_names_missing_scope(client, agent_key) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/v1/tickers", headers=auth(agent_key))  # needs market:read
    assert r.status_code == 403
    assert "market:read" in r.json()["title"]


def test_s3_cross_agent_draft_isolation(client, agent_key, agent_b_key, nvda) -> None:  # type: ignore[no-untyped-def]
    rid = client.post("/v1/reports", json=flash_payload(), headers=auth(agent_key)).json()[
        "report_id"
    ]
    # B sees 404 (not 403) on read, patch, submit — existence not leaked.
    assert client.get(f"/v1/reports/{rid}", headers=auth(agent_b_key)).status_code == 404
    assert (
        client.patch(
            f"/v1/reports/{rid}", json={"title": "hijacked title"}, headers=auth(agent_b_key)
        ).status_code
        == 404
    )
    assert client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_b_key)).status_code == 404
    # And B's list doesn't include A's draft.
    listed = client.get("/v1/reports", headers=auth(agent_b_key)).json()["items"]
    assert rid not in {i["report_id"] for i in listed}


def test_s4_size_limits(client, agent_key, nvda, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # 413: whole request too large (Content-Length gate)
    r = client.post(
        "/v1/reports",
        content=b"x" * 2_000_000,
        headers={
            **auth(agent_key),
            "Content-Type": "application/json",
            "Content-Length": "2000000",
        },
    )
    assert r.status_code == 413
    # 422: report body over its own limit
    payload = flash_payload()
    payload["body"]["event"] = "A" * 300_000
    r = client.post("/v1/reports", json=payload, headers=auth(agent_key))
    assert r.status_code in (413, 422)


def test_s5_html_rejected_everywhere(client, agent_key, nvda) -> None:  # type: ignore[no-untyped-def]
    probes = [
        ("title", "hello <script>alert(1)</script>"),
        ("body.event", "<img src=x onerror=alert(1)> happened today"),
        ("verdict.one_liner", "look <iframe src=//evil.com></iframe>"),
    ]
    for loc, value in probes:
        payload = flash_payload()
        if loc == "title":
            payload["title"] = value
        elif loc == "body.event":
            payload["body"]["event"] = value
        else:
            payload["verdict"]["one_liner"] = value
        r = client.post("/v1/reports", json=payload, headers=auth(agent_key))
        assert r.status_code == 422, f"{loc} accepted HTML"


def test_s6_rate_limit_per_key(client, engine, agent_key, agent_b_key, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("BW_RATE_LIMIT_READS_PER_MIN", "3")
    from bullwright_api.settings import settings

    settings.cache_clear()
    try:
        codes = [client.get("/v1/reports", headers=auth(agent_key)).status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
        limited = client.get("/v1/reports", headers=auth(agent_key))
        assert limited.status_code == 429 and "Retry-After" in limited.headers
        # per-key, not global: agent B is unaffected
        assert client.get("/v1/reports", headers=auth(agent_b_key)).status_code == 200
    finally:
        settings.cache_clear()


def test_s7_revocation_effective_immediately(client, engine, agent_key) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/v1/reports", headers=auth(agent_key)).status_code == 200
    factory = make_session_factory(engine)
    from datetime import UTC, datetime

    with session_scope(factory) as s:
        for row in s.scalars(select(ApiKey)).all():
            row.revoked_at = datetime.now(UTC)
    start = time.monotonic()
    r = client.get("/v1/reports", headers=auth(agent_key))
    assert r.status_code == 401
    assert time.monotonic() - start < 5


def test_s8_injection_probes_never_500(client, agent_key, nvda) -> None:  # type: ignore[no-untyped-def]
    probes = [
        "' OR 1=1 --",
        '"; DROP TABLE reports; --',
        "../../etc/passwd",
        "%00",
        "\x00null",
        "𝕏" * 200,  # noqa: RUF001 — non-ASCII abuse probe
    ]
    for p in probes:
        if "\x00" not in p:  # the HTTP client itself refuses raw NUL in URLs
            for path in (f"/v1/reports/{p}", f"/v1/tickers/{p}", f"/v1/reports?ticker={p}"):
                r = client.get(path, headers=auth(agent_key))
                assert r.status_code < 500, f"{path!r} -> {r.status_code}"
        # and in bodies
        payload = flash_payload()
        payload["title"] = f"probe {p}"[:100]
        r = client.post("/v1/reports", json=payload, headers=auth(agent_key))
        assert r.status_code < 500


def test_s10_audit_trail_written(client, engine, agent_key, admin_key, nvda) -> None:  # type: ignore[no-untyped-def]
    rid = client.post("/v1/reports", json=flash_payload(), headers=auth(agent_key)).json()[
        "report_id"
    ]
    client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_key))
    client.post(f"/v1/reports/{rid}/approve", headers=auth(admin_key))
    client.get("/v1/reports", headers={"Authorization": "Bearer bw_test_invalidinvalid"})

    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        actions = [e.action for e in s.scalars(select(AuditEvent)).all()]
        payloads = [e.payload for e in s.scalars(select(AuditEvent)).all()]
    for expected in ("report.create", "report.submit", "report.approve", "auth.denied"):
        assert expected in actions
    # never the full key — prefix only
    for p in payloads:
        assert "bw_test_invalidinvalid" not in str(p)


def test_a1_agents_cannot_be_minted_admin_keys(engine) -> None:  # type: ignore[no-untyped-def]
    from bullwright_core.ids import new_id

    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        rogue = Agent(agent_id=new_id("agt"), name="rogue", kind="cloud")
        s.add(rogue)
        s.flush()
        with pytest.raises(ValueError, match="A1"):
            mint_key(s, rogue, ["admin"])

"""Ops dashboard: renders in dev, absent outside dev, read-only."""

import pytest
from bullwright_api.settings import settings

from tests.integration.api.conftest import auth, flash_payload

pytestmark = pytest.mark.integration

PAGES = ["/ops", "/ops/queue", "/ops/jobs", "/ops/runs", "/ops/audit"]


def test_dashboard_renders_all_pages(client, agent_key, nvda) -> None:  # type: ignore[no-untyped-def]
    rid = client.post("/v1/reports", json=flash_payload(), headers=auth(agent_key)).json()[
        "report_id"
    ]
    client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_key))

    for page in PAGES:
        r = client.get(page)
        assert r.status_code == 200, page
        assert "bw ops" in r.text
    # the submitted report shows in the review queue
    assert rid in client.get("/ops/queue").text
    # and the audit tail saw the submit
    assert "report.submit" in client.get("/ops/audit").text


def test_dashboard_absent_outside_dev(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from bullwright_api.app import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("BW_ENV", "prod")
    settings.cache_clear()
    try:
        with TestClient(create_app(engine)) as c:
            for page in PAGES:
                assert c.get(page).status_code == 404, page
    finally:
        settings.cache_clear()


def test_dashboard_hostile_content_is_escaped(client, agent_key, nvda) -> None:  # type: ignore[no-untyped-def]
    payload = flash_payload()
    # HTML is rejected at ingest, so simulate hostile-ish text that passes:
    payload["title"] = "quotes ' and \" and & ampersands < 5"
    rid = client.post("/v1/reports", json=payload, headers=auth(agent_key)).json()["report_id"]
    client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_key))
    page = client.get("/ops/queue").text
    assert "&amp; ampersands" in page and "&lt; 5" in page

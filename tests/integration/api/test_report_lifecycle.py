"""Contract tests: report CRUD + full lifecycle matrix (TEST_PLAN §2)."""

from typing import Any

import pytest

from tests.integration.api.conftest import auth, flash_payload

pytestmark = pytest.mark.integration


def _create(client, key, **over: object) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    payload = flash_payload()
    payload.update(over)
    r = client.post("/v1/reports", json=payload, headers=auth(key))
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_golden_path_draft_to_published(client, agent_key, admin_key, nvda):  # type: ignore[no-untyped-def]
    rep = _create(client, agent_key)
    rid = rep["report_id"]
    assert rep["status"] == "draft"
    assert rep["author"]["model"] == "test-model"

    assert client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_key)).status_code == 200
    assert client.post(f"/v1/reports/{rid}/approve", headers=auth(admin_key)).status_code == 200
    r = client.post(f"/v1/reports/{rid}/publish", headers=auth(admin_key))
    assert r.status_code == 200
    assert r.json()["status"] == "published"
    assert r.json()["published_at"] is not None


def test_reject_requires_reason_and_is_terminal(client, agent_key, admin_key, nvda):  # type: ignore[no-untyped-def]
    rid = _create(client, agent_key)["report_id"]
    client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_key))
    assert (
        client.post(f"/v1/reports/{rid}/reject", json={}, headers=auth(admin_key)).status_code
        == 422
    )
    r = client.post(
        f"/v1/reports/{rid}/reject", json={"reason": "sources too thin"}, headers=auth(admin_key)
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # Terminal: no action moves it again.
    for action in ("submit", "approve", "publish"):
        key = agent_key if action == "submit" else admin_key
        assert client.post(f"/v1/reports/{rid}/{action}", headers=auth(key)).status_code == 409


@pytest.mark.parametrize(
    ("action", "from_key"),
    [("approve", "agent"), ("publish", "agent"), ("reject", "agent")],
)
def test_a2_agent_cannot_admin_transition(client, agent_key, admin_key, nvda, action, from_key):  # type: ignore[no-untyped-def]
    rid = _create(client, agent_key)["report_id"]
    client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_key))
    body = {"reason": "x"} if action == "reject" else None
    r = client.post(f"/v1/reports/{rid}/{action}", json=body, headers=auth(agent_key))
    assert r.status_code == 403
    assert "admin" in r.json()["title"]


def test_submit_requires_verdict_and_provenance(client, agent_key, nvda):  # type: ignore[no-untyped-def]
    rep = _create(client, agent_key, verdict=None, provenance=[])
    r = client.post(f"/v1/reports/{rep['report_id']}/submit", headers=auth(agent_key))
    assert r.status_code == 422
    locs = {e["loc"] for e in r.json()["errors"]}
    assert locs == {"verdict", "provenance"}


def test_revise_cycle(client, agent_key, nvda):  # type: ignore[no-untyped-def]
    rid = _create(client, agent_key)["report_id"]
    client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_key))
    r = client.post(f"/v1/reports/{rid}/revise", headers=auth(agent_key))
    assert r.status_code == 200 and r.json()["status"] == "draft"


def test_patch_own_draft_and_immutability_after_publish(client, agent_key, admin_key, nvda):  # type: ignore[no-untyped-def]
    rid = _create(client, agent_key)["report_id"]
    r = client.patch(
        f"/v1/reports/{rid}", json={"title": "Updated headline title"}, headers=auth(agent_key)
    )
    assert r.status_code == 200 and r.json()["title"] == "Updated headline title"
    # Unknown patch field
    assert (
        client.patch(
            f"/v1/reports/{rid}", json={"status": "published"}, headers=auth(agent_key)
        ).status_code
        == 422
    )
    client.post(f"/v1/reports/{rid}/submit", headers=auth(agent_key))
    client.post(f"/v1/reports/{rid}/approve", headers=auth(admin_key))
    client.post(f"/v1/reports/{rid}/publish", headers=auth(admin_key))
    assert (
        client.patch(
            f"/v1/reports/{rid}", json={"title": "Sneaky edit attempt"}, headers=auth(admin_key)
        ).status_code
        == 409
    )


def test_validation_mutations(client, agent_key, nvda):  # type: ignore[no-untyped-def]
    cases: list[tuple[dict[str, Any], str]] = [
        ({"report_type": "meme_analysis"}, "report_type"),
        ({"body": {}}, "body"),
        (
            {
                "verdict": {
                    "rating": "yolo",
                    "confidence": 0.5,
                    "horizon_days": 30,
                    "one_liner": "x",
                }
            },
            "verdict",
        ),
        ({"unknown_top_level": True}, "unknown"),
        ({"ticker": "ZZZZ"}, "ticker"),
    ]
    for override, _hint in cases:
        payload = flash_payload()
        payload.update(override)
        r = client.post("/v1/reports", json=payload, headers=auth(agent_key))
        assert r.status_code == 422, f"{override} -> {r.status_code}"
        assert r.json()["type"].endswith("/validation")


def test_thesis_update_requires_supersedes(client, agent_key, nvda):  # type: ignore[no-untyped-def]
    payload = flash_payload()
    payload["report_type"] = "thesis_update"
    payload["body"] = {
        "what_changed": "New export-control guidance materially widens the addressable market.",
        "prior_view": "We assumed a hard cap on shipments to key regions.",
        "new_view": "Caps look softer; raising the demand outlook for the next two quarters.",
    }
    r = client.post("/v1/reports", json=payload, headers=auth(agent_key))
    assert r.status_code == 422
    assert any(e["loc"] == "supersedes" for e in r.json()["errors"])


def test_idempotency_replay_and_conflict(client, agent_key, nvda):  # type: ignore[no-untyped-def]
    headers = {**auth(agent_key), "Idempotency-Key": "idem-123"}
    r1 = client.post("/v1/reports", json=flash_payload(), headers=headers)
    r2 = client.post("/v1/reports", json=flash_payload(), headers=headers)
    assert r1.status_code == 201
    assert r2.json()["report_id"] == r1.json()["report_id"]
    # same key, different body -> 409
    other = flash_payload()
    other["title"] = "A different report entirely"
    assert client.post("/v1/reports", json=other, headers=headers).status_code == 409


def test_list_pagination_and_filters(client, agent_key, nvda):  # type: ignore[no-untyped-def]
    ids = [_create(client, agent_key)["report_id"] for _ in range(5)]
    page1 = client.get("/v1/reports?limit=2", headers=auth(agent_key)).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = client.get(
        f"/v1/reports?limit=2&cursor={page1['next_cursor']}", headers=auth(agent_key)
    ).json()
    ids1 = {i["report_id"] for i in page1["items"]}
    ids2 = {i["report_id"] for i in page2["items"]}
    assert not ids1 & ids2 and ids1 | ids2 < set(ids) | ids1 | ids2
    filtered = client.get("/v1/reports?status=draft&ticker=NVDA", headers=auth(agent_key)).json()
    assert len(filtered["items"]) == 5

"""bw-agent client + CLI against the real app (in-process ASGI transport):
contract drift between client and API fails here first."""

import json

import pytest
from bullwright_api.app import create_app
from bullwright_client import ApiError, BullwrightClient
from bullwright_client.cli import app as cli_app
from bullwright_rag import FakeEmbedder
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from tests.integration.api.conftest import flash_payload

pytestmark = pytest.mark.integration

runner = CliRunner()


@pytest.fixture()
def client_for(engine):  # type: ignore[no-untyped-def]
    from bullwright_api.auth.ratelimit import limiter

    limiter.reset()
    asgi_app = create_app(engine, embedder=FakeEmbedder())
    # TestClient's transport drives ASGI synchronously — exactly what the
    # sync BullwrightClient needs to hit the real app in-process.
    tc = TestClient(asgi_app)
    transport = tc._transport

    def make(key: str) -> BullwrightClient:
        return BullwrightClient(base_url="http://testserver/v1", api_key=key, transport=transport)

    yield make
    tc.close()


def test_run_and_report_roundtrip(client_for, agent_key, nvda) -> None:  # type: ignore[no-untyped-def]
    c = client_for(agent_key)
    run = c.start_run("deep_dive:NVDA")
    assert run["run_id"].startswith("run_")

    envelope = flash_payload()
    envelope["agent_run_id"] = run["run_id"]
    report = c.create_report(envelope)
    assert report["status"] == "draft"

    # idempotency: same envelope -> same report
    again = c.create_report(envelope)
    assert again["report_id"] == report["report_id"]

    submitted = c.submit_report(report["report_id"])
    assert submitted["status"] == "submitted"

    done = c.finish_run(run["run_id"], "succeeded", summary="one flash uploaded")
    assert done["status"] == "succeeded"


def test_api_error_carries_problem(client_for, agent_key, nvda) -> None:  # type: ignore[no-untyped-def]
    c = client_for(agent_key)
    bad = flash_payload()
    bad["body"] = {}
    with pytest.raises(ApiError) as exc:
        c.create_report(bad)
    assert exc.value.status == 422
    assert exc.value.problem["errors"]


def test_cli_validate_offline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    good = tmp_path / "good.json"
    good.write_text(json.dumps(flash_payload()))
    result = runner.invoke(cli_app, ["report", "validate", "--file", str(good)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["valid"] is True

    bad = tmp_path / "bad.json"
    payload = flash_payload()
    payload["body"]["urgency"] = "apocalyptic"
    payload["hallucinated"] = 1
    bad.write_text(json.dumps(payload))
    result = runner.invoke(cli_app, ["report", "validate", "--file", str(bad)])
    assert result.exit_code == 1
    parsed = json.loads(result.output)
    assert parsed["valid"] is False and parsed["errors"]


def test_cli_json_error_when_api_unreachable(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("BW_API_URL", "http://127.0.0.1:1/v1")  # nothing listens
    monkeypatch.setenv("BW_API_KEY", "bw_test_x")
    result = runner.invoke(cli_app, ["ping"])
    assert result.exit_code == 1
    parsed = json.loads(result.output)
    assert parsed["error"] is True and "connection failed" in parsed["title"]


def test_cli_create_dry_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "draft.json"
    f.write_text(json.dumps(flash_payload()))
    result = runner.invoke(cli_app, ["report", "create", "--file", str(f), "--dry-run"])
    assert result.exit_code == 0
    assert json.loads(result.output)["dry_run"] is True

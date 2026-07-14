"""bw-agent — the CLI agents shell out to (docs/AGENT_SKILLS.md §2).

Contract: every command prints JSON to stdout; failures exit nonzero with
a JSON error on stdout too, so agent loops can parse either way. Reads
BW_API_URL / BW_API_KEY from the environment — skills never embed either.
"""

import json
from pathlib import Path
from typing import Any

import typer
from bullwright_core.envelope import ReportCreate
from bullwright_core.report_types import BodyValidationError, validate_body

from bullwright_client.client import ApiError, BullwrightClient

app = typer.Typer(name="bw-agent", no_args_is_help=True, add_completion=False)
run_app = typer.Typer(no_args_is_help=True)
report_app = typer.Typer(no_args_is_help=True)
app.add_typer(run_app, name="run", help="Agent work-session tracking")
app.add_typer(report_app, name="report", help="Create/validate/submit reports")


def _out(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


def _fail(error: ApiError | str) -> None:
    if isinstance(error, ApiError):
        _out({"error": True, "status": error.status, **error.problem})
    else:
        _out({"error": True, "title": str(error)})
    raise typer.Exit(1)


@run_app.command("start")
def run_start(task: str = typer.Option(...), input_digest: str | None = None) -> None:
    try:
        _out(BullwrightClient().start_run(task, input_digest))
    except ApiError as e:
        _fail(e)


@run_app.command("finish")
def run_finish(
    run_id: str,
    status: str = typer.Option(..., help="succeeded | failed | abandoned"),
    summary: str | None = typer.Option(None),
    tokens_used: int | None = typer.Option(None),
) -> None:
    try:
        _out(BullwrightClient().finish_run(run_id, status, summary, tokens_used))
    except ApiError as e:
        _fail(e)


def _load_envelope(file: Path) -> dict[str, Any]:
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _fail(f"cannot read {file}: {e}")
    if not isinstance(data, dict):
        _fail(f"{file} must contain a JSON object")
    return data  # type: ignore[no-any-return]


def _validate_offline(data: dict[str, Any]) -> list[dict[str, str]]:
    """Local validation: strict envelope model + body schema. Cheap failure
    beats a 422 round-trip (skill authoring rule 3)."""
    errors: list[dict[str, str]] = []
    try:
        envelope = ReportCreate.model_validate(data)
    except Exception as e:  # pydantic ValidationError
        for err in getattr(e, "errors", lambda: [])():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            errors.append({"loc": loc or "envelope", "msg": str(err.get("msg", e))})
        if not errors:
            errors.append({"loc": "envelope", "msg": str(e)})
        return errors
    try:
        validate_body(envelope.report_type.value, envelope.body)
    except BodyValidationError as e:
        errors.extend({"loc": loc, "msg": msg} for loc, msg in e.errors)
    if not envelope.ticker_or_sector_ok():
        errors.append({"loc": "ticker", "msg": "ticker required (or sector for sector_overview)"})
    return errors


@report_app.command("validate")
def report_validate(file: Path = typer.Option(..., exists=True)) -> None:
    """Offline validation — no API call, no key needed."""
    errors = _validate_offline(_load_envelope(file))
    if errors:
        _out({"valid": False, "errors": errors})
        raise typer.Exit(1)
    _out({"valid": True})


@report_app.command("create")
def report_create(
    file: Path = typer.Option(..., exists=True),
    run: str | None = typer.Option(None, help="agent_run id to thread into the audit trail"),
    dry_run: bool = typer.Option(False, "--dry-run", help="validate only, do not upload"),
) -> None:
    data = _load_envelope(file)
    if run:
        data["agent_run_id"] = run
    errors = _validate_offline(data)
    if errors:
        _out({"valid": False, "errors": errors})
        raise typer.Exit(1)
    if dry_run:
        _out({"valid": True, "dry_run": True})
        return
    try:
        _out(BullwrightClient().create_report(data))
    except ApiError as e:
        _fail(e)


@report_app.command("get")
def report_get(report_id: str) -> None:
    try:
        _out(BullwrightClient().get_report(report_id))
    except ApiError as e:
        _fail(e)


@report_app.command("submit")
def report_submit(report_id: str) -> None:
    try:
        _out(BullwrightClient().submit_report(report_id))
    except ApiError as e:
        _fail(e)


@app.command()
def search(
    query: str,
    ticker: str | None = typer.Option(None),
    k: int = typer.Option(8, min=1, max=20),
) -> None:
    try:
        _out(BullwrightClient().search(query, ticker=ticker, k=k))
    except ApiError as e:
        _fail(e)


@app.command()
def tickers() -> None:
    try:
        _out(BullwrightClient().list_tickers())
    except ApiError as e:
        _fail(e)


@app.command()
def ping() -> None:
    """Check connectivity + auth in one shot."""
    try:
        _out(BullwrightClient().version())
    except ApiError as e:
        _fail(e)


if __name__ == "__main__":
    app()


def main() -> None:  # console-script alias used in tests
    app()

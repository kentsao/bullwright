"""bw-harness — run local-model loops unattended.

bw-harness run news_sweep --input data/inbox/news/2026-07-11.json
bw-harness resume news_sweep
"""

import json
import os
from pathlib import Path

import typer
from bullwright_client import BullwrightClient

from bullwright_harness.loops import LoopManager, load_loops
from bullwright_harness.model import OllamaModelClient
from bullwright_harness.runner import TaskRunner
from bullwright_harness.tools import build_registry

app = typer.Typer(name="bw-harness", no_args_is_help=True, add_completion=False)

DEFAULT_TASKS = Path(__file__).parents[2] / "tasks.yaml"
DEFAULT_STATE = Path(os.environ.get("BW_HARNESS_STATE", "data/harness"))


def _manager(state_dir: Path) -> LoopManager:
    client = BullwrightClient()
    runner = TaskRunner(OllamaModelClient(), build_registry(client), client, state_dir)
    return LoopManager(runner, state_dir)


@app.command()
def run(
    loop: str,
    input_file: Path = typer.Option(..., "--input", exists=True, help="input JSON/text file"),
    tasks_file: Path = typer.Option(DEFAULT_TASKS, "--tasks"),
    state_dir: Path = typer.Option(DEFAULT_STATE, "--state"),
) -> None:
    """Run one iteration of a loop with the given input."""
    loops = load_loops(tasks_file)
    if loop not in loops:
        typer.echo(
            json.dumps(
                {"error": True, "title": f"unknown loop {loop!r}", "available": sorted(loops)}
            )
        )
        raise typer.Exit(1)
    result = _manager(state_dir).run_iteration(loops[loop], input_file.read_text("utf-8"))
    typer.echo(
        json.dumps(
            {
                "loop": loop,
                "status": result.status,
                "turns": result.turns,
                "reports": result.created_report_ids,
                "summary": result.summary,
            },
            indent=2,
        )
    )
    raise typer.Exit(0 if result.status == "succeeded" else 1)


@app.command()
def resume(loop: str, state_dir: Path = typer.Option(DEFAULT_STATE, "--state")) -> None:
    """Clear a loop's dead-letter pause after fixing the cause (L3)."""
    LoopManager.resume(_manager(state_dir), loop)
    typer.echo(json.dumps({"loop": loop, "resumed": True}))


if __name__ == "__main__":
    app()

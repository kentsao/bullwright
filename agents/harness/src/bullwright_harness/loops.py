"""Loop layer (docs/AGENT_SKILLS.md §4): scheduled tasks with idempotency
(L1), one bounded run per iteration (L2), and dead-lettering (L3).

tasks.yaml declares the loops; this module runs one iteration of one loop.
Scheduling (cron/launchd) is external by design — one less daemon."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bullwright_harness.runner import TaskResult, TaskRunner, TaskSpec

DEAD_LETTER_THRESHOLD = 3


@dataclass(frozen=True)
class LoopDef:
    name: str
    instructions: str
    max_turns: int
    max_seconds: float
    thinking: bool


def load_loops(path: Path) -> dict[str, LoopDef]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    loops = {}
    for name, cfg in (raw.get("loops") or {}).items():
        loops[name] = LoopDef(
            name=name,
            instructions=cfg["instructions"],
            max_turns=int(cfg.get("max_turns", 12)),
            max_seconds=float(cfg.get("max_seconds", 600)),
            thinking=bool(cfg.get("thinking", False)),
        )
    return loops


class LoopManager:
    def __init__(self, runner: TaskRunner, state_dir: Path) -> None:
        self.runner = runner
        self.state_dir = state_dir

    def _loop_state_path(self, loop: str) -> Path:
        d = self.state_dir / loop
        d.mkdir(parents=True, exist_ok=True)
        return d / "loop_state.json"

    def _load(self, loop: str) -> dict[str, Any]:
        p = self._loop_state_path(loop)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        return {"consecutive_failures": 0, "paused": False}

    def _save(self, loop: str, state: dict[str, Any]) -> None:
        self._loop_state_path(loop).write_text(json.dumps(state, indent=1), encoding="utf-8")

    def resume(self, loop: str) -> None:
        state = self._load(loop)
        state.update(consecutive_failures=0, paused=False)
        self._save(loop, state)

    def run_iteration(self, loop_def: LoopDef, input_text: str) -> TaskResult:
        state = self._load(loop_def.name)
        if state["paused"]:
            return TaskResult(
                "failed",
                f"loop {loop_def.name!r} is paused after "
                f"{state['consecutive_failures']} consecutive failures; "
                "run `bw-harness resume` after fixing the cause",
                0,
            )
        # L1: idempotency key = (loop, utc-date, input digest)
        digest = hashlib.sha256(input_text.encode()).hexdigest()[:16]
        run_key = f"{datetime.now(UTC).date().isoformat()}-{digest}"

        spec = TaskSpec(
            name=loop_def.name,
            instructions=loop_def.instructions,
            input_text=input_text,
            max_turns=loop_def.max_turns,
            max_seconds=loop_def.max_seconds,
            thinking=loop_def.thinking,
        )
        result = self.runner.run_task(spec, run_key)

        if result.status == "succeeded":
            state["consecutive_failures"] = 0
        else:
            state["consecutive_failures"] += 1
            if state["consecutive_failures"] >= DEAD_LETTER_THRESHOLD:
                state["paused"] = True  # L3: no infinite retry
        self._save(loop_def.name, state)
        return result

"""Tool whitelist (H1). The model NEVER gets a shell: it sees exactly the
registry below, and the executor re-validates every argument against the
schema before anything runs — model-emitted args are untrusted input.

The registry is deliberately a strict subset of the agent surface:
search, validate, create, submit. No approve/reject/publish exists here
at all — the harness is structurally incapable of publishing (A2/L4).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bullwright_client import ApiError, BullwrightClient
from bullwright_core.envelope import ReportCreate
from bullwright_core.report_types import BodyValidationError, validate_body
from jsonschema import Draft202012Validator

DATA_FENCE_OPEN = "<data untrusted='true'>"
DATA_FENCE_CLOSE = "</data>"


def fence(text: str, limit: int = 16_384) -> str:
    """H5: tool results are data, never instructions; H4: bounded size."""
    truncated = len(text) > limit
    body = text[:limit] + ("\n[truncated=true]" if truncated else "")
    return f"{DATA_FENCE_OPEN}\n{body}\n{DATA_FENCE_CLOSE}"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[[dict[str, Any]], str]

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}
        self._validators = {t.name: Draft202012Validator(t.parameters) for t in tools}

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def run(self, name: str, args: dict[str, Any]) -> str:
        """Execute one whitelisted tool. Any failure returns a fenced
        error string for the model — never an exception, never a shell."""
        tool = self._tools.get(name)
        if tool is None:
            return fence(f"error: tool {name!r} does not exist. Available: {sorted(self._tools)}")
        errors = [
            f"{'.'.join(str(p) for p in e.absolute_path) or 'args'}: {e.message}"
            for e in self._validators[name].iter_errors(args)
        ]
        if errors:
            return fence("error: invalid arguments:\n" + "\n".join(errors))
        try:
            return fence(tool.execute(args))
        except ApiError as e:
            return fence(f"error: api {e.status}: {json.dumps(e.problem)}")
        except Exception as e:
            return fence(f"error: {type(e).__name__}: {e}")


def build_registry(client: BullwrightClient) -> ToolRegistry:
    def do_search(args: dict[str, Any]) -> str:
        result = client.search(args["query"], ticker=args.get("ticker"), k=args.get("k", 6))
        return json.dumps(result["hits"], indent=1)

    def do_validate(args: dict[str, Any]) -> str:
        envelope = args["envelope"]
        try:
            parsed = ReportCreate.model_validate(envelope)
            validate_body(parsed.report_type.value, parsed.body)
            if not parsed.ticker_or_sector_ok():
                return "invalid: ticker required (or sector for sector_overview)"
            return "valid"
        except BodyValidationError as e:
            return "invalid:\n" + "\n".join(f"{loc}: {msg}" for loc, msg in e.errors)
        except Exception as e:  # pydantic
            return f"invalid: {e}"

    def do_create(args: dict[str, Any]) -> str:
        report = client.create_report(args["envelope"])
        return json.dumps({"report_id": report["report_id"], "status": report["status"]})

    def do_submit(args: dict[str, Any]) -> str:
        report = client.submit_report(args["report_id"])
        return json.dumps({"report_id": report["report_id"], "status": report["status"]})

    envelope_schema = {"type": "object", "description": "full report envelope JSON"}
    return ToolRegistry(
        [
            Tool(
                "search_reports",
                "Semantic search over existing Bullwright research. Use before writing.",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 2},
                        "ticker": {"type": ["string", "null"]},
                        "k": {"type": "integer", "minimum": 1, "maximum": 12},
                    },
                },
                do_search,
            ),
            Tool(
                "validate_report",
                "Validate a draft report envelope offline. Always call before create_report.",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["envelope"],
                    "properties": {"envelope": envelope_schema},
                },
                do_validate,
            ),
            Tool(
                "create_report",
                "Upload a validated draft report. Returns its report_id.",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["envelope"],
                    "properties": {"envelope": envelope_schema},
                },
                do_create,
            ),
            Tool(
                "submit_report",
                "Submit your draft for human review. Terminal step for you.",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["report_id"],
                    "properties": {"report_id": {"type": "string", "pattern": "^rep_"}},
                },
                do_submit,
            ),
        ]
    )

"""Report-type body schema registry (docs/API.md §4).

Adding a report type = drop a `<type>.schema.json` file in this directory
(named `<report_type>.schema.json`, draft 2020-12, additionalProperties
false) — the registry discovers it at import time, no code changes.

Every markdown string field is additionally checked for raw HTML (rule S5),
which plain JSON Schema can't express.
"""

import json
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from bullwright_core.html_guard import contains_raw_html


class BodyValidationError(Exception):
    """Carries (json-path, message) pairs for the RFC7807 `errors` array."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} body validation error(s)")


@cache
def registry() -> dict[str, Draft202012Validator]:
    result: dict[str, Draft202012Validator] = {}
    for entry in resources.files(__name__).iterdir():
        if entry.name.endswith(".schema.json"):
            schema = json.loads(entry.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            result[entry.name.removesuffix(".schema.json")] = Draft202012Validator(schema)
    return result


def known_types() -> frozenset[str]:
    return frozenset(registry())


def _walk_strings(value: Any, path: str, errors: list[tuple[str, str]]) -> None:
    if isinstance(value, str) and contains_raw_html(value):
        errors.append((path, "raw HTML is not allowed in markdown fields"))
    elif isinstance(value, dict):
        for k, v in value.items():
            _walk_strings(v, f"{path}.{k}", errors)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _walk_strings(v, f"{path}[{i}]", errors)


def validate_body(report_type: str, body: dict[str, Any]) -> None:
    """Raise BodyValidationError unless `body` is valid for `report_type`."""
    validator = registry().get(report_type)
    if validator is None:
        raise BodyValidationError([("report_type", f"unknown report type {report_type!r}")])
    errors = [
        (
            "body." + ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "body",
            e.message,
        )
        for e in validator.iter_errors(body)
    ]
    _walk_strings(body, "body", errors)
    if errors:
        raise BodyValidationError(errors)

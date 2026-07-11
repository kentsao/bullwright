"""Golden fixtures + mutation suite for report-type body schemas (TEST_PLAN §2)."""

from typing import Any

import pytest
from bullwright_core.report_types import BodyValidationError, known_types, validate_body

LONG = "This section develops the argument in enough detail to pass length gates. " * 8

GOLDEN: dict[str, dict[str, Any]] = {
    "company_deep_dive": {
        "summary": LONG[:500],
        "thesis": LONG,
        "moat": LONG[:600],
        "financial_highlights": LONG[:600],
        "risks": [
            "Customer concentration could unwind quickly in a downturn.",
            "Export controls may cap the addressable market materially.",
        ],
        "valuation": LONG[:600],
        "verdict_rationale": LONG[:300],
    },
    "earnings_review": {
        "fiscal_period": "2026Q2",
        "results_vs_expectations": LONG[:600],
        "guidance": LONG[:300],
        "takeaways": ["Margins troughed a quarter earlier than modeled."],
    },
    "news_flash": {
        "event": "Company announced an acquisition on 2026-07-10 for $2B in cash.",
        "impact": "Accelerates the platform strategy by two years; leverage stays modest.",
        "urgency": "medium",
    },
    "thesis_update": {
        "what_changed": LONG[:300],
        "prior_view": LONG[:200],
        "new_view": LONG[:400],
    },
    "sector_overview": {
        "overview": LONG,
        "themes": ["AI capex is broadening from training to inference workloads."],
        "tickers_mentioned": ["NVDA", "AMD"],
        "outlook": LONG[:400],
    },
}


def test_registry_discovers_all_five_types() -> None:
    assert known_types() == set(GOLDEN)


@pytest.mark.parametrize("rtype", sorted(GOLDEN))
def test_golden_bodies_validate(rtype: str) -> None:
    validate_body(rtype, GOLDEN[rtype])


@pytest.mark.parametrize("rtype", sorted(GOLDEN))
def test_mutation_missing_required_field(rtype: str) -> None:
    body = dict(GOLDEN[rtype])
    body.pop(next(iter(body)))
    with pytest.raises(BodyValidationError):
        validate_body(rtype, body)


@pytest.mark.parametrize("rtype", sorted(GOLDEN))
def test_mutation_unknown_field(rtype: str) -> None:
    with pytest.raises(BodyValidationError):
        validate_body(rtype, {**GOLDEN[rtype], "hallucinated_field": "x"})


def test_html_in_nested_field_rejected_with_path() -> None:
    body = dict(GOLDEN["news_flash"])
    body["impact"] = "Bad news <iframe src='//evil'></iframe> indeed."
    with pytest.raises(BodyValidationError) as exc:
        validate_body("news_flash", body)
    assert any(path == "body.impact" for path, _ in exc.value.errors)


def test_html_in_array_item_rejected() -> None:
    body = dict(GOLDEN["company_deep_dive"])
    body["risks"] = [*body["risks"], "Regulatory risk <script>x()</script> is rising."]
    with pytest.raises(BodyValidationError) as exc:
        validate_body("company_deep_dive", body)
    assert any("risks[2]" in path for path, _ in exc.value.errors)


def test_unknown_report_type() -> None:
    with pytest.raises(BodyValidationError):
        validate_body("meme_analysis", {})


def test_bad_enum_and_pattern() -> None:
    with pytest.raises(BodyValidationError):
        validate_body("news_flash", {**GOLDEN["news_flash"], "urgency": "apocalyptic"})
    with pytest.raises(BodyValidationError):
        validate_body("earnings_review", {**GOLDEN["earnings_review"], "fiscal_period": "Q5-99"})

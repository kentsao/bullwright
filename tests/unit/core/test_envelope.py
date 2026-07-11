import pytest
from bullwright_core.envelope import Rating, ReportCreate, ReportType, Verdict
from bullwright_core.ids import new_id
from pydantic import ValidationError


def make_verdict(**over: object) -> dict[str, object]:
    v: dict[str, object] = {
        "rating": "buy",
        "confidence": 0.7,
        "horizon_days": 180,
        "one_liner": "Durable datacenter demand.",
    }
    v.update(over)
    return v


def test_verdict_bounds() -> None:
    assert Verdict.model_validate(make_verdict()).rating is Rating.BUY
    with pytest.raises(ValidationError):
        Verdict.model_validate(make_verdict(confidence=1.2))
    with pytest.raises(ValidationError):
        Verdict.model_validate(make_verdict(horizon_days=0))
    with pytest.raises(ValidationError):
        Verdict.model_validate(make_verdict(rating="yolo"))


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError, match="hallucinated"):
        Verdict.model_validate(make_verdict(hallucinated="field"))


def test_html_rejected_in_title_and_one_liner() -> None:
    with pytest.raises(ValidationError, match="raw HTML"):
        Verdict.model_validate(make_verdict(one_liner="<script>alert(1)</script>"))
    with pytest.raises(ValidationError, match="raw HTML"):
        ReportCreate.model_validate(
            {
                "ticker": "NVDA",
                "report_type": "news_flash",
                "title": "hello <img src=x onerror=alert(1)>",
                "body": {},
            }
        )


def test_math_less_than_is_not_html() -> None:
    v = Verdict.model_validate(make_verdict(one_liner="P/E < 20 and growth > 15%"))
    assert "<" in v.one_liner


def test_ticker_or_sector_rule() -> None:
    flash = ReportCreate.model_validate(
        {"ticker": "NVDA", "report_type": "news_flash", "title": "A headline", "body": {}}
    )
    assert flash.ticker_or_sector_ok()
    sector = ReportCreate.model_validate(
        {"sector": "semis", "report_type": "sector_overview", "title": "Semis today", "body": {}}
    )
    assert sector.ticker_or_sector_ok()
    assert sector.report_type is ReportType.SECTOR_OVERVIEW
    missing = ReportCreate.model_validate(
        {"report_type": "news_flash", "title": "A headline", "body": {}}
    )
    assert not missing.ticker_or_sector_ok()


def test_ids_are_prefixed_and_sortable() -> None:
    a, b = new_id("rep"), new_id("rep")
    assert a.startswith("rep_") and a != b and a < b
    with pytest.raises(ValueError):
        new_id("nope")

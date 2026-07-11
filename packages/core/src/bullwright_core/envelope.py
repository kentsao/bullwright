"""The report envelope (docs/API.md §4) — Pydantic models shared by the
API, the agent client, and the blog exporter.

`extra="forbid"` everywhere: unknown fields are a 422, catching agent
hallucinations at the boundary instead of silently dropping them.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bullwright_core.html_guard import assert_no_raw_html


class Rating(StrEnum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class ReportType(StrEnum):
    COMPANY_DEEP_DIVE = "company_deep_dive"
    EARNINGS_REVIEW = "earnings_review"
    NEWS_FLASH = "news_flash"
    THESIS_UPDATE = "thesis_update"
    SECTOR_OVERVIEW = "sector_overview"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Verdict(_StrictModel):
    rating: Rating
    confidence: float = Field(ge=0.0, le=1.0)
    horizon_days: int = Field(ge=1, le=1825)
    price_target: float | None = Field(default=None, gt=0)
    one_liner: str = Field(min_length=1, max_length=280)

    @field_validator("one_liner")
    @classmethod
    def _no_html(cls, v: str) -> str:
        assert_no_raw_html("verdict.one_liner", v)
        return v


class ProvenanceKind(StrEnum):
    URL = "url"
    FILING = "filing"
    DATA_SNAPSHOT = "data_snapshot"
    REPORT = "report"


class ProvenanceEntry(_StrictModel):
    kind: ProvenanceKind
    ref: str = Field(min_length=1, max_length=2048)
    accessed_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class AuthorKind(StrEnum):
    AGENT = "agent"
    HUMAN = "human"


class Author(_StrictModel):
    kind: AuthorKind
    name: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=100)


class ReportCreate(_StrictModel):
    """What a client sends to POST /reports. Server fields are absent by
    construction; `author` is derived from the API key, never trusted
    from the payload."""

    ticker: str | None = Field(default=None, min_length=1, max_length=12)
    sector: str | None = Field(default=None, min_length=1, max_length=64)
    report_type: ReportType
    schema_version: str = "1.0"
    title: str = Field(min_length=3, max_length=200)
    verdict: Verdict | None = None
    body: dict[str, Any]
    provenance: list[ProvenanceEntry] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    supersedes: str | None = None
    agent_run_id: str | None = None

    @field_validator("title")
    @classmethod
    def _title_no_html(cls, v: str) -> str:
        assert_no_raw_html("title", v)
        return v

    @field_validator("tags")
    @classmethod
    def _tag_shape(cls, v: list[str]) -> list[str]:
        for t in v:
            if not (1 <= len(t) <= 40) or not t.replace("-", "").replace("_", "").isalnum():
                raise ValueError(f"invalid tag {t!r}: 1-40 chars, alphanumeric/-/_")
        return v

    def ticker_or_sector_ok(self) -> bool:
        """sector_overview attaches to a sector; everything else to a ticker."""
        if self.report_type is ReportType.SECTOR_OVERVIEW:
            return self.sector is not None
        return self.ticker is not None


class Report(ReportCreate):
    """Full envelope as returned by the API."""

    report_id: str
    author: Author
    status: str
    reviewed_by: str | None = None
    review_note: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

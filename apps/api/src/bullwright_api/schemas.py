"""Response models (request models come from bullwright_core.envelope)."""

from datetime import datetime
from typing import Any

from bullwright_db.models import Report, Ticker
from pydantic import BaseModel, ConfigDict, Field


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: str
    ticker: str | None = None
    sector: str | None
    report_type: str
    schema_version: str
    title: str
    author: dict[str, Any]
    status: str
    verdict: dict[str, Any] | None
    body: dict[str, Any]
    provenance: list[Any]
    tags: list[Any]
    supersedes: str | None
    reviewed_by: str | None
    review_note: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: Report, *, ticker_symbol: str | None = None) -> "ReportOut":
        return cls(
            report_id=row.report_id,
            ticker=ticker_symbol,
            sector=row.sector,
            report_type=row.report_type,
            schema_version=row.schema_version,
            title=row.title,
            author={"agent_id": row.author_agent_id, "model": row.author_model},
            status=row.status,
            verdict=row.verdict,
            body=row.body,
            provenance=row.provenance,
            tags=row.tags,
            supersedes=row.supersedes_report_id,
            reviewed_by=row.reviewed_by,
            review_note=row.review_note,
            published_at=row.published_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ReportPage(BaseModel):
    items: list[ReportOut]
    next_cursor: str | None


class TickerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9.\-]+$")
    exchange: str = Field(min_length=1, max_length=12)
    name: str | None = Field(default=None, max_length=200)
    sector: str | None = Field(default=None, max_length=64)
    industry: str | None = Field(default=None, max_length=64)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class TickerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker_id: str
    symbol: str
    exchange: str
    name: str | None
    sector: str | None
    industry: str | None
    currency: str
    is_active: bool

    @classmethod
    def from_row(cls, row: Ticker) -> "TickerOut":
        return cls.model_validate(row)


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=200)
    input_digest: str | None = Field(default=None, max_length=80)


class RunPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(succeeded|failed|abandoned)$")
    summary: str | None = Field(default=None, max_length=4000)
    tokens_used: int | None = Field(default=None, ge=0)


class RunOut(BaseModel):
    run_id: str
    agent_id: str
    task: str
    status: str
    started_at: datetime
    ended_at: datetime | None


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=2000)

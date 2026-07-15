"""SQLAlchemy models for docs/DB_SCHEMA.md (phase-1 tables + dormant billing).

Portability rules (SQLite dev / Postgres cloud, same code):
- JSON columns: sa.JSON with a JSONB variant on Postgres.
- Arrays (scopes, tags): stored as JSON lists, not ARRAY — SQLite has none.
- Timestamps: timezone-aware, UTC, application-supplied (utcnow) so both
  backends behave identically.
Quant tables (index_scores, weight_profiles, ...) land in phase 3.
"""

from datetime import UTC, datetime
from typing import Any

from bullwright_core.status import ReportStatus
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


JSONVariant = JSON().with_variant(JSONB(), "postgresql")

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    # SQLAlchemy's documented customization point; not a shared-state hazard.
    type_annotation_map = {dict[str, Any]: JSONVariant, list[Any]: JSONVariant}  # noqa: RUF012


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # cloud | local | human
    default_model: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (CheckConstraint("kind IN ('cloud','local','human')", name="kind"),)


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    key_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"))
    key_prefix: Mapped[str] = mapped_column(String(20), index=True)
    key_hash: Mapped[str] = mapped_column(String(200))  # argon2id
    scopes: Mapped[list[Any]] = mapped_column()  # JSON list[str]
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ticker(TimestampMixin, Base):
    __tablename__ = "tickers"

    ticker_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12))
    exchange: Mapped[str] = mapped_column(String(12))
    name: Mapped[str | None] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (UniqueConstraint("symbol", "exchange"),)


class PriceBar(Base):
    __tablename__ = "price_bars"

    ticker_id: Mapped[str] = mapped_column(ForeignKey("tickers.ticker_id"), primary_key=True)
    bar_date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Numeric(18, 6))
    high: Mapped[float | None] = mapped_column(Numeric(18, 6))
    low: Mapped[float | None] = mapped_column(Numeric(18, 6))
    close: Mapped[float] = mapped_column(Numeric(18, 6))
    adj_close: Mapped[float] = mapped_column(Numeric(18, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_id: Mapped[str] = mapped_column(String(80))


class Report(TimestampMixin, Base):
    __tablename__ = "reports"

    report_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    ticker_id: Mapped[str | None] = mapped_column(ForeignKey("tickers.ticker_id"))
    sector: Mapped[str | None] = mapped_column(String(64))
    report_type: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(10), default="1.0")
    title: Mapped[str] = mapped_column(String(200))
    author_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"))
    author_model: Mapped[str | None] = mapped_column(String(100))
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.run_id"))
    status: Mapped[str] = mapped_column(String(12), default=ReportStatus.DRAFT.value)
    verdict: Mapped[dict[str, Any] | None] = mapped_column()
    body: Mapped[dict[str, Any]] = mapped_column()
    provenance: Mapped[list[Any]] = mapped_column(default=list)
    tags: Mapped[list[Any]] = mapped_column(default=list)
    supersedes_report_id: Mapped[str | None] = mapped_column(ForeignKey("reports.report_id"))
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    review_note: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(80))

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','submitted','approved','published','rejected')",
            name="status",
        ),
        Index("ix_reports_ticker_status", "ticker_id", "status", "created_at"),
        Index("ix_reports_author", "author_agent_id", "created_at"),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"))
    task: Mapped[str] = mapped_column(String(200))
    input_digest: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="running")
    summary: Mapped[str | None] = mapped_column(Text)
    tokens_used: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('running','succeeded','failed','abandoned')", name="status"),
    )


class AuditEvent(Base):
    """Append-only. The application never updates or deletes rows; in
    Postgres, revoke UPDATE/DELETE on this table as well."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    actor_kind: Mapped[str] = mapped_column(String(10))  # agent | operator | system
    actor_id: Mapped[str | None] = mapped_column(String(100))
    run_id: Mapped[str | None] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(30))
    entity_id: Mapped[str | None] = mapped_column(String(30), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(10), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(60))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("status IN ('queued','running','done','failed')", name="status"),
    )


class IdempotencyKey(Base):
    """24h dedupe window for writes (docs/API.md §1); swept by the worker."""

    __tablename__ = "idempotency_keys"

    idem_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    key_id: Mapped[str] = mapped_column(String(30), primary_key=True)  # scoped per API key
    request_hash: Mapped[str] = mapped_column(String(80))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportChunk(Base):
    """RAG chunks (docs/ARCHITECTURE.md §6). Embeddings are stored as JSON
    float lists — portable across SQLite/Postgres, brute-force cosine in
    the app meets the <2s @ 10k-chunks target. pgvector/sqlite-vec are
    drop-in VectorStore adapters later; the schema stays the same."""

    __tablename__ = "report_chunks"

    chunk_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.report_id", ondelete="CASCADE"), index=True
    )
    ticker_symbol: Mapped[str | None] = mapped_column(String(12), index=True)
    section: Mapped[str | None] = mapped_column(String(80))
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[Any]] = mapped_column()  # JSON list[float]
    embed_model: Mapped[str] = mapped_column(String(60), default="nomic-embed-text")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("report_id", "seq"),)


# --- Quant (docs/INDEXES.md; phase 3) -----------------------------------


class Fundamental(Base):
    """Point-in-time fundamentals snapshot. `as_of` is when the values
    were OBSERVED — queries for date D must filter as_of <= D. Free
    providers only give current snapshots, so history accretes from the
    day ingestion starts (documented free-data limitation)."""

    __tablename__ = "fundamentals"

    ticker_id: Mapped[str] = mapped_column(ForeignKey("tickers.ticker_id"), primary_key=True)
    as_of: Mapped[datetime] = mapped_column(Date, primary_key=True)
    metrics: Mapped[dict[str, Any]] = mapped_column()  # pe, ps, ev_ebitda, roe, gm, de
    snapshot_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IndexDefinition(TimestampMixin, Base):
    __tablename__ = "index_definitions"

    index_key: Mapped[str] = mapped_column(String(30), primary_key=True)
    version: Mapped[str] = mapped_column(String(10))
    direction: Mapped[str] = mapped_column(String(15))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    description: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("direction IN ('higher_better','lower_better')", name="direction"),
    )


class IndexScore(Base):
    __tablename__ = "index_scores"

    ticker_id: Mapped[str] = mapped_column(ForeignKey("tickers.ticker_id"), primary_key=True)
    index_key: Mapped[str] = mapped_column(
        ForeignKey("index_definitions.index_key"), primary_key=True
    )
    score_date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    raw_value: Mapped[float | None] = mapped_column()
    score: Mapped[float] = mapped_column()  # normalized 0..100
    inputs_digest: Mapped[str] = mapped_column(String(80))

    __table_args__ = (Index("ix_index_scores_date", "score_date", "index_key"),)


class WeightProfile(TimestampMixin, Base):
    __tablename__ = "weight_profiles"

    profile_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    weights: Mapped[dict[str, Any]] = mapped_column()  # {index_key: weight}, sums to 1
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # backtested → immutable
    created_by: Mapped[str] = mapped_column(String(100))


class CompositeScore(Base):
    __tablename__ = "composite_scores"

    ticker_id: Mapped[str] = mapped_column(ForeignKey("tickers.ticker_id"), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("weight_profiles.profile_id"), primary_key=True
    )
    score_date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    score: Mapped[float | None] = mapped_column()  # None = insufficient data
    rank: Mapped[int | None] = mapped_column(Integer)


class BacktestRun(TimestampMixin, Base):
    __tablename__ = "backtest_runs"

    backtest_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("weight_profiles.profile_id"))
    from_date: Mapped[datetime] = mapped_column(Date)
    to_date: Mapped[datetime] = mapped_column(Date)
    universe: Mapped[list[Any]] = mapped_column()  # symbols
    rebalance: Mapped[str] = mapped_column(String(10), default="weekly")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    snapshot_id: Mapped[str] = mapped_column(String(80))
    code_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10), default="queued")
    metrics: Mapped[dict[str, Any] | None] = mapped_column()
    artifact_path: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (
        CheckConstraint("status IN ('queued','running','done','failed')", name="status"),
    )


# --- Billing (dormant until BW_BILLING_ENABLED; docs/SUBSCRIPTION.md) ---


class Subscriber(TimestampMixin, Base):
    __tablename__ = "subscribers"

    subscriber_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(80), unique=True)


class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"

    subscription_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscribers.subscriber_id"))
    stripe_subscription_id: Mapped[str] = mapped_column(String(80), unique=True)
    tier: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30))  # mirrors Stripe verbatim
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("tier IN ('free','pro','quant')", name="tier"),)


class Entitlement(Base):
    __tablename__ = "entitlements"

    subscriber_id: Mapped[str] = mapped_column(
        ForeignKey("subscribers.subscriber_id"), primary_key=True
    )
    feature: Mapped[str] = mapped_column(String(40), primary_key=True)


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    type: Mapped[str] = mapped_column(String(60))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)

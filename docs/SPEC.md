# Bullwright — Product Spec

**Version:** 0.1-draft · **Date:** 2026-07-11 · **Status:** awaiting review

## 1. What this is

A local-first framework for stock research where AI agents do the heavy
lifting. Humans (you) direct research; agents (Claude, Gemini, local Ollama
models) produce structured analysis reports; the system stores, indexes,
scores, publishes, and backtests them.

**It is a framework/template for fun** — not deployed to the public internet
yet — but every contract is written so that flipping it to a real deployed
product later requires configuration, not re-architecture.

## 2. Goals

1. **Track stocks** — maintain a watchlist with price/fundamentals snapshots.
2. **Structured reports** — every analysis is a versioned, schema-validated
   report attached to a ticker, authored by a human or an agent.
3. **Agent-first API** — a small, boring, well-documented REST API that any
   agent can drive via provided skills/scripts. The API is the only write
   path; agents never touch the DB directly.
4. **Publish as a blog** — reports render as static blog pages (Astro),
   built locally, deployable to any static host later.
5. **RAG search** — all reports + filings chunks embedded locally (Ollama)
   for fast semantic search by agents and humans.
6. **Quant indexes** — pluggable scoring indexes (value, momentum, quality,
   volatility, sentiment) with user-adjustable weights composing a single
   Bullwright Score per ticker; 3–6 month backtests of any weight config.
7. **Subscription-ready** — entitlement model + Stripe protocol specced
   (SUBSCRIPTION.md) but **not implemented in MVP** (decided 2026-07-11,
   ADR-0001). Dormant DB tables ship so enabling it later is additive.
8. **Good UI** — the blog is not an afterthought: score dashboards,
   per-ticker pages with charts, consensus-diff view, clean typography.
   UI polish is an explicit phase-4 deliverable.

## 3. Non-goals (MVP)

- Real-money trading, brokerage integration, order execution. **Never** in
  scope for agents (safety rule: agents research, humans decide).
- Real-time/streaming market data. Daily bars are enough.
- Multi-user auth/tenancy. Single operator + N agent identities.
- Public deployment. CI/CD files exist but deploy jobs are stubs.
- Financial advice. Every published page carries a disclaimer.

## 4. Personas

| Persona | Interface | Typical action |
|---|---|---|
| Operator (you) | CLI, blog, config files | Adjust index weights, review/approve reports, run backtests |
| Cloud agent (Claude/Gemini) | REST API via skills | Deep research → upload report |
| Local agent (Ollama gemma) | REST API via harness loop | Cheap recurring jobs: summarize news, tag reports, RAG answers |
| Reader (future) | Blog | Read published reports, gated by subscription tier |

## 5. Core concepts & lifecycle

```
Ticker ──< Report (draft → submitted → approved → published | rejected)
Ticker ──< PriceBar (daily OHLCV)
Ticker ──< IndexScore (per index, per date)
WeightProfile ──< CompositeScore ──< BacktestRun
Report ──< ReportChunk (RAG embeddings)
AgentIdentity ──< ApiKey, ──< AgentRun (audit log)
```

**Report lifecycle:** agents can only create `draft` and move it to
`submitted`. Only the operator can `approve`/`reject`/`publish`. Publishing
triggers a blog rebuild. Every state change is audited.

**Human-in-the-loop is a hard rule:** nothing an agent writes reaches the
blog without operator approval.

## 6. Report types (v1)

All share a common envelope (see docs/API.md §4) with a typed `body`:

- `company_deep_dive` — full company/product analysis (thesis, moat,
  financial highlights, risks, valuation, verdict).
- `earnings_review` — quarter results vs expectations, guidance, model deltas.
- `news_flash` — short event note (M&A, product launch, regulation).
- `thesis_update` — change to an existing thesis, must reference prior report.
- `sector_overview` — cross-ticker; attached to a sector, not one ticker.

Adding a new type = add a JSON Schema file + register it (see API spec).
The envelope also carries a required `verdict` block (rating enum
strong_buy…strong_sell, confidence 0–1, time horizon) so reports are
machine-comparable and feed the sentiment index.

## 7. Feature summary by phase

| Phase | Features | Exit criteria (see TEST_PLAN.md) |
|---|---|---|
| 1. Core | DB, REST API, report CRUD + lifecycle, API-key auth, blog build | All API contract tests green; a report goes draft→published→blog page |
| 2. Agents | Skills, scripts, harness for Ollama loop, RAG ingest/search | Claude & gemma each upload a valid report end-to-end; RAG hit-rate eval passes |
| 3. Quant | Price ingest, 5 core indexes, weight profiles, composite score, backtest | Backtest of default profile over 6 months reproducible bit-for-bit |
| 4. Product | UI polish (dashboard, charts, consensus diff), agent scorecard, cloud deploy configs, CI/CD deploy stubs. ~~Stripe~~ spec-only (ADR-0001) | Blog UI review passes; `docker compose up` = full stack |

## 8. Ideas added beyond your list (recommended)

1. **Report verdict block + agent scorecard** — because verdicts are
   structured, we can score each agent's historical accuracy against
   subsequent price moves ("Claude is 62% directionally right at 90 days").
   Cheap to add, very fun, and it feeds back into index weighting.
2. **Consensus diff view** — when Claude and Gemini both cover a ticker, the
   blog shows a side-by-side disagreement view. Disagreement is signal.
3. **Provenance manifest** — every agent report must list its sources
   (URLs, filing accession numbers, data snapshot ids). Enables audit and
   makes RAG chunks citable.
4. **Paper portfolio** — a virtual portfolio driven by composite-score
   rebalancing; gives the backtest a live forward-testing counterpart.
5. **Everything reproducible** — price data snapshots are content-addressed;
   a backtest records the exact snapshot + weight profile + code version,
   so any number on the blog can be regenerated.

## 9. Security posture (MVP, local-first)

- API binds to `127.0.0.1` only by default; no port forwarding.
- Every agent gets its own API key (scoped, revocable, hashed at rest).
- Rate limits per key; body size limits; strict JSON Schema validation on
  every write (reject unknown fields).
- Blog output is fully static — no server-side execution surface; all
  agent-supplied markdown is sanitized at build time (no raw HTML).
- Secrets live in `.env` (gitignored) with a committed `.env.example`.
- Audit log (`agent_runs`) is append-only.
- Prompt-injection stance: content fetched from the web/RAG is data, never
  instructions; skills spell this out (see AGENT_SKILLS.md §7).

## 10. Key technology choices (proposed — confirm in OPEN_DECISIONS.md)

| Concern | Choice | Why |
|---|---|---|
| API | Python 3.12 + FastAPI + Pydantic v2 | Schema-first, OpenAPI for free, best agent-tooling ecosystem |
| DB | SQLite (dev) → Postgres 16 (cloud), via SQLAlchemy 2 + Alembic | Zero-setup locally, same ORM code in cloud |
| Blog | Astro (static) + content collections | Free, fast, no runtime server = smallest attack surface |
| RAG | Ollama embeddings (`nomic-embed-text`, to be pulled) + sqlite-vec → pgvector | Fully local; same SQL interface pattern in cloud |
| Local LLM | Ollama `gemma4:12b-mlx` (verified installed: 12.4B, 262k ctx, native tools + thinking) | Your runtime; ADR-0001 |
| Market data | `yfinance` daily bars behind a `MarketDataProvider` interface | Free MVP; interface allows swapping paid providers |
| Quant | pandas + numpy, vectorized; no backtest framework dependency | 3–6 month daily backtests don't need zipline et al. |
| Payments | Stripe (spec-only, not built in MVP — ADR-0001) | Protocol frozen now, zero code until deploy decision |
| Cloud | Dockerfiles + docker-compose; Terraform stubs for Fly.io/Cloud Run | Containers now, cloud later without rework |

## 11. Disclaimer requirement

Every published page and every API response containing scores includes:
*"Bullwright is a research toy. Nothing here is investment advice."*

# Bullwright — Architecture

**Version:** 0.1-draft · **Status:** awaiting review

## 1. Shape of the system

Monorepo, three runnable apps, shared packages, agents as first-class
citizens. Local-first: everything runs on one machine with `docker compose`
or bare processes; cloud is the same containers pointed at Postgres.

```
                ┌─────────────────────────────────────────────┐
                │                  agents/                    │
                │  Claude ──┐  Gemini ──┐  Ollama gemma ──┐   │
                │           │           │    (harness loop)│  │
                └───────────┼───────────┼──────────────────┼──┘
                            ▼           ▼                  ▼
                      HTTPS + API key (localhost only in MVP)
                            │
                    ┌───────┴────────┐        ┌──────────────┐
                    │   apps/api     │───────▶│ apps/worker   │
                    │   FastAPI      │ queue  │ price ingest, │
                    │                │        │ RAG embed,    │
                    └───┬────────┬───┘        │ index calc,   │
                        │        │            │ backtests     │
                 ┌──────┴──┐  ┌──┴────────┐   └──────┬───────┘
                 │  DB     │  │ object    │          │
                 │ SQLite/ │  │ store     │◀─────────┘
                 │ Postgres│  │ data/     │
                 └──────┬──┘  └───────────┘
                        │ publish event
                        ▼
                 ┌────────────┐     static files      ┌────────┐
                 │ apps/web   │──────────────────────▶│ reader │
                 │ Astro build│                       └────────┘
                 └────────────┘
```

## 2. Directory layout (authoritative)

```
stock_research/
├── README.md
├── docs/                      # All specs (this folder). ADRs in docs/adr/.
│   └── adr/                   # Architecture Decision Records, NNNN-title.md
├── apps/
│   ├── api/                   # FastAPI service — the ONLY write path
│   │   └── src/bullwright_api/
│   │       ├── routes/        # one module per resource (reports, tickers, …)
│   │       ├── auth/          # API-key middleware, scopes
│   │       ├── schemas/       # Pydantic models mirrored from docs/API.md
│   │       └── services/      # business logic; routes stay thin
│   ├── worker/                # background jobs (see §4)
│   │   └── src/bullwright_worker/
│   │       └── jobs/          # price_ingest, embed, index_calc, backtest
│   └── web/                   # Astro static blog
│       ├── src/content/       # generated from DB at build time — never hand-edited
│       └── src/pages/
├── packages/                  # shared Python packages (installed editable)
│   ├── core/                  # domain models, report envelope, index protocol
│   ├── db/                    # SQLAlchemy models + Alembic migrations
│   └── clients/               # typed API client (used by agent scripts AND tests)
├── agents/
│   ├── skills/                # Claude-style skills, one dir per skill
│   ├── scripts/               # thin CLI wrappers agents shell out to
│   └── harness/               # Ollama loop runner (see AGENT_SKILLS.md)
├── rag/
│   ├── ingest/                # chunkers per source type
│   └── index/                 # vector store adapters (sqlite-vec, pgvector)
├── data/                      # gitignored: sqlite db, price snapshots, artifacts
├── .github/workflows/         # CI (real) + CD (stubbed, disabled)
├── infra/
│   ├── docker/                # Dockerfile.api, Dockerfile.worker, compose.yaml
│   └── cloud/                 # terraform/ fly.toml stubs — cloud usage code
├── tests/
│   ├── unit/ integration/ security/
└── .env.example
```

**Rules that keep this maintainable:**

- Dependency direction: `apps/* → packages/* → nothing`. Packages never
  import from apps. Agents only use `packages/clients` + HTTP.
- The DB is written by `apps/api` and `apps/worker` only. The blog reads via
  a build-time export script, agents via the API.
- Any cross-cutting decision gets an ADR in `docs/adr/` before code.

## 3. apps/api

- FastAPI, fully typed, OpenAPI spec auto-generated and committed to
  `docs/openapi.json` (CI fails if drift).
- Layers: `routes` (HTTP) → `services` (logic) → `packages/db` (persistence).
- Auth: `Authorization: Bearer bw_<key>`; keys hashed (argon2) in DB,
  scoped (see API.md §3). Localhost bind by default; `BW_BIND=0.0.0.0`
  is an explicit opt-in that also forces rate limiting on.

## 4. apps/worker

MVP: a simple job runner polling a `jobs` table (no Redis dependency —
one less moving part; the table gives us audit for free). Cloud: same code,
optionally swapped to a real queue later. Jobs:

| Job | Trigger | Effect |
|---|---|---|
| `price_ingest` | cron (daily) or manual | fetch daily bars → `price_bars` + content-addressed snapshot in `data/snapshots/` |
| `embed_report` | report submitted/approved | chunk → embed via Ollama → vector store |
| `index_calc` | after price_ingest | compute each index score per ticker per date |
| `composite_calc` | index_calc done / weights changed | compose scores per weight profile |
| `backtest` | manual/API | run backtest, store artifact + metrics |
| `blog_export` | report published | regenerate `apps/web/src/content` + rebuild |

## 5. apps/web (blog)

- Astro static site. Content collections: `reports/`, `tickers/`, `indexes/`.
- Build-time export script pulls **published** reports only from the DB and
  writes sanitized markdown + JSON frontmatter. Agent markdown is sanitized
  (strip raw HTML, scripts, iframes) at export time.
- Pages: home (latest reports), per-ticker page (reports timeline + score
  chart + consensus diff), per-report page, index methodology page,
  backtest results page. Disclaimer in the footer of every page.
- Zero client-side data fetching in MVP. Future subscription gating happens
  at the hosting layer (see SUBSCRIPTION.md), not in the static site.

## 5b. Ops dashboard (`/ops`, added 2026-07-11 at operator request)

Troubleshooting surface served by apps/api itself — live DB, no extra
process, no build step. Pages: overview (report/job/run counts, recent
failures), review queue (submitted reports awaiting operator action),
jobs table with errors, agent-run history, audit-log tail. Server-rendered
HTML, no client framework.

Security posture: mounted **only when `BW_ENV=dev`** (the default). It
never ships in a prod config; the blog remains the only public surface.
Rationale: for a framework, the first debugging question is "what state
is the system in" — the dashboard answers it without psql.

## 6. RAG subsystem

- **Ingest:** report bodies, provenance sources, (later) filings. Chunker
  per source type in `rag/ingest/`; chunks carry `{report_id, ticker,
  section, source_url}` metadata.
- **Embed:** Ollama `nomic-embed-text` (768-dim) — local, fast, free.
- **Store:** `sqlite-vec` table in dev; `pgvector` in cloud. Both behind a
  `VectorStore` protocol in `rag/index/` (same interface, two adapters).
- **Query path:** `GET /v1/search?q=` → embed query → top-k + metadata
  filter (ticker, date range, report type) → return chunks with citations.
- Hybrid search (BM25 + vector, reciprocal-rank fusion) is specced as a
  fast-follow; the API response shape already supports it.

## 7. Cloud usage

Written now, deployed later:

- `infra/docker/`: one Dockerfile per app + `compose.yaml` that brings up
  api + worker + Postgres + Ollama. `docker compose up` = full stack — this
  is also the cloud story in miniature.
- `infra/cloud/`: Terraform stubs (Fly.io primary target; Cloud Run
  alternative) for: Postgres, the two containers, secrets, a static-site
  host for the blog. All behind `count = var.enabled ? 1 : 0` so nothing
  provisions accidentally.
- 12-factor config: everything via env vars, `.env.example` documents all.

## 8. GitHub & CI/CD

- Repo: GitHub, `main` protected in spirit (solo project): work on
  branches, merge via PR to keep history reviewable by agents.
- `ci.yml` (real, runs on every PR): lint (ruff), typecheck (mypy/pyright),
  unit + integration tests, OpenAPI drift check, Astro build, `pip-audit`.
- `cd.yml` (stub, `if: false` guard): build/push images, terraform plan,
  deploy blog. Turning on deployment = flipping the guard + adding secrets.
- Conventional commits; CHANGELOG generated later if it ever matters.

## 9. Scaling story (why this won't need a rewrite)

| Pressure | Response already designed in |
|---|---|
| More data | SQLite→Postgres is a connection-string change (SQLAlchemy + Alembic both sides) |
| More jobs | jobs table → real queue behind the same enqueue interface |
| More agents | API keys are cheap; rate limits per key; audit log scales linearly |
| More indexes | index protocol (INDEXES.md §3) — drop in a class, register, done |
| Real users | static blog + entitlement service specced in SUBSCRIPTION.md |
| Paid market data | `MarketDataProvider` interface; yfinance is just adapter #1 |

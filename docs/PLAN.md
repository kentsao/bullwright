# Bullwright — Implementation Plan

**Status:** proposed, awaiting your review of the specs. No code exists yet.

## Build order & rationale

Contracts-first: each phase implements against specs that are already
frozen, so agents (including me) can work in parallel lanes without
stepping on each other.

### Phase 0 — Repo bootstrap (½ day)
- git init, GitHub repo, branch protection habits, `.gitignore`,
  `.env.example`, LICENSE (pending D8), uv workspace + pyproject layout,
  ruff/mypy config, pre-commit, `ci.yml` skeleton (lint+test only).
- Exit: CI green on an empty test.

### Phase 1 — Core spine (3–5 days of focused work)
1. `packages/db`: models + Alembic migrations for agents/keys/tickers/
   reports/audit/jobs (subscription tables included, unused).
2. `packages/core`: report envelope, report-type JSON Schemas, status
   machine.
3. `apps/api`: auth middleware, reports + tickers routes, audit writes,
   OpenAPI committed.
4. `apps/web`: Astro skeleton, export script, sanitization, disclaimer.
5. Tests: contract suite, security S1–S10 subset, E2E steps 1–4.
- Exit: TEST_PLAN §7 steps 1–4 green on SQLite + Postgres.

### Phase 2 — Agents & RAG (3–4 days)
1. `packages/clients` + `bw-agent` CLI.
2. Skills: `bw-report-writer`, `bw-rag-search` first; rest after.
3. `rag/`: chunker, Ollama embed, vector store behind a `VectorStore`
   protocol (v1: portable JSON-embedding store + numpy cosine — meets the
   <2s @10k-chunks target with zero native-extension risk; sqlite-vec/
   pgvector adapters are drop-ins later), `/search`.
4. `apps/worker`: jobs-table runner; `embed_report` + `blog_export`.
5. **Ops dashboard `/ops`** (operator request 2026-07-11): overview,
   review queue, jobs, runs, audit tail; dev-env only (ARCHITECTURE §5b).
6. `agents/harness`: runner with H1–H8, `news_sweep` + `report_tagger`
   loops.
7. Tests: skill lint, harness fakes, RAG eval baseline, A1–A5.
- Exit: Claude uploads a real deep-dive end-to-end; gemma live smoke passes.

### Phase 3 — Quant (3–4 days)
1. `MarketDataProvider` + yfinance adapter + snapshot store; price_ingest.
2. Index protocol + 5 core indexes + normalization.
3. Weight profiles + composite; backtest engine + metrics + blog page.
4. Tests: TEST_PLAN §4 complete incl. reproducibility bit-diff.
- Exit: default-profile 6-month backtest reproducible; scores on blog.

### Phase 4 — UI polish & packaging (2–3 days) *(revised per ADR-0001: Stripe cut)*
1. **Blog UI pass:** home dashboard (top movers by composite score, latest
   reports), per-ticker page (price + score sparkline charts, report
   timeline), consensus-diff view, index methodology pages, dark mode,
   responsive. Charts = lightweight client-side (e.g. Chart.js/uPlot) fed
   by build-time JSON — site stays static.
2. Agent scorecard page (AGENT_SKILLS.md §6).
3. `infra/docker` compose full stack; `infra/cloud` terraform stubs;
   `cd.yml` stub.
- Exit: `docker compose up` = whole system; UI review checklist passes.
- ~~Stripe~~: spec-only; P1–P6 tests written when/if billing is ever built.

## Working agreement for the build
- Every PR: spec section referenced, tests included, docs updated.
- I implement; you review PRs + make OPEN_DECISIONS calls; anything
  ambiguous becomes an ADR before code.
- After each phase we tag `v0.N.0` and do a 15-minute retro on the spec —
  spec bugs are cheaper to fix between phases.

## Immediate next actions (waiting on you)
1. ~~Answer OPEN_DECISIONS~~ ✅ resolved 2026-07-11 → ADR-0001.
2. Say **"yes / go"** → I start Phase 0 (repo bootstrap, git init, CI
   skeleton). No implementation happens before that.
3. At phase-2 setup: `ollama pull nomic-embed-text` (embeddings model,
   ~270 MB) — I'll remind you.

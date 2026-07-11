# ADR-0001: Initial stack and MVP scope

**Date:** 2026-07-11 · **Status:** accepted · **Decider:** operator

## Context
Spec phase complete; eight open decisions needed resolution before Phase 0.
Operator is an enthusiastic Python-native developer building a
local-first research framework; UI + backend quality prioritized over
monetization for MVP.

## Decision
1. **Local model:** Ollama `gemma4:12b-mlx` (verified installed: 12.4B,
   262k context, native tools + thinking, nvfp4). Harness uses Ollama's
   native tool-calling API. `nomic-embed-text` to be pulled for embeddings.
2. **Blog:** Astro static site. UI quality is an MVP goal.
3. **Backend:** Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 +
   Alembic, uv-managed monorepo, ruff + strict mypy.
4. **Normalization:** winsorized min-max (p5/p95) cross-sectional.
5. **Universe:** 20–40 ticker watchlist assumption.
6. **Billing:** Stripe is spec-only; no billing code in MVP. Dormant
   subscription tables kept in schema. Phase 4 repurposed to UI polish +
   cloud packaging + agent scorecard.
7. **Fundamentals:** yfinance adapter first; SEC EDGAR fast-follow.
8. **Repo:** private initially, MIT license, secret hygiene as if public.

## Consequences
- One language (Python) across api/worker/quant/rag/harness/scripts.
- No PCI/billing surface in MVP; SUBSCRIPTION.md stays the future contract.
- Harness simplifications: native tool calls replace JSON-format prompting
  (H2 narrowed); H4 context discipline retained for quality, not necessity.

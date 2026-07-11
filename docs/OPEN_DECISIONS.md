# Bullwright — Decisions (RESOLVED 2026-07-11)

All decisions made by operator on 2026-07-11. Recorded as ADR-0001
(docs/adr/0001-initial-stack.md). This file is kept as the decision log;
new open questions get appended below the line.

## D1 — Local model ✅ `gemma4:12b-mlx`
Verified installed via `ollama show`: gemma4_unified arch, 12.4B params,
**262,144 context length**, nvfp4 quantization, capabilities: completion +
**tools** + thinking. Consequences for the harness spec (applied in
AGENT_SKILLS.md): use Ollama's native tool-calling API instead of
JSON-format prompting; context budget pressure is largely gone but context
discipline (H4) is retained for cost/latency and attention quality.
Embedding model `nomic-embed-text` still needs `ollama pull` at phase-2
setup (not currently installed).

## D2 — Blog framework ✅ Astro
Static output, markdown-native content collections, minimal attack surface,
free. UI quality is now an explicit MVP goal (operator: "we need to set a
good UI & backend") — see PLAN.md phase 4.

## D3 — API language ✅ Python 3.12 + FastAPI
Operator preference (enthusiastic Python developer) and it
unifies API + quant + RAG + harness in one language. Readability/
maintainability bar: fully typed, ruff + mypy strict, thin routes / fat
services, packages never import apps.

## D4 — Normalization ✅ winsorized min-max (default stands)

## D5 — Universe size ✅ assume 20–40 ticker watchlist (default stands)
Revisit only if watchlist shrinks below ~15.

## D6 — Stripe ✅ CUT from MVP — spec-only
Payment is not needed now. SUBSCRIPTION.md remains as the protocol spec and
the dormant DB tables stay in the schema (cheap, avoids future migration
pain), but **no billing code is written** in any MVP phase. Former phase 4
is repurposed: UI polish + cloud/docker + agent scorecard.

## D7 — Fundamentals source ✅ yfinance first, EDGAR adapter fast-follow

## D8 — Repo visibility ✅ default: private to start, MIT license included
Flip to public template later if desired; secret hygiene enforced either way.

---

*(no open questions at this time)*

# Bullwright — Subscription Protocol (Stripe)

**Version:** 0.1-draft · **Status:** **SPEC-ONLY — not implemented in MVP**
(decided 2026-07-11, ADR-0001). This document freezes the protocol so the
dormant DB tables (DB_SCHEMA.md) and entitlement keys are designed
correctly; no billing code is written until a deploy decision. When built,
it ships behind `BW_BILLING_ENABLED=false`.

## 1. Model

Stripe owns money; Bullwright owns entitlements. We never store card data —
Stripe Checkout (hosted page) + Customer Portal handle all PCI surface.

### Tiers

| Tier | Price (placeholder) | Entitlements |
|---|---|---|
| `free` | $0 | published reports older than 7 days; weekly digest |
| `pro` | $9/mo | all published reports immediately; score history pages |
| `quant` | $29/mo | pro + scores/backtests via API (`market:read` reader keys) + weight-profile playground |

Entitlement keys: `reports.delayed`, `reports.full`, `scores.web`,
`scores.api`, `backtest.view`. Tier→entitlement mapping lives in one config
file (`packages/core/billing/tiers.yaml`) so pricing experiments don't
touch code.

## 2. Flows

**Subscribe:** blog "Subscribe" → `POST /billing/checkout-session`
(creates Stripe Checkout session with `client_reference_id =
subscriber_id`) → Stripe-hosted payment → webhook activates → success page.

**Manage/cancel:** `POST /billing/portal-session` → Stripe Customer Portal.
We never build cancel/upgrade UI.

**Webhooks** (`POST /webhooks/stripe`, signature-verified, idempotent via
`stripe_events` ledger):

| Event | Action |
|---|---|
| `checkout.session.completed` | create/link subscriber, activate subscription |
| `customer.subscription.updated` | mirror status + tier + period end |
| `customer.subscription.deleted` | downgrade to free at period end |
| `invoice.payment_failed` | mark `past_due`; grace period 7 days, then free |

Rules: webhook handler is the **only** writer of subscription state; state
mirrors Stripe verbatim (no invented statuses); unknown event types are
logged and 200'd (never 500 → Stripe retry storm); replayed event ids are
no-ops.

## 3. Enforcement with a static blog

The site stays static; gating is at the edge, not in page JS:

- MVP-when-deployed: blog on Cloudflare Pages/Netlify; premium paths
  (`/reports/recent/*`, `/scores/*`) checked by an edge function that
  validates a signed session cookie (JWT, issued by the API after
  Stripe-linked magic-link email login) against entitlements.
- API tier: `quant` subscribers get read-only API keys (existing key
  system, scopes `market:read` only).
- Local/pre-deploy: flag off → everything public on localhost, zero
  billing code in the hot path.

## 4. Security & compliance requirements (testable)

- P1: webhook signature invalid → 400, zero DB writes.
- P2: replayed `stripe_event_id` → 200, zero additional writes.
- P3: no card/PAN data ever in our DB or logs (grep-based CI check on log
  fixtures + schema review).
- P4: entitlement check fails closed (Stripe/API unreachable → treat as free).
- P5: all billing endpoints 404 when `BW_BILLING_ENABLED=false`.
- P6: test-mode keys only in CI; live keys never in repo or CI secrets
  until deploy decision.

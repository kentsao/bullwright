# Security Policy

Bullwright is a local-first research framework. It is designed to run on
`127.0.0.1` and is **not hardened for public internet exposure** — if you
bind it to a public interface, you are on your own (start by reading
docs/API.md §6 and keeping `BW_API_HOST=127.0.0.1`).

## Reporting a vulnerability

Please open a GitHub Security Advisory (Security tab → "Report a
vulnerability") rather than a public issue. You should get a response
within a week.

## Scope notes for researchers

- Secrets are never committed: `.gitignore` + gitleaks (pre-commit and CI).
  If you find a secret in history, report it immediately.
- Agent-supplied content is untrusted by design: markdown is sanitized at
  blog build; API rejects raw HTML; see docs/TEST_PLAN.md §3.
- There is no payment code in this repository (billing is spec-only).

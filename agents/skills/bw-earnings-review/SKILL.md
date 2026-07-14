# bw-earnings-review

Review a quarter's results against the standing thesis and upload an
`earnings_review` report.

**Required scopes:** `reports:write`, `reports:read`, `search:read`

## Goal

An `earnings_review` that a reader who knows the prior thesis can act
on: what beat/missed, what management guided, and what it changes.

## Workflow

1. `bw-agent run start --task "earnings_review:<TICKER> <PERIOD>"`
2. **Pull the prior thesis first** — the review must reference it:
   `bw-agent search "thesis and key metrics" --ticker <TICKER> -k 8`
   If there is no prior coverage, stop and use bw-report-writer for a
   deep dive instead; an earnings review without a thesis is noise.
3. Research the quarter (release, call, filing). Build provenance as you
   go — the filing reference is mandatory.
4. Draft `draft.json` with `report_type: "earnings_review"`. Body fields:
   `fiscal_period` (e.g. `2026Q2`), `results_vs_expectations`,
   `guidance`, `takeaways` (list), optional `model_deltas`.
   Numbers beat adjectives: "gross margin 74.2% vs 75.5% guided", not
   "margins slightly soft".
5. `bw-agent report validate --file draft.json` → fix →
   `bw-agent report create --file draft.json --run <run_id>` →
   `bw-agent report submit <report_id>`
6. `bw-agent run finish <run_id> --status succeeded --summary "<one line>"`

## Verdict rule

The verdict must answer: does this quarter confirm or dent the standing
thesis? If it materially changes the thesis, note in `takeaways` that a
thesis_update should follow (see bw-thesis-update skill).

## Self-check

- [ ] prior thesis searched and referenced in `results_vs_expectations`
- [ ] fiscal_period matches the pattern `2026Q2` / `FY2026Q2`
- [ ] every headline number has the comparison base stated
- [ ] filing reference in provenance; validate passes; run closed

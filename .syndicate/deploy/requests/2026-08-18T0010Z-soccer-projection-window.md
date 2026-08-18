# DEPLOY REQUEST — soccer projection window (#379 second half) + the modelled-fair edge column

**service:** **web AND refresh-worker** — both, and the reason is below
**sha:** `b4d82364` on `main` (also carries `f16214fe`)
**lane:** soccer-projection-collapse / modelled-fair-edge
**urgency:** normal. Soccer has been in this state for days; nothing degrades further by waiting for a window you want.

## why both services

`attach_projections` has two callers and they run on different services:

- `syndicate/blueprints/intelligence.py:2208` — the `/api/board/book-grid` API. **web**, serve-time.
- `syndicate/features/shared/book_grid_artifact.py:222` — the `book_grid` artifact build. **refresh-worker**.

Deploying only one leaves the other still reading a single date, so the board and the artifact would disagree about the same slate. Deploying web alone is the more misleading half: the API would show projections that the stored artifact does not have.

## reason

**The `#379` widening shipped inert.** `load_soccer_projections` grew a `window_dates` parameter so the projection read could span the slate window the QUOTE read already spans. It defaults to `[selected_date]` *"so every existing caller behaves exactly as before"* — and neither production caller passed one. The merge logic, its cost analysis and its documentation all shipped while production kept reading one date.

Soccer shards by KICKOFF date and almost nothing kicks off "today". Measured 2026-08-17:

```
window_dates          7   (08-17 .. 08-23)
grid_rows         8,759
rows_with_projection  4
matches_in_source     3
unmatched_match_rows 8,755
```

The three that DID load were today's and in play, so their pregame projections were correctly withheld. **Today was never the problem; the other six dates were never read.**

Also in this sha (`f16214fe`): `edge_vs_modelled_fair_pct`, the user-decided `book_margin_model` edge column. Named here so it is not a surprise in the payload — it is additive, writes only new `edge_vs_modelled_fair_*` fields, and **never touches `edge_vs_market_pct`**.

## verify — BOTH halves, on the served soccer payload

`GET /api/board/book-grid?sport=soccer`, read the `projections` block:

1. **`rows_with_projection` rises from `4`** toward the thousands.
2. **`unmatched_match_rows` falls from `8,755`.**

**One without the other is not success.** If projections rise while unmatched stays flat, the window widened but the join is still missing fixtures — a different defect wearing this fix's clothes.

Second, cheap, and it is the one that catches a regression rather than a win: **`edge_vs_market_pct` must be unchanged on every row.** The new column is additive and must not have moved the real edge.

## the trap

`window="slate"` is load-bearing. `resolve_window_dates` DEFAULTS to `window="day"`, which returns one date — a bare call leaves the fix exactly as inert as the bug. I wrote it that way first and caught it by reading the returned value. Two tests now pin the call site and the `"slate"` argument by name; if either is edited away, they fail.

## rollback

Redeploy each service's prior live SHA. No env or config change is involved. The window resolver is wrapped in try/except with a `[selected_date]` fallback, so the worst in-place failure mode is today's behaviour, not a broken join.

## cost, measured before shipping

`#241` is the standing reason to check rather than assume. Every tracked soccer recommendations file in the repo is **22 files totalling 1.5 MB** (2–40 KB each). A full 10-league × 7-date read is **~2.8 MB worst case**, against the **8.8 MB** soccer quote window already read beside it. The widened read is a fraction of the read it accompanies.

## tests

57 across the soccer suites, plus 22 for the modelled-fair column. Nothing is deployed yet, so none of this is measured in production.

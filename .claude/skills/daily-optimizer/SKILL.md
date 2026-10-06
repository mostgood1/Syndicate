---
name: daily-optimizer
description: Read back the daily optimizer the model-scorecard cron publishes -- per sport, how the model's probabilities compare with reality (calibration shrink w*), how the PUBLISHED betting recommendations performed against reality (ROI vs predicted EV by EV band, beside the pooled population), and which bounded rank/stake adjustments it validated. Use when asked how recommendations are doing, whether the models are over/under-confident, what the optimizer changed, or for the daily unattended review.
---

# Daily optimizer

Lane `daily-optimizer` (2026-10-05). User request: daily, per sport, model accuracy vs reality
**and** betting-recommendation accuracy vs reality, each with an optimize step, unattended.

## What runs, and where

Nothing new is scheduled for the computation. `scripts/publish_model_scorecard.py` -- the
`model-scorecard` job, 11:30Z daily on the local fleet (`scripts/local_production.py`) -- now
also runs `syndicate/features/shared/daily_optimizer.py` over the **same graded rows** the
scorecard grades (it wraps the scorecard's `grade` callable; the grader itself is untouched, so
no scorecard history reset). Fail-soft: an optimizer error is logged `OPTIMIZER_FAILED` and the
scorecard still publishes. `--optimizer off` disables it.

Published: `reports/model_scorecard/model_scorecard_optimizer.json` (report + overlay) and
`..._optimizer_state.json` (its incremental state). The scorecard's own JSON carries an
`optimizer` summary block too.

A daily Claude scheduled task (`daily-optimizer-review`) runs `review.py` after the cron and
reports. That task is the "review"; it never changes production.

## Reading it

```bash
py -3 .claude/skills/daily-optimizer/review.py          # fleet, token from WSL
py -3 .claude/skills/daily-optimizer/review.py --json
```

Exit codes: `0` fresh · `2` stale (judged on `generated_at`, never a scheduler field) · `4`
unreadable · `5` no token.

**Model vs reality** -- per cell `sport|market|segment|phase`, the Brier-optimal shrink of the
model edge toward the market, `w* = Σ d·r / Σ d²` (d = model − market, r = outcome − market).
`w* ≈ 1`: edge sized right. `w* < 1`: overconfident. `w* ≈ 0`: no information beyond the line.
`model_brier_minus_market` per sport: negative means the model beat the book.

**Recommendations vs reality** -- the rows the shortlist PUBLISHED (`clv_openings/<date>.jsonl`,
joined on the recorder's population key: 20,111 of 20,519 published keys matched on 2026-10-04),
graded by EV band: bets, hit rate, ROI per bet vs the EV predicted for them. "Predicted" is the
MODEL's EV (`p_model x odds - 1`); `market_ev` beside it is the price against the de-vigged fair,
which sits near minus the vig and is the no-model baseline (before `daily_optimizer/2`, 2026-10-06,
the market number was mislabelled as the prediction -- the first run's "-3.6% to -5.6%"). The pooled
population's same band sits beside it -- never instead of it (learnings 2026-09-21). Published
rows are graded at their first recorded sighting, which can predate publication.

## What it may change -- and what it may not

**2026-10-05 PRIME DIRECTIVE: no market is withheld.** The overlay holds only multipliers in
`[0.5, 1.0]` for RANK and STAKE:

- `edge_shrink` -- cells with `w*` CI upper < 1, BH-FDR q=0.10, every leave-one-date-out `w* < 1`,
  ≥60 games / ≥5 dates. Factor = CI upper (the smallest shrink the evidence supports), floor 0.5.
- `stake_scale` -- published bets in the cell realised significantly below predicted EV, same bar.

Never > 1, never a removal, 72 h expiry, ≤200 entries, `validate_overlay` re-checks on read.

**APPLIED (phase 2, 2026-10-05, user "wire phase 2").** The cron also writes
`reports/model_scorecard/model_scorecard_optimizer_overlay.json` (overlay only), and
`syndicate/features/shared/optimizer_overlay.factor_for_row` turns it into one multiplier per row:
`max(0.5, edge_shrink x stake_scale)` for the row's cell, 1.0 when nothing validated applies. It is
multiplied into:

- RANK -- `layer2_board._apply_skill_reliability` (stamped `optimizer_factor` on the score when it bites;
  `value_pct` and admission untouched);
- STAKE -- `portfolio_commit._sizing_skill_factor` (the model edge the stake sizes from).

Kill switch `SYNDICATE_OPTIMIZER_OVERLAY=off`. The consumers are ROLE code (web, refresh-worker):
they load it at the next role restart after a fleet fast-forward. To see whether a live row is
being moved, look for `optimizer_factor` on served Layer 2 scores and the
`[optimizer_overlay] reason=...` log line.

## Expect "insufficient" for weeks

History starts at the first run after landing (no backfill: the scorecard's state keeps only sums
that cannot be split into the calibration terms). 60 games / 5 dates per cell is days for NFL props
and weeks for thin markets. An empty overlay is the honest early output, not a fault.

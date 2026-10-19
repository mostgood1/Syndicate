# MLB strikeouts scale check: LEAD WITHDRAWN. The bias is measured, the calibrator absorbs it, and the three further defects I thought I found were all my own instruments

`[2026-10-19 21:40Z / 4:40 PM CDT]` lane `mlb-strikeouts-scale-check`
`[no outcomes used anywhere in this document]`

## The lead, and the verdict

My 2026-10-16 large-gap bug list carried:

> **mlb strikeouts** — 5 of 5 rejected, all OVER, mean |edge| 26.4. A one-sided
> rejection set at that magnitude is the signature of a scale or denominator
> error, not of noise.

**Not a scale bug. Withdrawn.** The bias is real, already measured with a
sample size, and already absorbed before the number reaches the board. Three
times while checking it I thought I had found something worse, and all three
were defects in *my* instruments, not in the pipeline. That is the actual
content of this document, so it is written in the order I got it wrong.

These rows are live today **because of my own change earlier today**: the old
15-point magnitude bound dropped all three, and `_plausibility_refusal` admits
them. So this family reached the board for the first time this afternoon, which
is why checking it before anything consumed it was worth doing.

## 1. The row answers the lead by itself

3 strikeouts rows, all Freddy Peralta, `proj = 5.502`:

```
model_skill.status          : measured
model_skill.verdict         : "parity with the market: Brier +0.017
                               [-0.009, +0.042] over 193 starts; biased high ~13%"
model_skill.sample_games    : 193
model_skill.verdict_class   : parity
model_skill.established_loss_rel : 0.0

calibration_cell            : strikeouts|*
calibration_method          : market_shrink
calibration_version         : mlb-market-shrink-2026-10-10
model_probability_raw       : 0.665192  ->  model_probability_cal : 0.424082
market_fair_prob_over       : 0.412900
model_edge_pct_raw          : 25.65     ->  model_edge_pct        : 1.539
ev_pct                      : 2.173
```

`biased high ~13%` over **193 starts** is a measurement, not a blind spot. And
the shrink is principled: it pulls the model probability **96% of the way to
the market price** (0.6652 to 0.4241 against a fair of 0.4129). The Brier CI
**spans zero** — no demonstrated skill — and a model with no measured edge
should not be allowed to claim one. Served edge **+1.54**, not +25.65.

**My 10-16 reading counted `edge_vs_market_pct` (RAW) when the consumer reads
`model_edge_pct`.** For this family those differ by **16.7x**, and the whole
"mean |edge| 26.4" characterisation evaporates at the field that matters. My own
standing rule says count the field the consumer reads
(`feedback_a_projection_is_not_a_model_edge`). I got the right answer on four
other sports for the wrong reason, which is worse than getting it wrong,
because nothing in the result flagged the method error.

## 2. WRONG: "the calibration layer is inert on 99.5% of the board"

`market_shrink` fires on **6 rows of 2,714** measured rows, and only 6 have a
`calibration_cell` at all (`mlb strikeouts|*` 3, `totals|first1` 2,
`totals|first5` 1). Everything else is `identity`, shrink factor **1.000**:

| verdict_class | method | rows | med raw | med cal | shrink |
|---|---|---|---|---|---|
| parity | `identity` | 1,173 | 5.74 | 5.74 | 1.000 |
| **loses_to_market** | `identity` | **771** | 4.94 | 4.94 | **1.000** |
| absent | `identity` | 652 | 9.33 | 9.33 | 1.000 |
| absent | `skipped_no_fair` | 59 | 25.20 | 25.20 | 1.000 |
| parity | `market_shrink` | 6 | 24.08 | **1.44** | **0.060** |

I drafted this as "771 rows publish `loses_to_market` on themselves and are
served at full magnitude — the calibration layer is inert." **That framing is
wrong, and wrong in exactly the way I warn about.** The skill verdict does not
act through the probability at all. It acts through:

- **board order** — `_apply_skill_reliability` (`layer2_board.py:936`) folds
  `skill_reliability` into `score["score"]` as `min(raw, raw * factor)`, where
  `factor = max(0.5, 1 - 5.0 * established_loss_rel)`;
- **admission** — `verdict_class: loses_to_market` makes a row "rest on the
  model" (`layer2_board.py:933`), which withholds one-sided rows under the
  2026-09-11 decision;
- **stake** — `portfolio_commit.py:346` reads `established_loss_rel` directly.

`established_loss_rel` is consumed in **seven** non-test modules. It is not an
unread field. `calibration_method: identity` means *this* mechanism did not
fire, not that the verdict was ignored — and `_apply_skill_reliability`'s own
docstring says stake is deliberately untouched by the score term. The
architecture is better than my draft gave it credit for.

## 3. WRONG: "193 losing rows escape their demotion"

The demotion is **reachable and correct**. `skill_reliability` is stamped only
when it bit, so the stamp is the instrument:

- **1,247 rows demoted by `category`**, **310 by `bucket`**
- factors span **0.98 down to 0.50** (0.50 is `SKILL_FLOOR`, hit by 196 rows)

I then found 193 rows (soccer, `established_loss_rel` 0.315 and 0.017) whose
own note predicts a factor below 1.0 and which carry **no stamp**, and recorded
them as a defect. Two innocent explanations had to be ruled out first — a null
score (early return) and a validated bucket pocket cancelling the demotion. I
ran the real `bucket_factor` over the served rows, got `None`, and scored it
`NEITHER -- DEFECT`.

**That was my instrument.** My process logged
`[skill_overlay] SOURCE=static reason=overlay_absent buckets=0` — it could not
see the overlay the worker has. A `None` from a *missing overlay* is
indistinguishable from a `None` meaning *no bucket matched*, and I let unknown
default to GUILTY. The giveaway was on the row the whole time: it carries
`optimizer_factor: 0.8816`, which is stamped *after* both early returns, so the
function had plainly run and simply found `factor >= 1.0`.

Production holds `measured_bucket_skill_overlay.json` (generated
**2026-10-19T11:30:00Z**, expires 10-22, **62 validated of 3,985 tested**, FDR
q=0.10, 2,000 resamples, seed 20260914), and it contains:

```
soccer|player_shots|full|pregame|fair_method=book_margin_model
  verdict: skill_pocket   brier_diff -0.003909
  ci95 [-0.005833, -0.001944]   games 156   dates 10
```

The flagged rows are soccer `player_shots` with
`fair_method = book_margin_model`. So `bucket_factor` returns **1.0** and the
category demotion is **cancelled for that row** — verbatim what the docstring
says a validated pocket does, backed by 156 games over 10 dates with a CI that
excludes zero. **A validated bucket outranking its category is the design.**

## What stands from the 10-16 bug list

- **mlb strikeouts: WITHDRAWN.** Measured, calibrated, served at +1.54.
- The other families **stand**, for a reason I had not established on 10-16:
  their edges are served at `identity`, so raw edge *is* served edge — the NFL
  `rushing_yards` raw -40.00 reaches the board as -40.00. But "unshrunk" is not
  "unhandled": those rows are demoted in rank and in stake by the terms above.
- The bug list's framing should have been *"large edges whose only correction is
  a rank demotion"*, which is narrower and sharper than *"large edges"*.

## What is NOT shown here

- **No outcomes were used.** Whether shrinking strikeouts to the market is
  PROFITABLE is unmeasured, as is whether the rank-only treatment of the other
  families is sufficient. This is a provenance and mechanism reading only.
- Three rows, one pitcher, one slate. The load-bearing number is the 193-start
  skill sample, not today's n=3.
- Extending `market_shrink` to other cells is **not** indicated by anything
  here. 62 validated pockets exist; shrinking a cell with demonstrated skill
  would destroy real edges rather than absorb a bias — the `mechanism vs
  estimator` trap the engine standard names.

## The one thing worth carrying forward

`calibration_cell` is set on **6 of 2,714 measured rows**, and `skipped_no_fair`
on 59 NCAAF rows whose median raw edge is **25.20 points** — the largest
unshrunk magnitudes on the board, held back only by rank. That is the cell most
worth a skill measurement next, and unlike everything else in this document it
is a gap rather than one of my misreadings.

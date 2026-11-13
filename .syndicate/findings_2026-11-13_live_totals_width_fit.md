# Live full-game totals: fitting the model's over-confidence (todo #780, candidate fix 2)

- **Lane** `live-totals-prob-scale`, session 8062940b.
- **User** 2026-11-13 "Fit it now".
- **Substrate:** production. The fleet's live gameline ledgers, read on the fleet host at nice 19, against ESPN finals.
- **Script:** `scripts/live_totals_width_fit.py`.

## What was fitted

- **The transform:** P_k(over) = Phi(Phi^-1(P) / k).
  - Widening a normal predictive distribution by k around its own mean divides every line's z by k.
  - So k is the width fix with the mean left alone: an estimator, not a mechanism (`model_engine_standard.md` 4.4).
  - k = 1 is today's number.
- **P** is the ledger's `model_home_win_prob`. On a totals row that is P(over), the Agresti-Coull point the join
  priced.
- **Population:**
  - Totals / full rows with a model probability, priced or not, because this is the model's calibration.
  - One row per (event, state, line), matched to the ESPN final.
  - NCAAB dates >= 11-13 are never read: that is the PREREG_780 window.
- **Evaluation:** walk-forward by ledger date. Fit on every earlier date, then score the next. Brier is compared
  against k = 1, with game-clustered 95% intervals.

## Result (read 2026-11-13 ~15:30Z, ledger dates through 11-12)

| sport | graded states / games | pure width (error sd / implied sd) | its walk-forward Brier | k fitted | its walk-forward Brier | model - market Brier, k=1 -> k |
|---|---|---|---|---|---|---|
| NBA | 26,289 / 162 (10-20..11-12) | 1.07-1.42 | -0.003 +- 0.001 | **2.156** | **-0.006 +- 0.005** | +0.004 +- 0.012 -> -0.002 +- 0.010 |
| NCAAF | 94,505 / 325 (10-01..11-12) | 1.24-1.35 | -0.009 +- 0.002 | **2.482** | **-0.015 +- 0.006** | +0.012 +- 0.012 -> -0.004 +- 0.005 |
| NCAAB, all dates | 40,304 / 397 (11-02..11-12) | 1.07-1.36 | -0.002 +- 0.001 | 1.676 | -0.006 +- 0.005 | +0.009 +- 0.010 -> +0.003 +- 0.005 |
| **NCAAB, after #768** | 15,858 / 135 (11-09..11-12) | 1.02-1.47 | +0.000 +- 0.002 | 1.195 | **-0.001 +- 0.003** (2 dates) | -0.005 +- 0.017 |
| WNCAAB | 4,493 / 79 (11-03..11-12) | 1.01-1.39 | -0.000 +- 0.002 | 1.469 | -0.001 +- 0.012 | -0.014 -> -0.015 |

- **Stability:** NBA's walk-forward k held 2.13-2.16 over its last 8 steps, and NCAAF's 2.24-2.48 over 27.
- **NCAAB's k fell as post-fix nights entered**, 2.33 -> 1.73.

**WHY k IS LARGER THAN THE WIDTH GAP.** The fit regresses (final - line) on (model mean - line), by progress
(score / line):

| sport | < 0.40 | 0.40-0.75 | >= 0.75 |
|---|---|---|---|
| NBA | b 0.18 | 0.61 | 0.75 |
| NCAAF | 0.38 | 0.54 | 0.70 |
| NCAAB, all | 0.42 | 0.71 | 0.83 |
| NCAAB, after #768 | 0.60 | 0.92 | 1.05 |

- b < 1 means the model's distance from the line overstates what it knows, early in games most. In early NBA, 82%
  of the gap is noise.
- A pure width fix (k 1.1-1.4) helps a little. The fitted k also absorbs this information shortfall, and helps
  2-3x more.
- **It does not use the market price.** It tempers the model's own confidence toward 1/2, so every edge keeps its
  sign and its order and becomes smaller.

## What was built (on main, NOT LOADED: the user's decision)

- **`live_gameline_join._TOTALS_PROB_SCALE_BY_SPORT`:** NBA 2.16, NCAAF 2.48. Every other sport is 1, including
  NCAAB and WNCAAB, where the walk-forward shows no gain. Re-fit those two once more post-fix nights exist.
- **Where it applies:**
  - In `price_distribution_market`, after the Agresti-Coull point. The precision gate judges the scaled edge against
    the scaled sim error (delta method).
  - Full-game totals only. Segment totals were not fitted.
  - The display number (`live_display_block`) gets the same tempering, so the Live column and a price agree.
- **Switches:**
  - `SYNDICATE_LIVE_TOTALS_PROB_SCALE=off` turns it off.
  - `SYNDICATE_LIVE_TOTALS_PROB_SCALE_<SPORT>=<k>` sets one sport.
  - A junk value falls back to the table, not to off.
- **Ledger v7** records `prob_scale` and `model_home_win_prob_unscaled`, so the engine's own number is always
  recoverable.
- **Tests:** `tests/test_live_totals_prob_scale.py`, 36.
  - Reachability first (`off != on` through `attach_live_gamelines` and through the production caller
    `board_enrichment.attach_live_gamelines_for_sport`).
  - The table and the knob, the math, the scaled precision gate, and NCAAB / spreads / h2h untouched.
  - The display number on full-game rows only, and the ledger fields.
  - 7 source mutations, each caught.
  - 1,453 pass across the 72 test files that drive the join and the ledger. Two `v == 6` asserts became `>= 6`, because v7 is additive.

## Replay on production rows (fleet ledger, the new code's functions, read-only)

| sport | dates | priced rows | median priced \|edge\| | priced \|edge\| >= 20 pp |
|---|---|---|---|---|
| NBA (k 2.16) | 11-11..11-12 | 262 -> 256 | 14.6 -> 6.7 pp | 57 -> 7 |
| NCAAF (k 2.48) | 11-07..11-08 | 3,655 -> 3,553 | 20.6 -> 8.9 pp | 1,907 -> 339 |
| NCAAB (k 1) | 11-11..11-12 | 3,239 -> 3,239 | unchanged | unchanged |

**What it does to the board:** NBA and NCAAF live totals keep about the same priced coverage, and their claimed edges
roughly halve to what the record supports. It does not find edge: after the scale the model is about level with the
market on Brier. That is the honest reading of `#780`.

## What it does not touch

- **Spreads and moneylines.** `#780` found the same pattern there; that is a separate fit.
- **Segment totals.**
- **Real-money in-play orders.** They come from the book-consensus `ingame:` rule, not the join.
- **The PREREG_780 test (NCAAB).** NCAAB is unscaled. Its grade now reads `model_home_win_prob_unscaled` whenever it
  is present (amendment 1 in that registration), so a later NCAAB scale cannot change which games it selects.

## Loading

- **Steps:** a fleet ff to a SHA containing this, then a claimed refresh-worker restart. The join runs in
  refresh-worker, which has no uptime recycle.
- **Expected on load:**
  - NBA / NCAAF `LIVE_GAMELINE_JOIN` priceable stays within a few % of its pre-load share.
  - The ledger's NBA / NCAAF totals rows carry `prob_scale` 2.16 / 2.48 with `model_home_win_prob_unscaled` beside it.
  - The served NBA / NCAAF totals |edge| median falls by about half.
  - NCAAB is unchanged (`prob_scale` 1.0).
- **Falsified if** NBA / NCAAF priceable falls by more than 10%, or NCAAB moves at all.

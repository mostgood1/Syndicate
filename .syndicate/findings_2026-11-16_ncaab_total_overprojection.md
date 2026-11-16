# Findings — NCAAB totals: why the model pointed OVER on FAMU @ UTEP (11-16), and what is systematic

Lane `ncaab-total-overprojection`, session b1d2088f, 2026-11-16. User: "take a look at the FAMU UTEP NCAAB game that
just completed - place a bet on o136.5 based on guidance of our model the game ended at 125. This is WAY to big of a
difference. I need you to understand, learn, and optimize based on this". Hypotheses H1 / H2 were written into the lane
(`127a25343`) before any test. All reads are of the fleet (`~/syndicate-prod/data`), read-only; scripts in `C:\tmp\famu\`.

## The game (ESPN 401929419, OddsAPI 59707f15a9e28eda5e24ec2ed98664c7)

- Final: UTEP 79, FAMU 46 = **125** (halves 70 / 55; UTEP by 33). Tip 19:00Z (OddsAPI first listed 01:00Z 11-16).
- **Pregame** (`pregame_sim_2026-11-16.json`, computed 18:46:11Z): raw prior total 139.96 -> calibrated target 143.59
  (prior calibration as of 11-15: slope 0.716, prior mean 150.08, close mean 150.83, 633 games) -> sim mean **145.8**
  (sd 16.3, 200 sims), P(total > 136.5) 0.71. **Closing total 142.5** (median of 9 books' last pre-tip lines,
  `prior_calibration.closing_totals`). Model - close = +3.3. Pregame totals are served RAW (`college_game_projections._served`:
  "not applied: totals served raw"); margins are book-blended at weight 0. Layer 2 plays on the game included full-game
  overs at 141.5 / 142.5 / 143.5 / 144.5.
- **Live** (`live_gameline_ledger_2026-11-16.jsonl`, 294 full-game total rows): over 136.5 was priceable with edge
  +8.2 / +8.7 pp at 5-2 / 8-4 (19:11-19:12Z, model total 140.7, one book at 136.5) and +7.2 / +7.3 / +7.6 pp at 40-70
  (20:38-20:40Z; model total **137.23**, model margin 32.94; market fair P(over) 0.497; prob_std_err 0.035). From 110
  points the model expected 27.2 more; 15 came. The 2nd-half edge at the same line swung +7.6 to -10.6 within minutes.
  No paper or live entry was booked on this total (only h2h paper rows).

## H1 (live over-projects remaining points late in blowouts) — FALSIFIED, EXONERATED

383 games 11-02..11-16 joined to finals (597 with model rows; the unjoined are name mismatches). Per game, then across
games, `final - model_total_mean` by |margin| x progress (points / projected total): every bucket is -0.6..+2.8; late
blowouts +0.7..+2.3 (30+ / .75-.90: 70 games, model remaining 25.8 vs actual 26.7). The live mean is not biased high.
FAMU's 2nd-half miss (-12 remaining against an unbiased mean, between-game sd ~6.4) is ~2 sd: variance, not a defect.
Market residual (final - line, rows with fair P(over) 0.46-0.54) is -0.5..-3.7 in every bucket: live lines ran high.

## H2 (calibration pulls low totals above the close) — FALSIFIED as registered

621 games 11-02..11-16 with a pregame sim, a close and a final. `target - close` by raw-prior bucket: <135 +2.4 +- 0.95
(n 29), 135-140 -0.3 +- 0.8 (n 60, FAMU's), 140-160 within -0.1..+1.4, >160 +0.7. Pooled < 140: +0.6. The OLS fit of
close on prior is unbiased per bucket, as built.

## What the tests found instead

- **Pregame total disagreement carries no information beyond the close.** `(final - close) = a + b (model - close)`:
  **b = 0.017 +- 0.129** (621 games). Over-the-close hit rate when model - close is [3, 6): **0.393** (113 games);
  >= 6: 0.472 (106). Level: final - close **-2.2 +- 0.8**, model - close +0.8, so the model ran ~3.0 high of finals.
  This is the same finding that set the college margin blend to weight 0 (`+0.04, 116 games, 2026-11-03`), but
  totals are still served raw.
- **The live model does carry information, but its probabilities are overconfident and the market ran high.**
  Game-clustered, rows with fair P(over) 0.40-0.60: slope of (final - line) on (model - line) **b = 0.417 +- 0.086**
  (874 game-buckets). Mean final - line by (model - line): -5.1 (< -4), -3.7, -2.8, **-2.1 at [-1, 1)** (over hit
  0.390), -1.9, -1.3, +0.5 (>= 4, over hit 0.487). Rows the board marked priceable with |edge| >= 3: **OVER side hit
  0.472 over 129 games, UNDER side 0.707 over 131 games.** FAMU's 2nd-half row sat at model - line = +0.7, the bucket
  where overs hit 0.390, yet it claimed P(over) ~0.57: a 0.7-point disagreement read as +7 pp because the sim's
  remaining-points spread is too narrow (#780: 10-30%) and 200 sims add +-3.5 pp of noise.
- **The over/under asymmetry is mostly LEVEL, not skill.** Finals landed ~2 points under the live line even where the
  model agreed with it. A served probability that corrects the spread alone removes most small-gap over flags; one that
  also corrects the level would lean the board under for as long as finals keep landing below lines (a bet that this
  early-season pattern persists).

## Constraints on the fix

- Every line is its own decision (user rule, memory `feedback-every-line-its-own-decision`): no market-wide pause or
  withhold of college totals or of one side. The fix is a fitted, per-line probability calibration, refit on a trailing
  window, with its basis stamped on each row.
- A change to a served distribution is gated on outcomes at every checkpoint a price reads (learnings 2026-11-11, #784):
  holdout Brier / log loss vs the raw model and vs the market before any load.
- `ncaab-live-edge20-prereg` (the |edge| >= 20 pp cell, rated ~11-25) reads live NCAAB total edges: a load changes its
  population, so a load splits that test at the load time.

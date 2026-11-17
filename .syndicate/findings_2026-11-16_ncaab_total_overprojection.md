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

## Build (user "Spread + level", 2026-11-16) — todo #816

- **Form:** `logit p = logit p_mkt + a + c (logit p_raw - logit p_mkt)` per college full-game total line, pregame and
  live; a and c fitted per league x phase on graded games (trailing 21 days, floor 11-11), refit daily after 11:00Z by
  the pregame child, served only when the phase's walk-forward (>= 40 games) beats the raw model and is no worse than
  the market. Module `syndicate/features/college_basketball/total_prob_calibration.py`; switch
  `SYNDICATE_COLLEGE_TOTAL_CALIBRATION=off`.
- **The module's own fit on the fleet (read-only, as of 11-16):**

  | league / phase | a (level) | c (share) | games | walk-forward Brier market / raw / calibrated (games) |
  |---|---|---|---|---|
  | NCAAB live | -0.37 +- 0.14 | 0.23 +- 0.19 | 212 | 0.2295 / 0.2367 / **0.2197** (168) |
  | NCAAB pregame | -0.39 +- 0.14 | 0 (clamped from -0.05) | 222 | 0.2500 / 0.2804 / **0.2407** (174) |
  | WNCAAB live | +0.21 +- 0.26 | 0.29 +- 0.38 | 63 | held: walk-forward 20 games < 40 |
  | WNCAAB pregame | +0.02 +- 0.23 | 0 | 74 | held: walk-forward 29 games < 40 (and 0.2608 > market 0.2500) |

- **FAMU @ UTEP under the fit:** live 2nd-half row (engine 0.70 at 136.5, market 0.497) -> ~0.46, inside its own error:
  no flag. Pregame at the 142.5 close -> ~0.40 over: an under lean.
- **Team-level input (user question):** each team's earlier (final - close) this season does not predict its next
  game's: b = +0.04 +- 0.11 (396 games); with >= 2 prior games each +0.17 +- 0.20 (202); >= 3, -0.15 +- 0.24 (48).
  FAMU's three earlier games had gone OVER the close (+22.5, +1.5, +7.5), so a team-tendency term would have pushed
  this game further over. The team model already feeds the prior (raw prior 140 here, the lowest number in play).
  Re-test at ~8 games a team (~mid-December).
- **Money paths at load:** pregame execution is live and armed (band 0.40-0.75, cell gate on). Kalshi lists NCAAB
  moneylines only; Polymarket lists some NCAAB totals, so a calibrated NCAAB under can reach a real Polymarket order
  through the portfolio's gates. In-game live entries trade NHL spreads only.

## End-of-half / end-of-game failures (user 2026-11-16 ~6:55 PM CST: "Iona UMBC end game and PV/OSU end of half ... Thats now 3 that failed due to end game/end half situations. We need to find a solve for this")

- **Iona @ UMBC (final 67-75 = 142; halves 57 / 85):** every live full-game total row from 00:41Z priced off a model
  state 103-257 s old (`recorded_at - live_state_as_of`). At 60-70 (130 points, 00:47:57Z) the model projected 132.6; at
  65-72 (137 points, 00:50:17Z) 133.3 -- a final BELOW the points already scored. Under 138.5 was flagged at -17 to -18
  pp (served 0.25-0.31 against a ~0.49 market); the game went over.
- **Prairie View A&M @ Ohio State (1st half 29-34 = 63):** first-half total lines are not priced for NCAAB
  (`segment_pricing_disabled`); the end-of-half recommendations were full-game unders (~144.5, -8 to -9 pp) from a model
  state 136-182 s old as the half closed. (Still live at 10:18 2nd half when read; what was bet is to be confirmed.)
- **FAMU @ UTEP:** the 2nd-half row was fresh (22 s); that miss was a 0.7-point disagreement read as +7 pp, which the
  #816 calibration now removes.
- **Graded, all NCAAB ledger dates (priceable flags |edge| >= 3 against finals, game-weighted):** when the model's
  projected final is below the points already scored (654 of 79,209 full-game total rows; 455 flagged), UNDER flags hit
  **0.420 +- 0.044 (71 games)** -- the over flags there hit 1.000 (24 games) because their lines were already passed.
  Under flags by model-state lag: <= 60 s 0.643 (220 games), 60-120 s 0.631, 120-240 s 0.625, > 240 s **0.565** (189).
  Late flags are NOT worse in general: the last 10% of projected points hit 0.739 over (227) / 0.681 under (328).
  The failure is a STALE model in a fast-scoring endgame -- it has not counted the latest points, so it says under.
- **Mechanism available:** the NCAAB live lane already publishes the state it simulated from (`projection.homeScore /
  awayScore / period / clockSeconds`, `ncaab/live_resim.py` ~1020), but `live_gameline_from_lens` does not carry it to the
  pricer, and NCAAB's lane-age ceiling is 600 s (`_MAX_LANE_AGE_SECONDS_BY_SPORT`); the 30 s guard that exists
  (`_MAX_QUOTE_LAG_BEHIND_SCORE_SECONDS`) is for the QUOTE behind the score, not the model.
- **Proposed solve (not built):** a per-row `model_behind_score` refusal for live full-game totals and spreads -- refuse
  when the row's score is ahead of the model's simulated score inside an end-of-period window (<= 2:00 left in the 1st
  half, <= 5:00 in the 2nd half, any OT), and always when the projected final total is below the points scored; carry
  the model's state score / clock onto the ledger so the rule is graded. Follow-up: re-sim end-of-period games first so
  the model keeps up.

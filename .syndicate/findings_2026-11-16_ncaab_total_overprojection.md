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

## 2026-11-17 (9:20 - 10:30 AM CST): the end-game rule graded before building; #824 built; the level re-graded

Read-only grading of the fleet's NCAAB live-gameline ledgers, slates 11-08..11-16 (the score-change quote basis in force
throughout), priced full-game rows against ESPN finals and ESPN play wallclocks. Scripts: `C:\tmp\ncal816\endgame\
grade_guard.py`, `grade_guard2.py`, `grade_qage.py`, `grade_bydate.py`; the model's state score is the last ESPN play at
or before `live_state_as_of - 20 s`. Flag = |edge_pp| >= 3; hit vs the lean's own de-vigged price, game-weighted, SE
clustered by game. **The price is the ledger's quote at pricing; whether a bettor could still get it is not measured.**

- **The proposed window rule is FALSIFIED.** Totals flags priced while the board's score differed from the score the
  model simulated from, inside the last 2:00 of the 1st half / 5:00 of the 2nd / OT: 2,910 records (11.3%), 285 games,
  flags hit **0.648 vs a 0.533 price (+11.5 +- 1.8 pp)**, overs +10.7 +- 2.9, unders +14.3 +- 2.2. Spreads the same way
  (+6.9 +- 1.7 pp, 285 games); h2h +4.8 +- 2.8. Judging the window on the clock at pricing instead changes nothing
  (+11.9 +- 1.7). Refusing them would cut flags that beat their price. Not built.
- **"The quote saw a basket the model had not" is not a loser either** (a scoring play in (state, quote]): totals
  window unders +13.0 +- 2.7 pp (221 games), midgame unders +8.5 +- 2.4; spreads and h2h within noise of the rest.
- **Only the contradiction loses.** Totals by the model's projected final minus the points on the board: **< 0** (the
  final is below the score): unders **0.430 vs 0.520 (-8.9 +- 5.6 pp, 47 games)**, overs 18 of 18 on lines the game
  had already passed; 0-3 points: unders +15.3 +- 4.1, overs +18.4 +- 7.1; 3-6, 6-10, 10-20: all +14 to +30. The 11-16
  read over every ledger date agrees (unders 0.420 +- 0.044, 71 games). 128 graded records, 0.5% of priced totals.
- **So the end-game solve is the contradiction only (#824, built):** `live_gameline_join.model_behind_score_verdict`
  refuses a college full-game TOTAL whose projected final is below the board's points, after the quote and lane gates,
  through `_apply_verdict` (no edge, no Live number, the reason on the ledger). Absent score or projection refuses by
  name (0 of 28,792 priced records lacked either). Switch `SYNDICATE_LIVE_MODEL_BEHIND_SCORE_GUARD` on (default) /
  shadow / off. The lane's start state (`projection.homeScore/awayScore/period/clockSeconds`) now reaches every ledger
  record (`state_home_score`, `state_away_score`, `state_period`, `state_clock_seconds`), so the window question can
  be re-graded on the real state instead of an ESPN reconstruction.
  - **What it covers:** Iona @ UMBC (133.3 projected, 137 scored, under 138.5 at -17 pp). **What it does not:** PV @
    OSU's end-of-half full-game unders (a model 136-182 s behind, not a contradiction): that population beat its price
    on 11-08..11-16, so nothing here refuses it. One loss does not overturn it; the new state fields will re-grade it.
- **The level re-graded (it is NOT quote staleness).** Finals minus the live price on priced totals, by quote age at
  pricing: <= 30 s -6.3 +- 2.6 pp (237 games), 30-60 s -6.1, 60-120 s -5.1, 120-240 s -6.9, > 240 s -4.0. The under
  lean is there on fresh quotes too.
  - **By night:** 11-08 +8.5, 11-09 -5.8, 11-10 +2.3, **11-11 -8.5, 11-12 -12.7, 11-13 -7.5, 11-14 -11.8, 11-15
    -10.2**, 11-16 (pre-load, 7 games) +3.6, **11-16 post-load +9.1 (19 games)**. Night-clustered over the 9 pre-load
    nights: -4.7 +- 2.5 pp; 6 of 9 below zero; every night since the engine floor (11-11) was -7.5 or lower until 11-16.
  - **Walk-forward on the fleet, through 11-16 (read-only refit, `C:\tmp\ncal816\wf_compare.py`), live, 188 games:**
    spread + level **0.2240**, spread only 0.2281, market 0.2296, raw 0.2376. The level won 4 of 5 scored nights and
    lost 11-16 (0.2558 vs spread-only 0.2322). Pregame: spread only fits c = 0, so it serves the market (0.2500, no
    edges); spread + level 0.2441.
  - **The daily refit already moved:** fit file as_of 11-16 (written 11:09:27Z 11-17) live a -0.358 -> **-0.288**,
    c 0.226; pregame a -0.379 -> -0.317. Tonight's games read it.
  - **Reading:** the level is supported by four out-of-sample nights against one; my 11-17 00:xx recommendation to drop
    it rested on that one night. Spread-only is BUILT (`fit(level=False)`, `refresh(level=...)`, `FIT_LEVEL`, default
    True = the user's choice), so dropping the level later is a one-line flip, a refresh-worker restart and a refit.
- **Money:** every NCAAB order in the November execution-ledger archive is paper (no live-mode row since 11-14 for any
  sport in that file, so live orders are recorded elsewhere and this does not prove none were placed).

## #816 7-day grade, PRE-REGISTERED (2026-11-17 ~12:55 PM CST, user "run the #816 7-day grade"; written before any 11-17 evening tip, with a few 11-17 day games in progress and none graded)

The calibration loaded 2026-11-17 00:04:20Z, so one post-load night (the 11-16 slate's late games) is in. That night is
known (calibrated under flags 23-40, rail monitor) and is reported DESCRIPTIVELY, outside the registered window.

- **Window:** NCAAB slates 2026-11-17 .. 2026-11-23 (7 nights). WNCAAB is graded only on slates where its phase is
  calibrated (its gate held it on 11-17); descriptive.
- **Script:** `scripts/grade_college_total_calibration.py --league ncaab --from 2026-11-17 --to 2026-11-23` (this commit),
  run on the fleet under refresh-worker's environ on **Tue 2026-11-24 at or after 10:00 AM CST** (scheduled task
  `college-total-cal-grade-816`). Per slate: the calibration IN FORCE for that slate (newest fit dated before it)
  applied to every live full-game total row of the slate; the spread-only counterfactual fitted on the same trailing
  window; each game's rows weigh 1; SE game-clustered, night-clustered printed beside it.
- **Tests (live unless named):**
  - **T1** served vs market: mean per-game Brier(served) - Brier(market). PASS if <= 0; FAIL if > 0 with the 90% game-
    clustered CI above 0.
  - **T2** served vs the engine: Brier(served) - Brier(raw). PASS if < 0.
  - **T3** level vs spread only: Brier(served) - Brier(spread_only). RECOMMENDS THE FLIP if > 0 with the 90% game CI
    above 0 AND the night-clustered mean > 0.
  - **T4** flags (|served - market| >= 3 pp) by lean: hit - fair per game, pooled. A side FAILS if its 90% CI is
    entirely below 0.
  - **T5** pregame at the close: Brier(served) - Brier(market = 0.25). PASS if <= 0.
- **Verdicts:**
  - **KEEP (spread + level)** if T1 and T2 pass and T3 does not recommend the flip.
  - **FLIP TO SPREAD ONLY** (`FIT_LEVEL = False`, refresh-worker restart, refit) if T3 recommends it, or if T1 FAILS
    while the under side FAILS T4.
  - **TURN THE CALIBRATION OFF** only if T2 fails (served worse than the engine's own number).
  - Anything else: **INCONCLUSIVE** -- keep as is and extend by 7 slates under the same rules.
- Any load that changes the served live total probability inside the window splits it at the load time.

## #816 7-day grade — RESULTS (Tue 2026-11-24, run 10:04:26-10:05:13 AM CST; scheduled task `college-total-cal-grade-816`; read-only)

**VERDICT by the registered rules: FLIP TO SPREAD ONLY** (T3 recommends it). Not loaded; the user decides. Nothing on
the fleet, in `FIT_LEVEL` or in `SYNDICATE_COLLEGE_TOTAL_CALIBRATION` was changed.

- **How it ran (as registered):** `scripts/grade_college_total_calibration.py --league ncaab --from 2026-11-17 --to
  2026-11-23 --json /mnt/c/tmp/college_total_cal_grade/result.json`, ONCE, from worktree
  `C:\tmp\syndicate-sessions\college-total-cal-grade-816` at origin/main `7cf6d12a5` (`git ls-tree HEAD` blob
  **cf1ef20b44a2** = the registered script from `47d504ea2`), fleet python `/usr/bin/python3.11` under refresh-worker's
  environ (pid 753771, 276 keys passed through `env -i`, no value printed), `nice -n 19`, rc 0. Output:
  `C:\tmp\college_total_cal_grade\result.json` / `.txt`.
- **Preconditions:**
  - (a) all 7 slate ledgers present on the fleet (`ncaab_source/data/live_gameline_ledger/live_gameline_ledger_<d>.jsonl`,
    11-17 .. 11-23: 24,161 / 36,050 / 17,793 / 31,260 / 24,121 / 17,484 / 20,093 lines). **No date excluded.**
  - (b) fit files as_of 20261116 .. 20261122 all present (each written ~5:0x AM CST the following day).
  - (c) loads 11-17..11-24 touching `total_prob_calibration.py` / the live join's totals step / `_served`:
    - `3dbe53df0` #824 (18:03:56Z 11-17): refuses contradiction rows; it does not move a priced row's probability, and
      it loaded BEFORE this pre-registration was written (18:55Z). No split.
    - `923869cf3` I-17 (08:02:54Z 11-18) and `d78a448c4` (04:58:14Z 11-19): the displayed calibrated TOTAL only
      (deploys.md: "No served probability, flag, rank or stake reads either"). No split.
    - `36a9f5501` gate fallback (14:42:44Z 11-18): a FAILED phase serves the market instead of raw. NCAAB live passed
      its gate on every fit in the window, so the live served probability did not change (deploys.md: "NCAAB live is
      unchanged"). It DID change pregame: from the 11-18 slate every pregame fit failed and serves the market
      (a = c = 0, `fallback: market`). The script reads `calibration_for` with this rule, which matches what was served
      from the load on. No live split; noted for T5.
    - `52e68382a` #836 (absent = shadow) and `75a787964`/`8acee817d` #847 (default off; 0 `SYNDICATE_CELL_CALIBRATION_*`
      keys on the fleet, deploys.md 2026-11-19 04:58:14Z): no served-probability change. The 11-24 08:30Z batch is after
      the window (no live college game at its load) and does not touch these files.
    - **Window NOT split.**
  - (d) blob cf1ef20b44a2 confirmed.
- **Population:** LIVE 284 NCAAB games over 7 nights (every live full-game total row, each game weighing 1); PREGAME 316
  games at the close. WNCAAB not graded (registered as descriptive only on calibrated slates; the task ran NCAAB only).

### Tests

| test | reading | rule | result |
|---|---|---|---|
| **T1** served − market (live Brier) | **+0.00149**, 90% game CI [−0.00192, +0.00490] (se 0.00207); night-clustered +0.00057 (se 0.00313, 7 nights) | PASS if <= 0; FAIL if > 0 with CI above 0 | **NOT PASS, NOT FAIL** (> 0, CI spans 0) |
| **T2** served − raw | **−0.00351**, CI [−0.00934, +0.00231]; night-clustered −0.00302 (se 0.00395) | PASS if < 0 | **PASS** |
| **T3** served − spread only | **+0.00484**, CI **[+0.00230, +0.00737]** (se 0.00154); night-clustered **+0.00424** (se 0.00261) | FLIP if > 0, CI above 0 AND night mean > 0 | **RECOMMENDS THE FLIP** |
| **T4** flags by lean (|served − market| >= 3 pp), hit − fair | OVER 235 games: 0.702 vs 0.538, **+16.4 pp [+12.3, +20.4]**; UNDER 276 games: 0.548 vs 0.514, **+3.4 pp [−0.3, +7.0]** | a side FAILS if its CI is entirely below 0 | **no side fails** |
| **T5** pregame at the close, served − market (0.25) | served 0.25481 vs 0.25 (raw 0.26128): **+0.00481**, CI [+0.00173, +0.00790], 316 games | PASS if <= 0 | **FAIL** (not a verdict input) |

Pooled live Brier: market 0.23805, raw 0.24305, served 0.23954, spread only **0.23470**.

**Verdict walk:** KEEP needs T1 PASS (it did not) and T3 not recommending (it does). FLIP TO SPREAD ONLY: T3
recommends it -> **FLIP**. TURN OFF only if T2 fails (it passes).

### By night (live, NCAAB)

| slate | games | market | served | spread only | fit in force (live a / c; as_of) |
|---|---|---|---|---|---|
| 11-17 | 53 | 0.2387 | **0.2539** | 0.2359 | −0.2884 / 0.226 (11-16) |
| 11-18 | 59 | 0.2353 | 0.2344 | 0.2314 | −0.1594 / 0.2497 (11-17) |
| 11-19 | 25 | 0.2361 | 0.2423 | 0.2336 | −0.1179 / 0.2735 (11-18) |
| 11-20 | 48 | 0.2350 | 0.2314 | 0.2298 | −0.0698 / 0.2812 (11-19) |
| 11-21 | 47 | 0.2469 | 0.2467 | 0.2468 | −0.0421 / 0.3049 (11-20) |
| 11-22 | 23 | 0.2399 | 0.2286 | 0.2284 | −0.0424 / 0.2883 (11-21) |
| 11-23 | 29 | 0.2333 | 0.2320 | 0.2336 | −0.0403 / 0.3137 (11-22) |

Spread only beat served on 6 of 7 nights (11-23 the exception, by 0.0016). Spread-only c per slate: 0.261, 0.268,
0.287, 0.290, 0.311, 0.294, 0.319.

### Fits in force per slate (a, c)

- **Live:** see the table; every slate `level: fitted`, `fallback: null`; games 232 -> 487. **The daily refit's own level
  shrank from −0.288 to −0.040 across the window**: by 11-21 the served fit was already close to spread only, which is
  why the last three nights are near-ties and the gap is carried by 11-17..11-19.
- **Pregame:** 11-17 slate a −0.3174 / c 0 (as_of 11-16, passed its gate); **11-18 .. 11-23 every fit FAILED its gate ->
  `fallback: market`** (a 0, c 0). So from 11-18 the served pregame probability IS the market, and T5's +0.00481 is
  carried by the 11-17 slate (inference from the fits: a = c = 0 gives served = market exactly on those slates; the
  script does not print T5 per slate and was run once, so the 11-17 share is not separately measured).

### 11-16 (DESCRIPTIVE, outside the window, known before registering)

`--from 2026-11-16 --to 2026-11-16`, same environ, rc 0 (`night_1116.json`). Fit in force as_of 11-15 (live a −0.3583 /
c 0.2294). 21 live games: market 0.2319, raw 0.2454, served **0.2558**, spread only 0.2322; served − market +0.0239
[+0.0024, +0.0454]; flags: over 5 games 1.000 vs 0.579, under 21 games 0.415 vs 0.504 (−8.9 pp [−21.3, +3.4]). Pregame
22 games: served 0.2673 vs 0.25. It matches the pre-registration's smoke run (served 0.2558, spread only 0.2322, market
0.2319).

### Reading (not part of the verdict)

- The level hurt most when it was large (11-16 and 11-17, a ≈ −0.3) and was close to harmless once the refit had walked
  it to ≈ −0.04. Spread only would have beaten it over the window by 0.0048 Brier per game, and it is the version that
  beats the market (0.2347 vs 0.2381); served does not (+0.0015, inside noise).
- Under flags no longer lose (+3.4 pp, CI touching 0); over flags are strong (+16.4 pp). The 11-18 "under flags 0.426"
  worry (rail monitor, 48 games) did not persist over 276 games.
- FLIP means: `FIT_LEVEL = False` on main, a drained, claimed refresh-worker restart, then rewriting the in-force fit
  file with `scripts/fit_college_total_calibration.py`. It is a **betting change** (it moves live NCAAB total flags), so
  it loads in a betting-change window (next: Tue 2026-12-08 2-7 AM CST; it is already on the 12-08 candidate list) unless
  the user classes it as a risk reduction.

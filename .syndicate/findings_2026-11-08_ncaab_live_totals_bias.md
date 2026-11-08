# NCAAB live totals run low: the engine's NBA blowout rule covers the whole college second half (2026-11-08)

Lane `ncaab-live-totals-bias`, session 6df1b15d. Read-only; nothing deployed, no env changed. Written 2026-11-08,
12:46 PM CST (18:46Z).

**Substrates.**
- Fleet live-gameline ledgers (`<data>/ncaab_source/data/live_gameline_ledger/`) and pregame sims
  (`.../pregame_sim/`), copied read-only at 17:45Z / 17:51Z. Both are production's own writes.
- ESPN finals (scoreboards and game summaries).
- The engine probe and the harness run are evidence about the CODE. They use main `e2b7b2f45`, whose sim path is
  identical to the fleet's `a3d72c82b` (the only diff in `ncaab/live_resim.py` is the score-change metadata). They read
  the fleet data root read-only, with live-odds-worker's three college switches copied from its `/proc` environ
  (names only printed).

**Scripts.**
- `scripts/ncaab_live_totals_bias.py`: ledger attribution, both leagues.
- `scripts/ncaab_blowout_resume_probe.py`: engine probe.
- `scripts/backtest_basketball_intervals.py` (#765's harness): run `ncaab2026_blowout_off`.

## Answer

1. **The cause is the engine's blowout rule. It takes about 2 points from every lopsided resumed game's remaining
   total.**
   - `basketball_engine/engine.py:2246-2250` sets `blowout` for a period when `q >= N_PERIODS and |margin| >= 15`,
     or `q >= second_half_first_period and |margin| >= 18`. For NBA that is the fourth quarter.
   - NCAAB has `N_PERIODS = 2`, so it is the WHOLE second half. It is decided by the margin at the half, or at the
     resume point inside it.
   - A blowout period runs:
     - possessions 8% longer (`_contextual_duration_scale`, `:425`);
     - make probability x0.96 (`garbage_time_eff_scale`, `:1936` / `:2066`);
     - turnovers x0.94 (`garbage_time_pace_scale`, `:1823`);
     - bench-weighted minutes (`_contextual_minutes_weights`, `:393`).
   - Real college blowouts do not slow down until the closing minutes.
     - In h2 states with the flag on, the halves scored ABOVE the prior's rate (prior error −1.22 ± 0.58, 715 states
       / 111 games).
     - With more than 4 minutes left: −0.9 to −2.5.
     - Only in the last 4 minutes do they run below it.
2. **The early-season prior is not low.**
   - Over every graded pregame entry, the prior target minus the final is **+0.01 ± 1.06** (279 games, 11-02..11-07;
     139 of 279 finals below it). The pregame sim's total is +0.40 ± 1.05.
   - Final regressed on the target: slope 0.80 ± 0.14 (234 games), mean target 151.0 against mean final 150.8.
3. **End-game fouling is not the cause.** It is a small secondary cell.
   - The final 2 minutes run −1.12 ± 0.68 (182 states / 108 games), the closest phase to 0.
   - Games 6-10 points apart with ≤ 4 minutes left run −2.03 ± 0.83, but that is 59 of 2,431 states (2.4%).
4. **Overtime was a defect, now fixed.** Before `b9999dc1d` (loaded 11-05 22:37:41Z), the full-game total left out
   the overtime points of sims that went to OT, and states resumed IN overtime read −11.9 (9 states / 3 games).

## Reproduction (`college_quote_order_by_score_change.py`, same work dir, same ledger copies)

Priced full-game totals rows recorded before the quote-order gate (2026-11-07 16:29:14Z), 11-02..11-06. The
findings file's rows are reproduced exactly:

| quote vs state | n / games | model − final | line − final | model − line |
|---|---|---|---|---|
| within 30 s | 1,680 / 151 | **−3.41 ± 1.10** | −1.15 ± 1.09 | **−2.26 ± 0.50** |
| older > 30 s | 7,646 / 179 | −2.57 ± 0.92 | −0.23 ± 0.95 | −2.34 ± 0.37 |
| newer > 30 s | 10,876 / 193 | −1.43 ± 1.00 | +0.37 ± 0.91 | −1.80 ± 0.41 |

- `model − line` is the clean statistic. The final is common noise to both, so the gap with the book is far tighter
  than either error. **The model sits about 2 points below the book in every bucket, each beyond 4 SE.**
- The bucket differences in `model − final` are mostly the books' own: the within-30 s rows' games went over the
  book as well.
- SEs are game-clustered throughout.
- `model − line` comes from `ncaab_live_totals_bias.py`. It filters on the state time rather than `recorded_at`, so its
  n is 1,681 / 7,653 / 10,879, 1-7 rows off. Its `model − final` matches to the second decimal.

## Dates after 11-06, and the censoring

- Ledgers copied through 11-08 (37 KB; 1 priced totals row since the workers=2 load).
- From 2026-11-07 16:29:14Z, rows whose quote is more than 30 s older than the state are refused and never written.
  So every post-gate row is a SELECTED subset: quote within 30 s or newer.
- **Handling:**
  - every table splits `pregate` from `censored` and never pools them;
  - the post-gate rows are compared only with the pre-gate buckets the gate admits (within / newer);
  - the attribution rests on the pre-gate rows.
  - The selection is on quote timing, not on game state, so it should not bias the per-state engine reading. It
    does change which games appear (40 on 11-07).
- **11-07 (post-gate, 40 games):**
  - priced totals model − final −3.89 / −5.01 (newer / within), model − line −1.46 ± 1.04 / −3.11 ± 1.02;
  - the engine signature replicates: h2 flag-on live update **−2.23 ± 0.53** (41 states / 13 games) against
    +0.77 ± 0.32 with the flag off;
  - but that day's games out-scored their prior (prior error −4.24 ± 1.49; pregame target − final −3.10 ± 2.49 on
    48 games). That is the day's outcomes, not a persistent prior defect (see 2).
- **Coming change:** the score-change quote rule (`711e299d6`, lane `ncaab-live-resim-capacity`) loads at
  live-odds-worker's recycle (~21:28Z 11-08). It re-admits rows with no score change between quote and state, so
  post-gate censoring changes again from that time. Any re-read must split on it.

## Attribution: one row per lane state

Population P2: every DISTINCT re-sim state (game, `live_state_as_of`) in any full-game record that carries
`model_total_mean`, priceable or not. That is 2,431 pre-gate states over 192 games (11-02..11-06) and 393 post-gate
states over 41 games (11-07).
- Each state is placed on the clock by the ESPN play it resumed from: the last play at or before the state time
  with the record's score.
- The error splits exactly:
  - **live update** = model remaining − PRIOR remaining, where PRIOR remaining is the engine's own pregame targets
    (`pregameTotal` x 0.4743 / 0.5257 per half, `half_targets`) pro rata over the time left;
  - **prior error** = PRIOR remaining − actual remaining.
- So model − final = live update + prior error.

**By score margin at the state, pre-gate:**

| \|margin\| | states / games | model − final | live update | prior error |
|---|---|---|---|---|
| 0-5 | 643 / 115 | −0.75 ± 1.54 | +0.45 ± 0.16 | −0.94 ± 1.51 |
| 6-10 | 478 / 134 | +0.76 ± 1.55 | +0.04 ± 0.15 | +0.77 ± 1.52 |
| 11-14 | 279 / 96 | −2.75 ± 1.42 | −0.65 ± 0.17 | −1.98 ± 1.41 |
| **15-19** | 312 / 94 | **−3.96 ± 1.09** | **−2.28 ± 0.17** | −1.46 ± 1.04 |
| **20+** | 719 / 93 | **−4.14 ± 0.89** | **−2.24 ± 0.10** | −1.89 ± 0.85 |
| all | 2,431 / 192 | −2.09 ± 0.96 | −0.90 ± 0.14 | −1.07 ± 0.92 |

**Second half, by the engine's own blowout flag** (the flag is fixed for the rest of the half at the resume point):

| h2 states | states / games | model − final | live update | prior error |
|---|---|---|---|---|
| flag ON (\|m\| ≥ 15) | 715 / 111 | **−3.23 ± 0.61** | **−1.97 ± 0.09** | −1.22 ± 0.58 |
| flag off | 560 / 93 | −1.34 ± 1.34 | +0.69 ± 0.16 | −1.96 ± 1.35 |

- **The same in every engine epoch.** The h2 flag-on live update is:
  - −2.08 ± 0.25 before the prior calibration (E0, < 11-03 19:41:57Z);
  - −1.68 ± 0.14 with the efficiency bounds and no OT (E2, to 11-05 22:37:41Z);
  - −2.11 ± 0.12 with OT counted (E3);
  - −2.23 ± 0.53 post-gate on 11-07.
  - So it is not a passing calibration state.
- **The step sits exactly at the engine's threshold.** In h2 states with more than 8 minutes left:
  - live update −0.66 ± 0.32 at \|m\| 11-14 (66 states / 35 games);
  - **−2.11 ± 0.28 at 15-19** (106 / 47);
  - a step of **−1.45 ± 0.43**.
  - Real basketball has no discontinuity at 15. The engine does.
- **First-half states with \|m\| ≥ 15 lose about 3 points of live update** (15-19 −2.71 ± 0.24, 20+ −3.01 ± 0.16),
  because the engine flags most of their simulated second halves.
- **By phase it is flat, not end-loaded.** model − final runs −1.7 to −1.8 through the first half, −2.7 / −3.3 /
  −2.5 in h2 with 14-20 / 8-14 / 4-8 minutes left, then −1.2 / −1.1 in the last 4 minutes.
- **Pace.** Games running faster than the prior read lower: model − final −4.76 ± 1.32 at pace 1.05-1.15 (416 /
  82) and −4.30 ± 1.66 at ≥ 1.15 (192 / 47).
  - That is mostly prior error: −3.39 ± 1.25 (2.7 SE) and −2.62 ± 1.59.
  - The live update adds −1.37 / −1.68, because fast games are often the lopsided ones.
  - So hot games kept scoring above the prior rate this week. #765 measured on 5,000+ games of 2025-26 that pooling
    observed pace LOSES to the line at every checkpoint, so this is a lead to re-test in-season, not a fix.
- **Prior source** makes no difference: prior-season fallback teams −0.93 ± 0.18 live update vs current-season
  −0.87 ± 0.22.

**The books agree.** On the priced totals rows (P1, pre-gate, 20,213 rows / 193 games):

| state | model − line | model − final | line − final |
|---|---|---|---|
| h1, \|m\| < 15 (5,902 / 166) | −0.84 ± 0.52 | +0.07 ± 1.47 | +0.92 ± 1.37 |
| h1, \|m\| ≥ 15 (2,498 / 84) | **−4.02 ± 0.69** | −6.38 ± 1.48 | −2.36 ± 1.35 |
| h2, flag off (5,142 / 113) | −1.22 ± 0.40 | −0.48 ± 1.17 | +0.74 ± 1.25 |
| h2, flag ON (6,300 / 131) | **−2.74 ± 0.37** | −3.08 ± 0.67 | −0.33 ± 0.67 |

- In blowout second halves the book is right on the final (−0.33 ± 0.67) and the model is 3 points low.
- In close second halves the model is nearer the final than the book.

## The engine probe (code, not deployment)

`scripts/ncaab_blowout_resume_probe.py` setup:
- Real 2026-27 games, sampled evenly from the 11-05..11-07 pregame artifacts.
- Production's engine inputs (`build_engine_inputs`: dated ratings, player priors, prior calibration), and
  live-odds-worker's three college switches.
- 100 sims, nice 19.
- Each state was resumed under three configs:
  - `prod`;
  - `no_scales` (`garbage_time_pace_scale` = `garbage_time_eff_scale` = 1.0);
  - `no_blowout` (`blowout_margin` = `blowout_q4_margin` = 999).
- Leads alternate between home and away. SE is over games.

**At the half** (first half scored at its prior share), second-half points against the prior's h2 target, 30 games:

| lead at the half | prod − prior h2 | no_blowout − prior h2 | prod − no_blowout | of which the scales |
|---|---|---|---|---|
| 0 | +0.93 ± 0.22 | +0.93 ± 0.22 | 0.00 (identical draws) | 0.00 |
| 8 | +0.94 ± 0.25 | +0.94 ± 0.25 | 0.00 | 0.00 |
| **16** | −1.17 ± 0.23 | +0.77 ± 0.21 | **−1.94 ± 0.26** | −1.13 ± 0.23 |
| **24** | −1.81 ± 0.20 | +0.06 ± 0.21 | **−1.87 ± 0.21** | −1.34 ± 0.21 |

- The rule takes about **1.9 points from a full college second half** once the lead is 15+.
  - The garbage-time scales are 58-72% of that.
  - Bench minutes plus the x1.08 possession length are the rest.
- Below 15 the draws are identical: the flag never fires. That is the reachability check (off ≠ on only where the
  rule applies).
- The +0.93 in close halves is production's end-game fouling. Blowouts never get it, rule or no rule (+0.06 at 24
  with the rule off).

**At the tip** (the pregame sim), 20 games:
- prod − target **+0.61 ± 0.50**; no_blowout − target +1.22 ± 0.45.
- **Rule off raises the pregame total by +0.61 ± 0.36**, more for lopsided matchups, whose simulated second halves
  are often flagged.
- This is the re-fit obligation below.

**10:00 left in the first half** (first half scored pro rata at its prior share), remaining points, 20 games:
- the rule takes −0.14 ± 0.22 at an even game (n.s.);
- **−0.92 ± 0.35** at a 16-point lead;
- **−1.61 ± 0.33** at 24, through the simulated second halves it flags.
- Rule off, the remaining points sit +0.14 to +0.69 over the prior's rate at every margin.

**Live states lose more than a pro-rata share of the halftime cost.**
- By time left in h2, the flag-on live update is:
  - −2.71 ± 0.20 (14-20 min);
  - −1.95 ± 0.16 (8-14);
  - −2.00 ± 0.16 (4-8);
  - −1.49 ± 0.21 (2-4);
  - −1.24 ± 0.21 (≤ 2).
- Flag off, it is −0.11 / +0.54 / +1.14 / +0.88 / +1.28. The end-game fouling grows as the clock runs down.
- So the probe's pro-rata cost is a LOWER bound on what the rule takes from real states. The #765 harness run below
  re-sims real states.
- **What real blowouts do, by the same split:**
  - with more than 4 minutes left they score ABOVE the prior rate (prior error −2.19 / −2.47 / −0.94);
  - in the final 4 minutes they do slow (+0.52 ± 0.42 / +0.95 ± 0.21), where the engine's cut is about the right
    size (model − final −1.06 ± 0.43 / −0.30 ± 0.31).
  - **The rule's mistake is its SCOPE.** NBA's fourth-quarter rule became the whole college second half, which is
    20 minutes, not the closing few.

## Proposed fix, and its expected effect

**Smallest fix: switch the blowout regime off for NCAAB.** No code. Two `EventSimConfig` fields go into
live-odds-worker's `SYNDICATE_NCAAB_LIVE_MECHANISMS`
(`LIVE_ODDS_WORKER__SYNDICATE_NCAAB_LIVE_MECHANISMS` in `local_production.env`):

    "blowout_q4_margin": 999, "blowout_margin": 999

- **Why it is safe to scope:**
  - `live_mechanisms_from_env` (`ncaab/live_resim.py:460`) accepts any `EventSimConfig` field.
  - `build_engine_inputs` applies it to `league == "ncaab"` only (`:360`), so women's, NBA and WNBA are untouched.
- **What it reaches:** the live re-sim AND the college pregame sims. The pregame `inputs_key` carries the mechanism
  names, so every men's pregame game re-sims once.
- **Loading it:** env is built only at `up`, so this needs a drained full `down`/`up`: lane, three claims,
  origin/main preflight with `--reinject-env`, joint CLEAR.
- **A lighter-deploy alternative:** an NCAAB default in `build_engine_inputs` behind a switch, loaded by a fleet ff
  plus a live-odds-worker TERM (or its own ~6 h recycle). That edits `ncaab/live_resim.py`, so it needs a loan from
  lane `wncaab-module` and must stay clear of `ncaab-live-resim-capacity`'s #762 sections.
- **Not done here:** both need the user's yes.

**Expected effect, measured on the same rows** (`ncaab_live_totals_bias.py --penalty=`: each state's projection plus
the points the probe says the rule took, at its margin, pro rata to the h2 time left). Because live states lose more
than the pro-rata cost (above), these are LOWER bounds:

The penalty table was `{"half": {16: 1.94, 24: 1.87}, "h1mid": {0: 0.14, 16: 0.92, 24: 1.61}}`. It interpolates
linearly in the margin, h2 states pro rata to the time left; overtime gets 0. The comparison is on the same rows:
the 19,906 priced rows / 192 games whose state could be placed on the clock.

| pre-gate rows | model − line today → rule off | model − final today → rule off |
|---|---|---|
| all | −1.95 ± 0.34 → **−1.40 ± 0.32** | −1.92 ± 0.89 → −1.37 ± 0.88 |
| within 30 s (1,658 / 150) | −2.22 → −1.66 | −3.32 → −2.77 |
| h2 flag ON (6,300 / 131) | −2.74 → −1.91 | −3.08 → −2.24 |
| h1, \|m\| ≥ 15 (2,498 / 84) | −4.02 → −2.74 | −6.38 → −5.10 |
| h2 flag off, h1 \|m\| < 15 | unchanged (−1.22 / −0.84) | unchanged |

- Lane states (P2, 2,482 / 194): model − final −2.09 → **−1.54**; at \|m\| 15-19 −3.96 → −2.96; at 20+ −4.14 → −3.19.
- Post-gate 11-07 (40 games): model − line −1.76 → −1.44.
- **Upper side.** Flag-on live states sit −1.97 below the prior rate, against a pro-rata probe cost of about 0.9.
  If the whole of that gap is the rule, the headline moves about +0.9 rather than +0.55. The harness run re-sims real
  states and decides between the two.
- **What is left after the fix is mostly not model error:**
  - In close second halves the model is nearer the final than the book: model − final −0.48 ± 1.17 against line −
    final +0.74 ± 1.25.
  - Lopsided first halves keep scoring above the prior (prior error, n.s. at the state level). The prior target is
    level over the whole slate (+0.01 ± 1.06).

**What switching it off costs.** In the final 4 minutes real blowouts do slow (prior error +0.52 / +0.95). With the
rule off, the model would run about +0.5 to +1 high on those states, where it is about right today (−1.06 / −0.30).
- That is the case for the BETTER fix, as a follow-up: keep the rule but give it a clock window. Add a new
  `EventSimConfig` field, e.g. `blowout_window_s`, defaulting to the whole period (byte-identical for NBA/WNBA).
  Set NCAAB to the final ~240 s of regulation through the same env.
- That is an `engine.py` change (lanes `basketball-scenario-calibration` and `wncaab-module` hold loans there) and a
  new mechanism, so it carries §4.4's re-fit too.

**Re-fit obligations (engine standard §4.4): what was absorbing the rule?**
1. **The pregame tip total.**
   - Rule off raises it +0.61 ± 0.36 (probe, 20 games), so the sim would sit about +1.2 over its close-calibrated
     target. That is a systematic lean to the over on pregame totals against the market.
   - Re-centre it with `solver_endgame_pts_per_team`. It is a cfg field the exact solve already subtracts
     (`engine.py:142`, `:1152`, `:1173-1174`), and the env already accepts it. Fit it so the tip sim mean equals the
     target over a full slate.
   - Then re-read the pregame sim against finals. Today: +0.40 ± 1.05 on 279 games.
2. **The end-game fouling fit** (`endgame_foul_p_by_deficit` and the rest).
   - It acts only at |m| ≤ 10 inside its window, which never overlaps a flagged state at decision time.
   - But another session is re-fitting it now (harness run `ncaab2026_oos_B`, `endgame_foul_p_by_deficit
     [0.25, 0.7, 0.9]`, seed 20261108). **The two must be gated as a PAIR** (learnings 2026-10-12: "test the pair,
     never one alone").
3. **Unaffected:**
   - `H1_SHARE`, an estimator measured from data;
   - the prior calibration, fitted prior → close with no sim in the loop.

**Gate before any load.** #765's harness, paired, on 2025-26 regular season, run `ncaab2026_blowout_off`:
- the same 400 games and seed (20261107) as `ncaab2026_resim_prod`, production's three switches;
- `resim` against `resim_mech` with the rule off;
- launched 18:11:38Z, WSL `~/bball_iv/runs/ncaab2026_blowout_off`, nice 19.
- **Ship only if** the full-game and h2 total |err| improve or tie at every checkpoint (0 / 10 / 20 / 30 / 38 m) and
  the margin does not get worse.
- The result is appended below when the run completes. Until then the fix is a proposal resting on the 2026-27
  ledger and the probe.

**Harness gate status `[18:45Z 11-08]`:** RUNNING, 50 of 400 games. Expected done about 20:50Z (2:50 PM CST).
- Two other jobs share the host at nice 19: another session's `ncaab2026_oos_B` (3 workers) and this lane's probes,
  now finished.
- **Reachability already read off the partial output** (19 regular-season games):
  - states with \|m\| < 15 at 20 / 30 / 38 m shift by exactly 0.00;
  - at 20 m with \|m\| ≥ 15 the total shifts +1.69 ± 0.44 (3 games), in line with the probe.
- Read it with `scripts/ncaab_blowout_harness_read.py <run>/results.jsonl`. It recovers the margin at each checkpoint from
  `pregame_rate`, and splits by the engine's flag.
- **Expect the season-wide gate to read small or tie.** Mid-season 2025-26 has far fewer lopsided games than
  opening week, so the split by \|m\| ≥ 15 is the reading that matters.

## Women's (wncaab)

**The books run HIGH on the live-priced women's games, but 29 games cannot support a book bias.**

- **Priced totals rows, pre-gate** (2,505 rows / 29 games, 11-03..11-06):
  - line − final **+3.80 ± 1.80** (+3.92 / +3.70 / +4.20 within / older / newer);
  - model − final +0.49 ± 1.82;
  - model − line −3.31 ± 0.44.
- **One number per game:**
  - the game's mean line − final is +3.62 ± 1.56;
  - its FIRST priced line (nearest the tip) − final is +3.26 ± 2.52, and the final went under that line in 19 of 29;
  - the model's game mean is +0.43 ± 1.54.
  - Every date reads high: +3.85 / +5.05 / +2.76 / +4.30 game mean, on 4 / 5 / 14 / 6 games.
- **Why that is not evidence against the books:**
  - The same games' pregame prior, which is calibrated to the books' close (`prior_calibration` target "close"),
    was high by the same amount: +3.96 ± 2.52 on 37 games. These games went under the market's expectation both
    pregame and live. That is outcome noise shared by both numbers, not two pieces of evidence.
  - **Over every graded women's pregame entry**, the close-calibrated prior is **+1.22 ± 1.23** (196 games, 105
    finals below it), the raw prior −0.68 ± 1.28 (178), and the pregame sim +0.91 ± 1.22. A +3.6 bias in the
    market's women's totals would show there, and it does not.
  - Post-gate, 11-07 (8 games): game-mean line − final +0.38 ± 3.50.
- **What would support a claim:** detecting a true +3.6 at 80% power (two-sided 5%) needs about **43 live-priced
  games** at the game-mean spread (sd 8.4), or **about 110** at the first-line spread (sd 13.6). The women's slate
  priced 29 in four days.
- **The women's model is near the final by cancellation, not by being right.**
  - Its prior error is +1.90 ± 1.95 on the time left (n.s.).
  - Its live update is −1.00 ± 0.17 (833 states / 29 games).
  - The same blowout rule applies, but over less of the game: women's `N_PERIODS = 4`, so it covers Q4 at 15+ or
    Q3-Q4 at 18+. Flag on −1.30 ± 0.14 (217 / 22), off −0.33 ± 0.17.
  - A men's-only fix (through `SYNDICATE_NCAAB_LIVE_MECHANISMS`, which `build_engine_inputs` applies to `league ==
    "ncaab"` only) leaves the women's engine untouched. A women's change would need its own reading.

## Limits

- **Season phase.** 11-02..11-07 is the first week: buy games, many 20+ point margins, prior-season ratings for most
  teams (`priorSeasonFallback` on 132 of 192 games). Mid-season has fewer blowouts, so the effect per game will be
  smaller, while the effect per blowout state should not change.
- **Ledger weighting.** Records are deduped on line movement, so P1 weighs volatile games more. P2 dedups to one row
  per state, but a game with more lane states still weighs more within the game cluster.
- **Unmatched games.** 33 men's game keys did not match ESPN by name and are excluded (e.g. "Arizona St").
- **Placement.** 37 states had a score that never appears in the play-by-play, and were dropped.
- **The prior remaining is the engine's TARGET split, not the sim's own expectation.** The pregame sim sits +0.4 on
  the target, and the half split is the production `H1_SHARE`. The actual h1 share this season is 0.469 ± 0.003,
  against 0.4743.
- **The probe's halftime state** is synthetic (first half scored at its prior share), with real teams and real
  production inputs.

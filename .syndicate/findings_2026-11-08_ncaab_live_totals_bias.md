# NCAAB live totals run low: the engine's NBA blowout rule covers the whole college second half (2026-11-08)

Lane `ncaab-live-totals-bias`, session 6df1b15d. Read-only; nothing deployed, no env changed. Written 2026-11-08,
12:46 PM CST (18:46Z). The harness gate result was added at 2:07 PM CST (20:07Z), and the tip re-centre result
(lane `ncaab-blowout-tip-recentre`) at 5:33 PM CST (23:33Z).

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
5. **Switching the rule off passes #765's harness gate** (285 regular-season 2025-26 games, paired).
   - The total improves or ties at every checkpoint; the margin is unchanged.
   - Where the rule fires (15+ apart), the total improves by −0.47 ± 0.30 |err| at 30 m (73 games, ± 1.96 SE).
   - **With its re-fit it passes again.** Adding `solver_endgame_pts_per_team` 0.2 puts the tip back on production's
     (+0.04 ± 0.10), still improves or ties everywhere against production, and ties rule off alone at every
     checkpoint (see "Tip re-centre"). 0.6, which centres the tip on its target, is not recommended.
   - The end-game re-fit it was to be paired with (`ncaab2026_oos_B`) was not adopted, so production's end-game
     fields are the partner, and every gate here carries them. **Nothing is owed before a load but the user's yes.**

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

**With its §4.4 re-fit the load is three fields** (measured in "Tip re-centre" below):

    "blowout_q4_margin": 999, "blowout_margin": 999, "solver_endgame_pts_per_team": 0.2

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
  states and puts it at about +0.7 (gate result below).
- **What is left after the fix is mostly not model error:**
  - In close second halves the model is nearer the final than the book: model − final −0.48 ± 1.17 against line −
    final +0.74 ± 1.25.
  - Lopsided first halves keep scoring above the prior (prior error, n.s. at the state level). The prior target is
    level over the whole slate (+0.01 ± 1.06).

**What switching it off might cost.** In the final 4 minutes real blowouts do slow (prior error +0.52 / +0.95). On
the live ledger, the model with the rule off would run about +0.5 to +1 high on those states, where it is about right
today (−1.06 / −0.30).
- **The harness does not see that cost** (gate result below). At 2 minutes left, states 15+ apart are still nearer
  the final with the rule off.
- That leaves a clock-windowed rule as a HYPOTHESIS, not the recommendation. It would keep the rule but add a new
  `EventSimConfig` field, e.g. `blowout_window_s`, defaulting to the whole period (byte-identical for NBA/WNBA), with
  NCAAB set to the final ~240 s of regulation through the same env.
- It would be an `engine.py` change (lanes `basketball-scenario-calibration` and `wncaab-module` hold loans there)
  and a new mechanism, so it would carry §4.4's re-fit and need its own gate.

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
   - **Resolved 11-08:** variant B was not adopted. On a fresh sample it improves no total and worsens the 38 m
     margin, so production's E1 stays (`findings_2026-11-07_basketball_interval_backtest.md:391-392`, `:487`). The
     partner is therefore production's end-game fields, which every gate here already carries.
3. **Unaffected:**
   - `H1_SHARE`, an estimator measured from data;
   - the prior calibration, fitted prior → close with no sim in the loop.

**Gate before any load.** #765's harness, paired, on 2025-26 regular season, run `ncaab2026_blowout_off`:
- the same 400 games and seed (20261107) as `ncaab2026_resim_prod`, production's three switches;
- `resim` against `resim_mech` with the rule off;
- launched 18:11:38Z, WSL `~/bball_iv/runs/ncaab2026_blowout_off`, nice 19.
- **Ship only if** the full-game and h2 total |err| improve or tie at every checkpoint (0 / 10 / 20 / 30 / 38 m) and
  the margin does not get worse.

**Gate result `[read 2:07 PM CST (20:07Z) 11-08]`: PASS.**
- Run `ncaab2026_blowout_off` finished at 2:05 PM CST (20:05Z) after 6,814 s. It scored 399 of 400 games (1 refused
  `pbp_final_mismatch`), 285 of them regular season.
- Read with `scripts/ncaab_blowout_harness_read.py <run>/results.jsonl`. It recovers the margin at each checkpoint
  from `pregame_rate` and splits on the engine's flag. It reads the projected total and the projected margin.
- In the table, each cell is |err| off − prod, ± 1.96 SE. Negative means the rule-off variant is nearer the final.
  Shifts and biases below carry ± 1 SE.

| checkpoint | full total, all 285 | h2 total, all 285 | full total, \|m now\| ≥ 15 | margin, all 285 |
|---|---|---|---|---|
| 0 m (tip) | −0.01 ± 0.17 | −0.09 ± 0.16 | — | +0.10 ± 0.16 |
| 10 m | −0.02 ± 0.16 | −0.09 ± 0.15 | +0.91 ± 0.91 (13 games) | −0.04 ± 0.14 |
| 20 m (half) | −0.06 ± 0.12 | −0.06 ± 0.12 | −0.38 ± 0.84 (42) | +0.01 ± 0.06 |
| 30 m | **−0.12 ± 0.08** | **−0.12 ± 0.08** | **−0.47 ± 0.30** (73) | +0.01 ± 0.05 |
| 38 m | −0.03 ± 0.03 | −0.03 ± 0.03 | **−0.11 ± 0.09** (81) | −0.01 ± 0.02 |

- **Against the ship rule:**
  - the total improves or ties at every checkpoint, full and h2, and improves beyond 1.96 SE at 30 m;
  - the margin ties at every checkpoint, in every split.
- **The one cell that is not better:** first-half states 15+ apart at 10 m, 13 games. The full total reads
  +0.91 ± 0.91, but its h2 part reads −0.07 ± 1.17. Thirteen games resolve neither.
- **Reachability.** h2 states below 15 shift by exactly 0.00 at 20 / 30 / 38 m (240 / 209 / 201 games). States 15+
  apart shift +2.41 ± 0.21 at the half, +1.23 ± 0.10 at 30 m and +0.11 ± 0.04 at 38 m.
- **It removes the margin dependence of the bias.** h2 total bias, prod → off:
  - at the half, 15+ apart: −3.99 ± 1.81 → −1.58, beside −1.33 ± 0.88 for closer games;
  - at 30 m, 15+ apart: −4.11 ± 0.90 → −2.87, beside −3.17 ± 0.82.
- **The expected effect is above the lower bound.**
  - In real states the rule takes about 1.3× the probe's pro-rata cost at the same checkpoint: +2.41 at the half
    against the probe's ~1.9, and +1.23 at 30 m against ~0.95.
  - Scaled, the live headline (model − line −1.95) moves about +0.7. That sits inside the bracket above: +0.55 as the
    lower bound, +0.9 as the upper side.
  - The scaling is approximate. The harness is 2025-26 regular season, not this week's population.
- **The closing-minutes cost is not seen.**
  - At 2 minutes left, states 15+ apart are still nearer the final with the rule off (−0.11 ± 0.09). Their bias
    stays low: prod −0.46 ± 0.43 → −0.35.
  - The +0.5 to +1 over-projection estimated from the live ledger (above) does not appear here.
  - So the harness gives no support to the windowed rule. It stays a hypothesis that would need its own gate.
- **The tip moves up +0.39 ± 0.09** (285 games; the probe read +0.61 ± 0.36 on 20).
  - Bias prod +0.13 ± 1.02 → +0.52, with |err| −0.01 ± 0.17.
  - Re-fit 1's re-centring was owed: the shift is systematic even though this sample cannot see its cost. Done in
    "Tip re-centre" below.
- **What it does not fix: a low bias in 2025-26 second halves that does not depend on the rule.**
  - Where the rule never fires (h2 below 15), the total reads −1.33 ± 0.88 at the half, −3.17 ± 0.82 at 30 m and
    −3.59 ± 0.72 at 2 minutes left.
  - The 2-minute cell is close games' end-game fouling: `pregame_rate`, pro rata, reads −7.14 there. That is the
    end-game re-fit's domain (`ncaab2026_oos_B`), not this rule.
  - The live 2026-27 ledger reads that phase at −1.12 ± 0.68, so the two seasons differ there.
- **The pair** `[corrected 11-08 5:33 PM CST]`. This gate switched the rule off against production's end-game fields.
  At the tip and in the first half the simulated future spans both mechanisms, so they had to be gated together. The
  end-game re-fit `ncaab2026_oos_B` was not adopted (re-fit 2 above), so production's fields ARE the pair's other half,
  and this gate tested it. The re-centred pair is gated again below.

## Tip re-centre `[read 5:33 PM CST (23:33Z) 11-08]`: 0.2 PASSES; 0.6 is not recommended

Lane `ncaab-blowout-tip-recentre`. Read-only, nothing loaded. The lever is `solver_endgame_pts_per_team` (re-fit 1).

**Probe** (`scripts/ncaab_blowout_resume_probe.py --variant NAME=JSON`).
- 24 games, 11-05..11-07, at the tip, 100 sims each.
- Production inputs, with live-odds-worker's switches copied from pid 1665718 (names only printed).
- Tip total minus the exact solve's target, ± 1 SE:

| variant | − target | − production | − rule off alone |
|---|---|---|---|
| production | +1.11 ± 0.43 | — | −0.11 ± 0.29 |
| rule off | +1.23 ± 0.38 | +0.11 ± 0.29 | — |
| rule off + 0.2 | +0.77 ± 0.35 | −0.34 ± 0.38 | −0.46 ± 0.29 |
| rule off + 0.6 | −0.10 ± 0.22 | −1.21 ± 0.34 | −1.33 ± 0.30 |

- The tip falls about 2.2 points per point of the field, so the solve bounds do not bind. The hypothesis held.
- On these 24 games the rule's own tip shift is only +0.11 ± 0.29, below the harness's +0.39 ± 0.09. So the probe
  alone cannot pin the value that restores production; the harness does.

**Harness.**
- Runs `ncaab2026_off_eg02` and `ncaab2026_off_eg06`: the same 400 games and seed (20261107) as the gate above, with
  `resim_mech` = rule off + 0.2 and + 0.6.
- Launched 3:33 PM CST (21:33Z) from `ed224359a`, nice 19; each done after 7,116 s. 399 scored (1 `pbp_final_mismatch`),
  285 regular season.
- Read with `scripts/ncaab_blowout_harness_read.py`, against production, and with
  `--vs ~/bball_iv/runs/ncaab2026_blowout_off/results.jsonl` against rule off alone.
- **Pairing check:** production's `resim` is identical across the three runs (max |difference| 0.0000 over 3,696
  rows).

Full-game total, all 285 games, |err| new − base, ± 1.96 SE. Negative means nearer the final:

| checkpoint | 0.2 vs prod | 0.2 vs rule off | 0.6 vs prod | 0.6 vs rule off |
|---|---|---|---|---|
| 0 m (tip) | +0.01 ± 0.19 | +0.02 ± 0.17 | +0.05 ± 0.20 | +0.06 ± 0.22 |
| 10 m | −0.08 ± 0.16 | −0.06 ± 0.15 | +0.07 ± 0.18 | +0.09 ± 0.18 |
| 20 m | −0.00 ± 0.17 | +0.06 ± 0.13 | +0.03 ± 0.18 | +0.10 ± 0.16 |
| 30 m | −0.09 ± 0.12 | +0.03 ± 0.10 | −0.01 ± 0.12 | **+0.11 ± 0.11** |
| 38 m | −0.01 ± 0.05 | +0.02 ± 0.04 | −0.02 ± 0.06 | +0.01 ± 0.06 |

- **Where the rule fires (15+ apart), against production:**
  - 0.2: −0.36 ± 0.29 at 30 m (73 games), −0.12 ± 0.09 at 38 m (81);
  - 0.6: −0.39 ± 0.28 and −0.11 ± 0.08;
  - rule off alone was −0.47 ± 0.30 and −0.11 ± 0.09.
- **h2 total, against production, ties everywhere:** 0.2 reads −0.16 ± 0.17 / −0.12 / −0.00 / −0.09 / −0.01, and 0.6
  −0.05 / −0.05 / +0.03 / −0.01 / −0.02.
- **Margin, against production, ties everywhere for both, in every split.** The largest cell is 0.2 at the tip,
  +0.14 ± 0.17. At 38 m both are slightly better (−0.03 ± 0.03, −0.05 ± 0.04).
- **The tip** (± 1 SE):
  - 0.2 shifts it +0.04 ± 0.10 against production (−0.35 ± 0.09 against rule off), so it restores production's tip;
  - 0.6 shifts it −0.77 ± 0.09.
  - Bias against finals: production +0.13 ± 1.02, rule off +0.52, 0.2 +0.17, 0.6 −0.63.

In-game bias, full total, all 285 games (model − final):

| | 10 m | 20 m | 30 m | 38 m |
|---|---|---|---|---|
| production | −1.99 | −1.80 | −3.46 | −2.67 |
| rule off | −1.57 | −1.44 | −3.14 | −2.64 |
| rule off + 0.2 | −1.86 | −1.61 | −3.30 | −2.68 |
| rule off + 0.6 | −2.52 | −2.08 | −3.49 | −2.70 |

**Verdict.**
- **Rule off + 0.2 passes the gate against production.**
  - The total (full and h2) and the margin improve or tie at every checkpoint.
  - It keeps the gain where the rule fires.
  - It puts the tip back on production's, which meets §4.4's re-fit.
  - Against rule off alone it ties at every checkpoint, so the re-centre costs nothing measurable.
- **Rule off + 0.6 is not recommended.** It also ties production, but:
  - it gains nothing at the tip (|err| +0.05 ± 0.20);
  - it reads worse than rule off alone at every in-game checkpoint (+0.06 to +0.11, at the 1.96 SE edge at 30 m);
  - it deepens the in-game low bias this work exists to fix, by −0.5 at 10 m.
  - The reason is structural. The field lowers the whole-game scoring rate, so live projections fall in proportion to
    the time left. One rate field cannot lower the tip without lowering the live total too.
- **Production's tip sits above its own target, and this load leaves that alone.**
  - It reads +1.11 ± 0.43 over the target (probe, 24 games, 2026-27), and +1.28 over the harness's `pregame_rate`
    projector at the tip (2025-26).
  - That predates this change. Neither sample sees it against finals: 2026-27 graded pregame sims read
    +0.40 ± 1.05, and the harness tip +0.13 ± 1.02.
  - It is a separate question, a possible lean to the over on pregame totals, and not part of this load.

**Expected live effect, revised for 0.2.**
- The re-centre takes back 0.29 / 0.18 / 0.16 / 0.04 at 10 / 20 / 30 / 38 m against rule off alone (harness). That
  is a rate change, pro rata to the time left, so it should carry to the 2026-27 states roughly unchanged.
- Rule off alone was expected to move the live headline (model − line −1.95) by about +0.7. Net of the re-centre,
  **about +0.5, to roughly −1.45.**
- On h2 flag-on rows (−2.74 today), the re-centre takes back about 0.15 (15+ apart: 0.29 / 0.13 / 0.02 at 20 / 30 /
  38 m), so they move to roughly −2.0.
- These are approximate: the harness is 2025-26 regular season, not this week's population.

**The load, if the user says yes** (nothing done):
- live-odds-worker's `SYNDICATE_NCAAB_LIVE_MECHANISMS`, role key `LIVE_ODDS_WORKER__` in `local_production.env`;
- production's four end-game fields, plus `"blowout_q4_margin": 999, "blowout_margin": 999,
  "solver_endgame_pts_per_team": 0.2`;
- men's only; a drained full `down`/`up` between slates (lane, three claims, origin/main preflight with
  `--reinject-env`, joint CLEAR). Every men's pregame game re-sims once, because the `inputs_key` carries the
  mechanism names.
- **Verify** on the live ledger after load: priced-row model − line from −1.95 to about −1.45, and h2 flag-on rows
  from −2.74 to about −2.0. The tip needs no reading of its own: the harness puts it at +0.04 ± 0.10 from today's.

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

# NBA smart-sim `market_anchor.model_margin_raw == 0.0` — diagnosis `[2026-11-16, lane nba-margin-raw-zero, todo #821]`

Read 2026-11-16, 7:00–7:45 PM CST. Diagnose only: no code was changed, nothing was loaded or deployed.

## Verdict

**DEFECT, and it is wider than the 72 zeros.**

- The NBA pregame smart-sim never receives the game model's team strength. In the
  2026-27 corpus that holds for **261 of 261 NBA sims on the fleet (10-03..11-16)**,
  not 72 of 192.
- The 72 zeros are only the games where the one remaining term (injury-count and b2b
  adjustments) happens to cancel. The 122 "nonzero" raw margins are that same term,
  injury-count noise: correlation with the actual margin is **0.028** (192 graded games).

**Cause: a column-name mismatch.**

- The shared job builder reads WNBA's prediction column names:
  `row.get("totals")` / `row.get("spread_margin")`
  (`syndicate/features/shared/basketball_props_smart_sim.py:5795-5796`).
- NBA's `predictions_<D>.csv` carries **`pred_total` / `pred_margin`** (41 of 41 fleet
  files, 10-03..11-16). Neither name ever matches.
- So `home_mu`/`away_mu` are `None` (`:5797-5798`), and `_rating_from_mu` returns the
  neutral default `baseline_off_rating` 110.6 for BOTH teams (`:5825-5834`).

**Is it a defect? Yes.** It is the model-engine standard's own failure shape: a field
that is consumed, defaulted to neutral, silent, and unfed. It is also the reason the
`skip_def_subtraction` switch's premise does not hold in production (see "Why nobody saw
it").

**Fixing it is NOT obviously worth it** (the 2x2 below). The fix is a decision for the
user, not a default.

## Pipeline trace (file:line, origin/main 994066989)

1. **Producer.** `syndicate/features/nba/source_cli/cli.py:984-985` (the sklearn
   fallback) writes `res["pred_margin"]` / `res["pred_total"]`.
   - Only the NPU branch renames them to `spread_margin`/`totals` (`:954-959`, inside the
     period-calibration try).
   - The fleet files lead with the full feature row (`elo_diff, home_rest_days, ...`),
     which is the fallback's `pd.DataFrame(feat_rows)` shape. The NPU branch keeps only
     `date/home_team/visitor_team`.
   - So the fleet runs the fallback. That is structural evidence: the "NPU predictor not
     available" log line was NOT confirmed.
2. **WNBA's producer is different.** `syndicate/features/wnba/source_cli/cli.py:449-454`
   renames on the path that runs, so WNBA files carry `spread_margin`/`totals` (17 of 17
   files, 0 with `pred_margin`).
3. **Reader.** The job build is `basketball_props_smart_sim.py:5795-5798`:
   `pred_total = _num(row.get("totals"))` and `pred_margin = _num(row.get("spread_margin"))`.
   For NBA both are `None`, so `home_mu = away_mu = None`.
4. **Neutral default.** `:5825-5834` `_rating_from_mu(None, ...)` returns
   `LEAGUE.baseline_off_rating` (110.6). The job writes
   `home_off_rtg == away_off_rtg == 110.6` and `off_rtg_from_points = False` (`:5866-5869`).
5. **Worker.** `:5204-5205` re-defaults through `float(job.get(...) or baseline)`, then
   `TeamContextLocal` is built at `:5214-5215`.
6. **Quarter model.** `_simulate_quarters_local`:
   - `:1191-1193`: the fleet's `nba_sim_total_inputs.json` is
     `{"skip_def_subtraction": true}`, so `home_eff = away_eff = clip(110.6)`.
   - `:1201-1202`: `mu = eff/100 * pace + _adjustments_local(ctx)`.
7. **The only term that differs.** `_adjustments_local` (`:893-905`) gives −0.5 per
   injury out and −0.8 for a b2b (`form_7`/`form_30` are never set on this path).
   - Outs are `min(5, len(excluded_map[team]))` (`:5851-5852`).
   - No `calibration_totals_*.json` exists on the fleet, so `_apply_totals_calibration_local`
     adds nothing.
8. **Recorded.** `:1208-1209` `model_margin_raw = home_mu - away_mu`, which equals
   `0.5*(away_outs - home_outs) + 0.8*(away_b2b - home_b2b)`.
9. **Anchored.** `:1218-1226` / `:95` gives `anchored_margin = 0.95*market + 0.05*raw` and
   `anchored_total = 0.7*market + 0.3*raw`.
10. **Downstream.** The anchored quarter means go to the player sim as `quarters`
    (`:5237`). Their sums become `target_home_points`/`target_away_points`, which
    "gently calibrate possession efficiency in PBP mode"
    (`syndicate/features/basketball_engine/orchestrator/smart_sim.py:1568-1569`). So the
    anchored TOTAL (not just the period lines) reaches player props. That was NOT measured
    here.

## Evidence

| check | result |
|---|---|
| rule `0.5*(ao-ho) + 0.8*(ab-hb)` vs recorded `model_margin_raw`, #818 copy (`C:\tmp\nba_seg\...\processed`) | **197/197** exact (max \|dev\| 2.9e-15) |
| same rule, the raw TOTAL (`2*1.106*pace_after_drags + adj`) | **197/197** exact (max \|dev\| 5.7e-14) |
| same rule, every NBA sim on the fleet (read-only scan, nice 19) | **261/261** on-rule, 0 off-rule; 105 zeros |
| zeros in the #818 window 10-21..11-15 | 72 of 194 sims (192 graded); **72/72 = equal outs AND equal b2b** |
| NBA `predictions_<D>.csv` on the fleet | 41/41 have `pred_margin`/`pred_total`, **0** have `spread_margin`/`totals` |
| WNBA control (same code, `spread_margin` present) | **15/15** sims with a raw value are OFF the rule (game model fed); 7 have no raw |

**The shape of the margins confirms it.** The only values in the window are 0.5·k + 0.8·j:

- −2.8, −2.5, −2.0, −1.8, −1.5, −1.3, −1.2, −1.0, −0.8, −0.5, −0.2, **0.0 ×72**, 0.3, 0.5,
  0.7, 0.8, 1.0, 1.5, 1.8, 2.0, 2.3, 2.5, 2.8.
- A fed margin would be continuous.

## Share over time, and why it climbs

| week (Mon) | NBA sims | zero | zero share | both teams at the 5-outs cap |
|---|---|---|---|---|
| 09-28 (preseason) | 3 | 3 | 100% | – |
| 10-05 (preseason) | 23 | 12 | 52% | – |
| 10-12 (preseason) | 30 | 13 | 43% | – |
| 10-19 | 43 (40 in the #818 window) | 8 (6) | 19% (15%) | 0 of 40 |
| 10-26 | 49 | 14 | 29% | 13 |
| 11-02 | 54 | 21 | 39% | 24 |
| 11-09 | 51 | 31 | **61%** | 29 |
| 11-16 (partial) | 8 | 3 | 38% | – |

- The climb is the outs cap saturating. Of the 72 zeros, **61 are 5-vs-5 outs** (57 with
  no b2b, 4 with b2b on both sides). The rest are 4-4 (6), 3-3 (3), 2-2 (1) and 1-1 (1).
- By 11-09, 29 of 51 games had both teams at the cap. Home sides sat at 5 outs in 100 of 194
  games and away sides in 109 of 194.
- Zeros by team (window) follow the same driver, not a team effect. NOP is highest at 11
  of 14 sims, OKC 9/13, and MEM/SAS/WAS 8 each; MIA and ORL are 1 each.
- Preseason 10-03..10-10: 22 sims carry no `nba_total_inputs` (the switch file was not yet
  read), and they are still on-rule. So the def-rating subtraction did not separate the
  teams there either; why was not verified.

## Why nobody saw it

- **Neutral default.** `_rating_from_mu` and `float(job.get(...) or baseline)` turn
  "missing" into 110.6. Every field is populated with a valid-looking number.
- **Checklist scope.** `scripts/basketball_sim_input_checklist.py` enumerates the
  player-sim inputs, not the quarter model's `TeamContextLocal`/job fields. It has no
  `TeamContext`/`off_rating` reference, so it could not flag consumed-but-unfed here.
- **The 10-06 calibration ran on a fed corpus.**
  `.syndicate/findings_2026-10-06_basketball_scenario_calibration.md` (D1/D2/D3) was
  measured on 2025-26 vendor predictions, where ratings WERE game-model-derived (e.g.
  "LAL-DET 12-30 home off 119.07 vs 106.54"). It concluded "with both removed the raw
  equals the vendor game model's own prediction".
  - In 2026-27 production the raw equals 110.6 × pace. The `skip_def_subtraction`
    switch's premise (points-derived ratings already price the opponent's defense) does
    not hold.
  - With baseline ratings, the def subtraction was the only remaining per-team strength
    term (`adv_map` def ratings). Whether those def ratings are populated now was NOT
    verified.
- **The anchor hides it.** At margin weight 0.95, the anchored margin is the market's to
  within 0.05 × raw. Nothing downstream looks wrong.

## Does it cost anything? 2x2 counterfactual on the 192 graded games

Inputs:

- the recorded sims plus fleet predictions;
- ESPN finals from #818 (`C:\tmp\nba_seg\linescores.json`);
- `_simulate_quarters_local`'s arithmetic re-derived (served arm A reproduces the recorded
  raw total to 5.7e-14).

Bias is actual − prediction. CIs are a game bootstrap, 2000 draws, seed 0, NOT
date-clustered.

| arm | raw total bias | raw total MAE | **anchored total MAE** (Δ vs served, 95% CI) | anchored total bias | anchored margin MAE |
|---|---|---|---|---|---|
| A served: unfed, outs penalties on | +12.38 | 18.06 | **14.504** | +3.42 | 11.082 |
| B unfed, outs off | +2.90 | 14.99 | 14.127 (−0.377 [−0.774, +0.031]) | +0.57 | 11.080 |
| C **fed, outs on** (the naive fix) | +15.46 | 20.63 | 14.811 (**+0.307** [−0.075, +0.668]) | +4.34 | 11.096 |
| D fed, outs off (10-06's D1+D2) | +6.06 | 16.89 | 14.387 (−0.118 [−0.566, +0.328]) | +1.52 | 11.097 |
| market | −0.42 | 14.09 | – | – | 11.07 |

What the game model would bring (window, 192 games):

- **Margin.**
  - MAE: game model **15.28**, market **11.07**, served raw 13.70.
  - Correlation with the actual margin: market 0.539, game model **0.130**, served raw 0.028.
- **Total.**
  - MAE: game model 16.74, market 14.09.
  - Bias: game model +5.58, i.e. it runs 5.6 low.
- **Anchored margin.** It does not move in any arm (11.080–11.097): the raw carries 0.05 weight.

Readings:

1. **On margin the defect is costless today.** At w = 0.95, feeding a weak game model
   changes nothing measurable.
2. **On total, the larger cost is the outs penalties, not the missing feed.**
   - The served anchored total runs 3.4 low, and that is what reaches the player sim's
     target points.
   - Feeding the game model with the outs penalties still on (arm C) is the WORST arm by
     point estimate: the game model already runs 5.6 low, and the penalties stack on it.
   - No arm differs from served at 95% on 192 games.
3. **The NBA game model is itself weak this season** (a lead, not this lane). Its
   `pred_margin` correlates 0.24 with its own input `elo_diff`, while `elo_diff` correlates
   **0.81** with the market margin (194 games).

## Proposed fix, for the user to decide (nothing is done)

**F0: make it loud (recommended first; behaviour-neutral).** This is what the model-engine
standard asks for, whichever way F1 goes.

- Record `market_anchor.game_model_fed: bool` and the column names that were found.
- Print one `NBA_SIM_GAME_MODEL_UNFED date= n=` line per run, with `print(..., flush=True)`.
- Add a quarter-model section (`TeamContextLocal` fields over `dataclasses.fields()`) to
  `scripts/basketball_sim_input_checklist.py`. It must flag `home_off_rtg == away_off_rtg
  == baseline` on more than X% of jobs as consumed-but-unfed.
- No served value changes.

**F1: feed it (reader-side, default-off switch).**

- At `:5795-5796`, read `spread_margin` else `pred_margin`, and `totals` else `pred_total`,
  as the NBA live tick already does (`syndicate/features/nba/live_tick/tick.py:5403`).
- Gate it behind a key in `nba_sim_total_inputs.json` (e.g. `"feed_game_model": true`).
  The file is re-read per call and absent means today's behaviour.
- Reader-side is right: `nba_game_projections.py:298` and the board read `pred_margin`, so
  renaming the producer's columns would break them.
- **Do not ship F1 alone.** Arm C is the worst arm.
  - Pair it with `skip_outs_penalties: true` (arm D, the 10-06 D1+D2 prescription), or
    pair it with nothing and leave it off.
  - Arm B (outs off, no feed) has the best point estimate on totals, and its 95% CI just
    crosses zero. It is a SEPARATE decision about the outs penalties: lane
    `basketball-scenario-calibration` owns that switch.
- The standard's "mechanism vs estimator" rule applies. Adding real team strength to a
  calibrated engine means re-fitting what was absorbing it: the anchor weights 0.7/0.95,
  the NBA prop calibration, and the totals calibration.

**F1 reachability test plan (off != on, before any correctness claim).**

1. **Unit, reachability.** Feed a job built from a predictions row that has ONLY
   `pred_margin`/`pred_total`.
   - Off: assert `home_off_rtg == away_off_rtg == 110.6` and `game_model_fed is False`.
     This pins today.
   - On: assert `home_off_rtg != away_off_rtg`, `game_model_fed is True`, and
     `model_margin_raw` ≈ `pred_margin × pace_after_drags / matchup_pace + adj`.
   - Assert `off != on` on the raw AND on the anchored margin.
   - Add the same test with a WNBA-named row, to show both names work and WNBA is
     unchanged.
2. **Assert the branch ran, not the outcome.** The audit field comes from the branch
   itself, not from a fixture value.
3. **Corpus replay** (import `_simulate_quarters_local`, never copy it) over the 192 graded
   games:
   - Off: 192/192 on the outs/b2b lattice.
   - On: ≈0/192 on it.
   - Anchored total MAE per arm, matching the table above to within 1e-9 for arm A.
4. **Production, after a load** (a `betting change: yes`: anchored totals move the player
   sim's target points). Read the first NBA `smart_sim_*.json` written after the role picks
   up the switch:
   - `game_model_fed: true`;
   - `model_margin_raw` OFF the outs/b2b rule;
   - 0 zeros across a full slate.
   - Gate on artifact mtime > load time.
5. **Pre-registered grade, owed before keeping it on.** Anchored total MAE/bias vs served on
   the next ≥ 150 regular-season games, date-clustered CI, with the outs decision recorded.

## F0 built `[2026-11-17 9:38 AM CST, main 8aea4fe7e, lane nba-game-model-fed-audit; user: "Build F0 here"]`

Behaviour-neutral, and **not loaded**: it reaches the fleet only with an ff of `~/Syndicate`
plus a refresh-worker restart.

- **The read is unchanged.** `_game_model_points_local` (just above
  `_smart_sim_run_date_local`) reads `totals`/`spread_margin` through the job build's own
  `_num`, exactly as before, and also returns an audit. The job build calls it in place
  of the four inline lines.
- **The artifact.** Each pregame job carries `game_model_fed` and `game_model_columns`. The
  worker copies them into `market_anchor` (`_game_model_anchor_fields_local`). A job without
  them adds nothing: absent is not False.
- **The print.** `SMART_SIM_GAME_MODEL_UNFED league= date= unfed= of= read= found= games=`
  is printed once per run that has an unfed job, with `flush=True`. A fully fed run prints
  nothing.
- **Checklist Level 4** (`scripts/basketball_sim_input_checklist.py`):
  - **Structural.** Over `dataclasses.fields(TeamContextLocal)`, it compares the fields the
    quarter model consumes (AST of `_simulate_quarters_local` + `_adjustments_local`) with
    the fields every `TeamContextLocal(...)` call in `_smart_sim_worker_run_local` passes.
    A positive control drops `off_rating` from the builder and must alarm.
  - **Data.** It replays the bridge's own `_game_model_points_local` over the newest 14
    `predictions_<D>.csv` in each league's sim root, and counts `market_anchor.game_model_fed`
    on that window's sims.
  - **Root.** WNBA's sim root is `wnba_source/data/processed`, not the `source_artifacts`
    copy that Levels 1-3 read.
- **Neutrality, measured in the tests.**
  - The real run-date loop (worker stubbed) gives an NBA-named row `game_model_fed: false`
    and 110.6/110.6, which pins today's numbers. A WNBA-named row gives ratings from the
    means.
  - The REAL worker writes `market_anchor`. The pre-existing anchor fields are identical
    with and without the audit, including `model_margin_raw == 0.0` for equal outs/b2b.
  - Test counts: `tests/test_nba_game_model_fed_audit.py` 12,
    `tests/test_basketball_sim_input_checklist_level4.py` 9. The 95 neighbouring smart-sim
    tests and Level 0 are green.
- **Fleet reading of Level 4** (read-only, 9:36 AM CST, worktree code against
  `~/syndicate-prod/data`):
  - **NBA, 0 of 103 predictions rows fed** (14 dates, 11-04..11-17). `pred_total` 103,
    `pred_margin` 103, `totals`/`spread_margin` 0, so the `UNFED` alarm fires.
  - **WNBA control: 15 of 15 fed** (10-01..10-31).
  - **Sims:** 0 of 103 NBA and 0 of 14 WNBA carry the field yet (they were written before
    the load).
- **Owed after a load:** the first NBA `smart_sim_*.json` with mtime > the load shows
  `game_model_fed: false` and `game_model_columns: ["pred_total", "pred_margin"]`, and the
  refresh-worker log shows one `SMART_SIM_GAME_MODEL_UNFED league=nba` line per run.

**F0 loaded and verified** `[2026-11-17]`. The fleet was ff'd to `8aea4fe7e` at 16:26:58Z
with no restart (`deploys.md`). The first two NBA sims written after the ff carry
`game_model_fed: false` and `[pred_total, pred_margin]`:

- `MIN_POR`, 16:45:44Z: raw margin 1.0;
- `TOR_NYK`, 16:47:07Z: raw margin −0.5.

Both raw margins sit on the outs/b2b rule. The allowlist for the unfed line (`f252a5969`) is not
on the fleet yet, so the line is blanked there for now.

## F1 built, DEFAULT OFF `[2026-11-17 10:55 AM CST, main 92ae7490a; user: "build F1 behind the switch, default off"]`

Not loaded and not switched on.

- **Switch.** It is `"feed_game_model": true`, in the NBA processed root's
  `nba_sim_total_inputs.json`. That is the file which already holds `skip_def_subtraction`
  and `skip_outs_penalties`. It is read by `_nba_feed_game_model_switch_local`, separately from
  the other lane's loader, which is untouched (tested). It is re-read per job and applies to NBA
  only.
  - Absent, false, unreadable or any other league is today's behaviour: the job and the artifact
    are byte-identical to F0 (tested with the file absent and with `false`).
- **Read.** With the switch on, `_game_model_points_local(..., read_pred_columns=True)` falls back
  to `pred_total` / `pred_margin` when `totals` / `spread_margin` are missing. Each half is
  independent, and the WNBA names win when both are present.
  - `market_anchor.game_model_read` appears only when a fallback name was read.
  - `off_rtg_from_points` stays False for NBA, so the def term is decided by
    `skip_def_subtraction`, which is true on the fleet. With it false, a fed NBA rating would also
    get the opponent def subtracted: the double count the 10-06 work measured. Keep it true
    whenever F1 is on.
- **Level 4** replays under the same switch (`feed_game_model` in its census). Its `UNFED` alarm
  clears by itself once the switch is on and the code is loaded.
- **Reachability** (`tests/test_nba_game_model_feed_switch.py`, 10 tests, through the real
  per-game loop and the real worker):
  - Off: ratings 110.6/110.6, `model_margin_raw` 0.0.
  - On, with `skip_def_subtraction`, no outs or b2b: `model_margin_raw` = the game model's 3.1 and
    `model_total_raw` = 226.4, both to 1e-9.
  - The anchored margin differs between off and on, and equals the anchor arithmetic
    (`_apply_market_anchor_local` scales both means by the total blend, then blends the margin).
  - WNBA ignores the switch. The 103 neighbouring smart-sim tests are green.
- **Corpus replay through the REAL `_simulate_quarters_local`** (`C:\tmp\nba_margin0\f1_replay.py`,
  output `f1_replay.json`).
  - Inputs: the 197 #818 sims, fleet predictions, the real `_game_model_points_local`, anchor
    weights pinned to the recorded 0.95 / 0.7, and `skip_def_subtraction` in every arm.
  - Arm A reproduces all 197 production sims to **5.7e-14**: raw and anchored, margin and total.

  | arm | fed | raw-margin zeros (of 197) | anchored total MAE (192 graded) | bias | Δ vs A [95% CI] | anchored margin MAE |
  |---|---|---|---|---|---|---|
  | A unfed, outs on (today) | 0 | 74 | 14.504 | +3.42 | – | 11.082 |
  | B unfed, outs off | 0 | 177 | 14.127 | +0.57 | −0.377 [−0.779, +0.017] | 11.080 |
  | C fed (F1 on), outs on | 197 | 0 | 14.811 | +4.34 | +0.307 [−0.068, +0.659] | 11.098 |
  | D fed (F1 on), outs off | 197 | 1 | 14.387 | +1.52 | −0.118 [−0.568, +0.324] | 11.098 |

  - The MAE per arm matches the arithmetic 2x2 above to the third decimal. The verdict stands:
    no arm clears 95%, C is the worst, and B has the best point estimate.
  - With F1 on, the raw margin's correlation with the actual margin is 0.139, against 0.028 today.
    The anchored margin does not move (the raw weight is 0.05).
- **To switch it on (the user's call; a betting change; pair it with `skip_outs_penalties`):**
  1. ff the fleet to `92ae7490a` or later. The NBA props child loads it from disk, no restart.
  2. Add `"feed_game_model": true` to `~/syndicate-prod/data/nba_source/data/processed/nba_sim_total_inputs.json`.
  3. `betting_change.py add --kind yes`.
  - **A flip reaches only sims built afterwards.** The reuse checks do not read the switch, and
    tipped games are frozen. The next slate (built ~06:00Z) is the first full one.
  - Then read: `game_model_fed: true` and `game_model_read: [pred_total, pred_margin]` on a sim
    with mtime after the flip; 0 zeros over a full slate; Level 4's `UNFED` alarm gone.
  - Then the pre-registered grade (plan item 5), before keeping it on.

## F1 switched ON with the outs penalties OFF: pre-registered keep/revert grade `[written 2026-11-17 ~11:15 AM CST, BEFORE the flip; lane nba-f1-switch-on]`

**Decision.** The user said "On, with outs off", which is arm D. They also said "Carry it along" for
#824 `3dbe53df0`, which rides the same ff. The fleet switch file becomes
`{"skip_def_subtraction": true, "skip_outs_penalties": true, "feed_game_model": true}`. The replay
prior for arm D vs today was −0.118 [−0.568, +0.324] anchored-total MAE (192 games), with no arm
clearing 95%. This grade decides whether it stays on.

**Population.**

- NBA regular-season games that tip after the first NBA sim written after the flip.
- The sim on disk at tip must carry `market_anchor.game_model_fed: true` and
  `nba_total_inputs.skip_outs_penalties: true`. Pregame sims freeze at tip.
- Games whose sim was built before the flip (reused) are excluded, as are games with no ESPN
  final.
- The first **150** graded games by tip time.

**Arms, paired on the same games.**

- **D** is the served `market_anchor.anchored_total`.
- **A** is today's counterfactual: both ratings at `baseline_off_rating`, outs penalties ON, the
  same market lines and the recorded weights.
  - It is rebuilt from the artifact (`pregame_context` outs, b2b and team paces) with the exact
    arithmetic of `_simulate_quarters_local`. That arithmetic reproduced 197 of 197 production
    sims to 5.7e-14 (`f1_replay.py`).
  - **Validity gate:** the same arithmetic must reproduce each graded game's SERVED D raw and
    anchored total to 1e-9. On any miss the grade is void until the reconstruction is fixed.

**Metric.** `e = |actual final total − anchored total|` per game. Δ = mean(e_D − e_A). The 95% CI
is a percentile bootstrap that resamples whole tip dates (Central), 2,000 reps, seed 821.

**Rule.**

- **KEEP** if the CI upper bound is < 0.
- **REVERT** if the CI lower bound is > 0. Reverting means taking both keys out, so the file
  returns to `{"skip_def_subtraction": true}`.
- **Otherwise INCONCLUSIVE:** stay on and re-grade once at 300 games with the same rule.
  Inconclusive at 300 goes to the user with the numbers.

**Reported, not gating.**

- Anchored-total bias for D and A.
- Anchored-margin MAE. Expected unchanged within ±0.05, since the raw weight is 0.05.
- The share of raw-margin zeros (expected ≈ 0, against 38% of the replay corpus today).
- The raw margin's correlation with the actual margin (replay prior: 0.139 vs 0.028).

**Not covered here.**

- **Props.** Outs-off also removes the player-sim pace drag (`orchestrator/smart_sim.py`
  `_pace_injury_drag`), and the anchored total sets each player sim's target points. A props read
  is owed separately.
- **The calibrated layers.** The 0.7/0.95 anchor weights, the NBA prop calibration and the totals
  calibration were fit on unfed sims. If D is kept, a re-fit is owed (model-engine standard,
  mechanism vs estimator).

**Expected timing.** At about 8 graded games a day, 150 games arrive around 2026-12-06.

## Leads (recorded, not followed)

- **`TeamContextLocal.form_7` / `form_30` are consumed and never passed** (found by Level 4,
  2026-11-17).
  - They feed the quarter means (`_adjustments_local`: +0.5·form_7, +0.25·form_30) and the
    quarter sigma (the stress term in `_simulate_quarters_local`).
  - Neither `TeamContextLocal(...)` call in `_smart_sim_worker_run_local` passes them, so both
    are always None, for NBA and WNBA alike.
  - Same shape as this defect: a mechanism that exists in code and is inert in production.
    Wiring them would be a mechanism change on a calibrated engine, so it needs a re-fit
    (model-engine standard). Not done.
- The **NBA game model's margin barely follows its own `elo_diff`** (0.24 vs elo↔market
  0.81). The fleet appears to run the sklearn fallback (`cli.py:966-985`), so the NPU
  predictor may be unavailable. This is a game-model question for the NBA owners.
- The **outs cap of 5 saturates**: more than 50% of team-sides sit at 5 since 11-02. The
  outs signal (penalties AND the cap) is nearly constant now.
- `scripts/backtest_nba_lines_props.py:1111` reads `spread_margin`/`totals` from NBA
  predictions: the same mismatch in a backtest, so anything it reports as "game model"
  for 2026-27 NBA may be empty.

## Reproduce

- Scripts:
  - `C:\tmp\nba_margin0\margin0_corpus.py` and `C:\tmp\nba_margin0\margin0_skill.py`
    (copied out of the session scratchpad);
  - `C:\tmp\nba_margin0\lattice_scan.py` (fleet, read-only, `nice 19`).
- Read-only data: `C:\tmp\nba_margin0\preds\` (fleet predictions, `cp -p`) and
  `C:\tmp\nba_margin0\corpus_rows.json`.
- Run with `PYTHONHASHSEED=0` at Idle priority.

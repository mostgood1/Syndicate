# College basketball pregame sim → the boards

Lane `wncaab-module`, Phase 3. User decision 2026-11-02: pregame sims go **straight to the boards**
(Layer 1 projections and Layer 2 model rows, like NBA/WNBA). This doc is the pipeline trace that
`docs/ai_context/model_engine_standard.md` requires.

## What it is

The live tier's NCAAB engine, run from the opening tip. `GameState()` takes exactly the pregame code
path, seed for seed (`syndicate/features/basketball_engine/resume.py` docstring). Nothing new is
modelled. The inputs and switches are the live tier's, so a pregame number and a live number come from
the same engine configuration.

## Pipeline trace (file:line at each hop, and what it writes)

1. **Launch, live-odds-worker.**
   - `scripts/run_live_odds_refresh_worker.py:3218` calls `launch_autorun_ncaab_live_refresh()` every
     in-play tick.
   - That call reaches `syndicate/features/ncaab/inplay_lane.py:180` → `maybe_launch_pregame_sims("ncaab")`
     (`:142`).
   - It starts ONE child, at `nice -n 15`, when the last child has exited, 900 s have passed and the D1
     slate shows a pregame game today or tomorrow.
   - The child inherits the worker's env: `SYNDICATE_NCAAB_HALF_SPLIT`, `SYNDICATE_NCAAB_EXACT_TARGET`,
     `SYNDICATE_NCAAB_LIVE_MECHANISMS`.
   - Log lines: `COLLEGE_PREGAME_SIM_LAUNCHED`, `COLLEGE_PREGAME_SIM_EXITED rc=`.
2. **Child.**
   - `scripts/build_college_pregame_sims.py:21` `main` → `run_pregame_sims` (`:32`) per date, under one
     deadline (`--budget-seconds`, default 600).
3. **Producer.** `syndicate/features/college_basketball/pregame_sim.py:125` `run_pregame_sims`:
   - candidates are slate games that are neither in progress nor final and start in the future
     (`is_pregame`, `:82`);
   - inputs come from `_ncaab_engine_inputs` (`:114`), which calls
     `ncaab/live_resim.py:233` `build_engine_inputs`. That reads the team prior
     (`ncaab/live_team_model.py:252` `prior_for_game`, ratings table) and player priors
     (`live_resim.py:134` `load_player_priors`, `player_priors_<season>_asof_<date>.csv`);
   - a game is re-simmed only when `inputs_key` (`:99`) changes: ratings / priors dates, prior-season
     fallback, half split, mechanisms, exact target, sims;
   - the sim is `live_resim.py:460` `resim_live_game(inputs, GameState(), sims, seed=stable_seed(event_id, 0))`;
   - **writes** `<data_root>/<league>_source/data/pregame_sim/pregame_sim_<date>.json` (`artifact_path`,
     `:50`). It writes after every simmed game, and once at the end for refusals. Log line:
     `[college_pregame_sim] RUN ... simmed= unchanged= refused= not_reached= published=`.
4. **Join, refresh-worker book-grid build.**
   - `syndicate/features/shared/board_enrichment.py:2110` (ncaab/wncaab branch) →
     `shared/college_game_projections.py:103` `load_college_game_projections` (dates −1/0/+1) →
     `:155` `attach_college_game_projections`.
   - Each row is matched by `chip_join_key(league, name)` (`lookup`, `:82`) and priced by
     `_project_row` (`:124`) through `wnba_game_projections._projection_from_dist` +
     `_attach_sim_probability_edge` + `refuse_published_certainty`.
   - **Writes** `row["projection"]` on grid rows. The coverage it returns is reported under
     `enrichment.projections`.

## Prior calibration: the college fit (user 2026-11-03 "College model fit")

The engine is told what to produce by the team prior, and with the exact target on it reproduces it.
Measured 11-03 on the fleet, sim mean against prior: men slope 0.94 (129 games); the women's sim narrows
only blowouts over 25 points, by about 6 (the engine's efficiency bounds; fixed the same day, see "Cost and
known limits"). So the prior is what gets fitted, as an ESTIMATOR: the mean
margin and total move, pace and every engine rate stay.

1. **Fit, once a day after 11:00Z, in the pregame child.**
   - `scripts/build_college_pregame_sims.py:47` `refresh_prior_calibrations`. It is called at `:88` under
     `--refresh-inputs`, before any sim.
   - That calls `syndicate/features/college_basketball/prior_calibration.py:320` `refresh_calibration`:
     - it builds rows over the trailing 21 days of this season: `build_fit_rows` (`:261`), with the RAW
       prior via `prior_for_game(calibrate=False)`, the close via `live_resim.closing_home_margin` and
       `closing_totals` (`:227`), and the final from the slate;
     - it then runs `fit` (`:166`): margin' = beta·margin + gamma·[home site], and total' = target_mean +
       slope·(total − prior_mean);
     - the target is the close (≥ 60 games), else the final (≥ 80), else UNCALIBRATED by name;
     - out-of-range values are clamped and recorded;
     - `holdout` (`:190`) records a split-sample check: fit on even event ids, score the odd ones.
   - **Writes** `<league>_source/data/processed/prior_calibration_<season>_asof_<D-1>.json`.
   - Log line: `[college_prior_calibration] FIT league= as_of= rows= closes= finals= ...`, or `FIT_FAILED`.
2. **Apply.** `syndicate/features/ncaab/live_team_model.py:279` `prior_for_game` → `_calibrated` (`:303`):
   - the newest file of the game's season dated STRICTLY before the game (`calibration_for`, `:353`);
   - an uncalibrated or unreadable newest file serves the raw prior by name, never an older fit.
   Pregame and live sims both read it, so the live margin anchor compares like with like.
3. **Provenance.** `ncaab/live_resim.py:309` stamps `priorCalibration`, `rawPregameTotal` and
   `rawPregameHomeMargin`. `pregame_sim.py:106` puts the stamp in the inputs key, so a new fit re-sims
   the game.
4. **Gate.** `scripts/ncaab_live_input_checklist.py:174` reports the fit in force and FAILS when it is
   older than 3 days with the switch on (the daily refit stopped). No file at all is reported, not
   failed: a season's first days have none.

Measured before shipping (`deploys.md`, 2026-11-03 college model fit entry):

- **2025-26 walk-forward against finals.** Ratings come from games strictly before each date; both teams
  had ≥ 5 games; fit on Nov–Jan, judged on Feb–Apr.
  - Men's margins were already right (beta 1.007, gamma 0.06): the ratings builder's own
    `MARGIN_CALIBRATION_K` fit holds.
  - Men's totals were spread out (slope 0.70) and about 1.5 points low.
  - Women's margins were 12–19% too narrow, because they carry the men's K. Women's totals slope 0.80.
- **11-02/03 opener, men, against the close (135 games).** Margins: beta 1.115, gamma +2.25. Totals:
  slope 0.72. Split-sample against the close: margin RMSE 6.08 → 5.20, total RMSE 6.63 → 6.16.

**Spread and moneyline weight stays 0, by measurement.** On the opener, the prior's disagreement with
the close carried no information about the final margin: regressing (final − close) on (prior − close)
gives a coefficient of +0.04 over 116 games. The fit fixes what the board shows, not whether it has an
edge.

## Inputs: consumed vs populated

The pregame path consumes EXACTLY `build_engine_inputs`' output, nothing more. The gating input
checklist is therefore the live tier's own: `scripts/ncaab_live_input_checklist.py --date <D>` (team
model fields over the real ratings table; exits non-zero on a consumed-but-unpopulated field or thin
D-I coverage). Player priors with fewer than `MIN_ROTATION` projected players refuse the game by name
(`thin_rotation` / `team_has_no_player_priors`). Every refusal is published per game, without a
probability.

## Outputs the join reads (all populated by the producer)

- per entry: `home.key` / `away.key` (join);
- `dist.segments.{full,h1,h2}.{total,margin}` (histograms, home minus away in the slate's orientation);
- `sims_run`;
- `refused` (named, instead of `dist`).

Board rows label the full game `full_game` (NCAAB) or `full` (WNCAAB). The join maps both to `full`.

## Switches (absent = the stated default)

| env | default | effect |
|---|---|---|
| `SYNDICATE_COLLEGE_PREGAME_SIM` | on | `0` stops the launcher (reachability test: `tests/test_college_pregame_sim.py`) |
| `SYNDICATE_COLLEGE_PREGAME_INTERVAL_SECONDS` | 900 (floor 300) | gap between launches |
| `SYNDICATE_COLLEGE_PREGAME_BUDGET_SECONDS` | 600 (floor 60) | per-launch deadline |
| `SYNDICATE_COLLEGE_PREGAME_SIMS` | 200 (floor 100) | draws per game |
| `SYNDICATE_COLLEGE_PRIOR_CALIBRATION` | on | `0`/`off` serves the raw prior to pregame AND live sims (reachability: `tests/test_college_prior_calibration.py`) |

## Cost and known limits

- **Measured 2026-11-02 on the fleet (nice 19):** ~5.5–6 s per game at 100 sims, so a 120-game slate
  is ~22 CPU-minutes at 200. Three 11-03 games landed on their team-prior targets: total 146.7 vs
  149.5, 156.6 vs 156.0, 156.0 vs 153.0; margins within 0.2.
- **Tip quality is the team model's.** The P4 backtest (`docs/ai_context/ncaab_live_tier.md`) graded
  the engine at the tip as no better than the team model, and with the settled switches its total
  bias is +1.1 regular season / +4.0 tournaments. No book blend is applied (NBA's is NBA-fitted).
- **WNCAAB** (corrected 2026-11-03; this bullet said the women had no inputs): the women's ratings, preseason
  and player priors have been built since 11-02 and refreshed daily by the pregame child. The women's
  engine rules are `basketball_engine/league.WNCAAB`.
- **The engine's efficiency bounds (fixed 2026-11-03, lane wncaab-module).**
  - With the exact target on, the engine solves each team's efficiency multiplier to hit its points
    target. The vendored engine bounded that multiplier twice: the solve to 0.70–1.30
    (`basketball_engine/engine.py`, the EXACT_TARGET_CALIBRATION block), then a clip to 0.75–1.25
    after the team prior stacks on it.
  - A college mismatch needs a team far past both. The sim then fell short of its own target, and the
    calibration could not fix that: it moves the input, and the engine narrowed the result.
  - Both bounds are `LeagueParams` fields now (`exact_target_solve_bounds`, `eff_mult_final_bounds`).
    NBA/WNBA keep the vendored values (byte-identical, `tests/test_basketball_engine_eff_bounds.py`).
    NCAAB and WNCAAB use 0.40–2.00 for both.
  - The bounds are in the provenance (`effMultBounds`) and the pregame inputs key, so a new bound re-sims
    every published game.
  - **Measured 2026-11-03 on the fleet, offline.** The 11-03 + 11-04 slates were run three ways: 200
    sims each, the same seeds, the production worker's college switches. Harness: the vendored-bound arm
    reproduced every published sim to 0.00.
    - Sim minus target, vendored → 0.40–2.00:
      - women (39 games): total −4.29 → −0.81 (se 0.20); margin toward the favourite −5.65 → −0.49;
      - women, targets of 24+ points: −8.51 → −1.48 total and −11.56 → −0.93 margin;
      - men (27 games): total −0.98 → −0.20; margin −0.94 → −0.22.
    - 0.55–1.55 still bound in 5 women's games, all with 43–63-point targets such as 104–45. For the men
      it matched 0.40–2.00 exactly.
    - Games inside the vendored range are byte-identical: 17 of 39 women's, 20 of 27 men's.
    - Cost unchanged: ~9 s per game at 200 sims.
- **Prior calibration limits.**
  - The root of the women's narrow margins is the men's `MARGIN_CALIBRATION_K` in
    `build_ncaab_team_ratings.py`; the calibration corrects for it downstream.
  - The calibration file sits beside the ratings tables on the fleet disk. It is not in Render's
    `HOT_ARTIFACT_PATTERNS`, and neither are the women's tables: `artifact_publisher.py` belongs to other
    lanes, and the fleet serves from its own disk.

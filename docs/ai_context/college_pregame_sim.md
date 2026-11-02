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

## Cost and known limits

- **Measured 2026-11-02 on the fleet (nice 19):** ~5.5–6 s per game at 100 sims, so a 120-game slate
  is ~22 CPU-minutes at 200. Three 11-03 games landed on their team-prior targets: total 146.7 vs
  149.5, 156.6 vs 156.0, 156.0 vs 153.0; margins within 0.2.
- **Tip quality is the team model's.** The P4 backtest (`docs/ai_context/ncaab_live_tier.md`) graded
  the engine at the tip as no better than the team model, and with the settled switches its total
  bias is +1.1 regular season / +4.0 tournaments. No book blend is applied (NBA's is NBA-fitted).
- **WNCAAB:** no women's ratings or player priors exist yet, so every game refuses
  `no_engine_inputs_for_league` and the board reports it. Women's engine rules
  (`basketball_engine/league.py`) and the data producers are the next step.

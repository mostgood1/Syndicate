# Basketball live lens — fully Syndicate-native (NBA / WNBA / NCAAB)

**Decision (user, 2026-10-09):** the basketball live lens must model the scoring shape of
games from play-by-play and team models, including interval knowledge of bench rotations
and game-situation awareness (blowouts, Q4 / end-of-game scenarios). It must be **fully
contained in Syndicate and NOT reliant on the vendored app in any way.**

This doc is the shared plan. Each phase is a separate session with its own lane. Update the
**Status** table when a phase changes state; keep narrative in the daily log and `lanes.md`.

## Where things stand (measured 2026-10-09 on `origin/main`)

- **NBA live game lines** run the VENDORED tick in-process:
  `syndicate/features/nba/live_lens.py:97` imports
  `vendor.nba_betting_repo.app._live_lens_tick_payload` (`app.py` is 45,799 lines).
  - **Total** = actual + (sim_final - sim_at) along the PREGAME SmartSim cumulative
    interval ladder (`_live_interp_cum_p50`, app.py:2164). The ladder's shape calibrators
    (`intervals_time_profile.json`, `intervals_band_calibration.json`) are never built.
  - Recent pace, runs and droughts (`_recent_total_flow_context`) are computed and
    DISCARDED.
  - **ATS** blends the pregame margin toward the CURRENT margin
    (`w = elapsed/48`, ~app.py:44968).
  - **ML** = logistic(margin / (6 + 0.35·min_left)).
  - `board_enrichment._LIVE_GAMELINE_SPORTS` excludes nba, so NBA publishes ZERO live
    game-line edges.
- **NBA live props** also come from the vendored app (`/api/live_player_lens`,
  app.py:37785): live rotation stints (`_live_pbp_rotation_state` app.py:4108), a
  foul-trouble minutes cap, late-blowout starter caps and a Q4 end-game foul boost
  (app.py:39350).
- **WNBA live**: `wnba/live_lens.py:65` imports the vendored tick.
  - The native game lens in `wnba/cards.py` is a pace-adjusted LINEAR extrapolation
    (`_wnba_live_total_projection` :1155) with a CONSTANT logistic scale (:1038/:1097/:1210).
  - Props: `wnba_live_prop_projection.py`, `wnba_live_prop_probability.py` (a blowout
    minutes term), and `wnba/cards.py:5490` garbage time.
- **NCAAB**: score display only (`ncaab/live_lens.py`, 164 lines). It is not in
  `live_lens_loop._LIVE_LENS_SPORTS`.
- **The possession engine itself is vendored.**
  `shared/basketball_props_smart_sim.py:3275/3303` imports `vendor/*/sim/events.py`
  (2,209 lines; NBA vs WNBA copies differ by ~160 lines) and monkey-patches its
  `_sample_lineup`. `simulate_pbp_game_boxscore` (events.py:1262) cannot resume: it starts
  0-0 at :1505 and loops `for q in range(1, 5)` at :2059.
- **Known sim defects** (`.syndicate/findings_2026-10-06_basketball_scenario_calibration.md`
  :405-445):
  - no score-effect reversion: the H2-on-H1 slope is -0.001 in the sim vs -0.174 in
    real games;
  - garbage time scales both teams equally;
  - the only margin-dependent foul term favours the leader.
  - Possession alternation, quarter env SD and possession jitter are EXONERATED as the
    cause of over-wide margins (learnings 2026-10-07).
- **Rotation history**: `rotation_stints_history` has no producer. The sim's stint path
  always returns `no_rotation_stints_history`
  (`findings_2026-09-08_engine_room_audit.md:78`).
- **Template to follow**: `syndicate/features/nhl/live_resim.py`.
  - It refuses before it degrades.
  - Resuming at 0:00 is seed-identical to the pregame run.
  - It publishes source `live_resim` and a `pregame_only` lane on refusal, consumed by
    `live_gameline_join`.

## Phases

| # | Phase | Needs | Lane (fill in) | Status |
|---|---|---|---|---|
| P1 | Native possession engine + resumable state | — | `basketball-native-engine` | **DONE 2026-10-12 (lane CLOSED, GOAL MET)**: `syndicate/features/basketball_engine/` live since fleet `63a58748` (2026-10-09); parity 5,400/5,400 at the switch and again at close (c2ce211e); first native production sims healthy (`deploys.md` 2026-10-12 13:35Z). engine.py live-mechanism section now held by P3. |
| P2 | Native live game-state ingestion + rotation-stints producer | — (parallel with P1) | `basketball-native-live-state` | DONE 2026-10-10 (GOAL MET; deploys.md 2026-10-09 18:56:24Z, 20:34:28Z, 2026-10-10 14:25:14Z) |
| P3 | NBA native live re-sim, situations re-fit, cut the vendored tick | P1, P2 | `nba-native-live-resim` | **BUILT, NOT SWITCHED ON** (2026-10-12). `syndicate/features/nba/live_resim.py` resumes production's engine object from P2 state on persisted pregame inputs (live_resim / pregame_only lanes, named refusals, props, loop OFF unless `SYNDICATE_NBA_LIVE_RESIM`); gated engine-neutral (parity 5,400/5,400, e2e A/B 22/22, deploys.md 2026-10-10 01:13Z); input persist live in production 8/8 (deploys.md 2026-10-12 13:35Z); default-off end-game foul mechanism. NOT done: regular-season gate vs `pregame_rate` (running), mechanism re-fits, switch-on (user approval), board join, vendored-tick deletion. Readings: `.syndicate/findings_2026-10-09_nba_live_situation_targets.md` |
| P4 | NCAAB live tier on the native engine | P1, P2 (P3 helps) | `ncaab-native-live-tier` | BUILT 2026-10-12, OFF in production (`SYNDICATE_NCAAB_LIVE_RESIM`): P1 player engine + NCAAB player priors (+ roster preseason) resumed from P2 state, on the board (loan). Backtest 608 games: in-game totals beat the naive baseline (CI excl. 0), margin no gain, ML = ESPN WP; tip/H1 total overshoot +6..+10 and H2 -4 (no bonus mechanism). Owed: target-calibration test, fleet ff + switch-on (user), opening-week reading. `docs/ai_context/ncaab_live_tier.md` |
| P5 | WNBA cut-over to native live | P1, P2, P3 | `wnba-native-live-cutover` | **BACKTEST PASSED + GAME-LENS CUT-OVER BUILT, flag OFF** (2026-10-16). Native re-sim vs linear lens (2026 regular season): ML Brier end Q2 -0.0115 / end Q3 -0.0085, over end Q3 -0.0058 (CIs exclude 0), nothing worse. Scope by user decision: game lens only (wnba/cards.py, wnba/live_resim.py, SYNDICATE_WNBA_LIVE_RESIM); the vendored tick is nba-live-tick-native's port. Live reading + switch-on owed at the 2027 opener (#694). |
| P6 | Native smart-sim ORCHESTRATOR (`sim/smart_sim.py:simulate_smart_game` + its vendored callees) | P1 | `basketball-native-orchestrator` | **SHIPPED 2026-10-10** (fleet ff 45e03ae2 -> `24d7b19c`, no restart; `deploys.md` 14:39:11Z). Parity on real production games, same seed: NBA 22 games / 8 dates, 862,659 leaves; WNBA 13 games / 8 dates, 265,118 leaves; 0 differences; all 34 end-to-end `smart_sim_*.json` byte-identical. Re-verified on the DEPLOYED checkout: both arms identical, and no vendored module loads. Team-advanced-stats builders ported too (24 DataFrame comparisons, 0 differences). The sim bridge imports no vendored module. First newly simulated production games healthy (NBA 10-11, 4 games, 05:43Z; `deploys.md`). Remaining vendored uses OUTSIDE the sim: see the P6 section. Biggest: the ONNX props models in `vendor/*/models`, read on every props run |

### P1 — native possession engine + resumable state
- Port the possession engine into a Syndicate package as ONE league-parametric engine
  (`nba`, `wnba`; leave hooks for `ncaab`: 2x20 halves, 30 s shot clock, foul-out at 5,
  college bonus rules). Do not copy the vendored module's globals-patching: lineup sampling
  becomes a parameter.
- **Parity gate before switching anything:** with fixed seeds and identical inputs, the
  native engine reproduces the vendored engine's outputs EXACTLY. Use a recorded corpus of
  real production sim inputs, several dates per league, including the
  `_sample_lineup_local` override. Then switch `basketball_props_smart_sim.py` to native and
  delete `_import_real_events_module_local` / `_call_real_events_entrypoint_local`. The
  flat fallback goes too.
- **Resume API:** start from (period, seconds remaining, score, team fouls / bonus, player
  fouls, players on floor, possession). Prove a resume at the opening tip is
  seed-identical to the pregame run, as the NHL docstring does, and that a resumed state
  moves the answer the right way and monotonically.
- Model engine standard (`docs/ai_context/model_engine_standard.md`):
  - an input checklist over `dataclasses.fields()` that exits non-zero;
  - a pipeline trace;
  - a reachability test.
- NO behaviour change in P1. Re-fits belong to P3.

### P2 — native live game-state ingestion + rotation-stints producer
- A Syndicate-owned live feed for NBA / WNBA / NCAAB, from ESPN summary / pbp (plus the
  NBA CDN if needed). It produces a typed `LiveGameState`: period, clock, score,
  possessions, team fouls / bonus, player PF, on-floor five, stint log and timeouts.
- It replaces the vendored tick's pbp parsing (app.py:3222-3773, 4108).
- Disk-backed under `SYNDICATE_DATA_ROOT`. Check `_keyvalue_backed` before choosing a path.
  The 8 MB keyvalue cap refused the NBA lens on 2026-10-08, and a payload carrying pbp
  history must be sized.
- **Historical rotation stints producer** (`rotation_stints_history`): per team, per
  player, on/off intervals by game clock, from completed games' pbp. Scheduled, dated,
  allowlisted. This is the "interval-based knowledge of bench rotations".
- Verify against real completed games: reconstructed final scores and box minutes match
  the official box score.

### P3 — NBA native live re-sim (needs P1 + P2)
- Resume the native engine from P2's `LiveGameState` each tick, N seeded sims under a
  time budget, to produce:
  - live total / spread / ML;
  - quarter and half markets;
  - live player props (minutes from the resumed rotation + foul state).
- **Game-situation mechanisms**, each behind a reachability test, then a re-fit of the
  rates that were absorbing them (mechanism vs estimator, measured negative interaction
  in 4 of 4 markets):
  - score-effect reversion;
  - asymmetric garbage time (bench minutes for the LEADING team, trailing-team pace);
  - end-of-game intentional fouling and clock management;
  - foul trouble;
  - bench rotation intervals from P2's stints history.
- Backtest on historical pbp at in-game checkpoints (end of Q1/Q2/Q3, 5:00 Q4). Grade
  against the final and the live close. Report the population per checkpoint.
- Publish source `live_resim`; add nba to `_LIVE_GAMELINE_SPORTS` and
  `live_gameline_join` sources.
- **DELETE** `from vendor.nba_betting_repo.app import _live_lens_tick_payload` and every
  other vendored call on the NBA live path. Refusals are named, not silent.
- Verify on live NBA games on the local fleet (preseason now, regular season from ~10-20):
  served lens reads `live_resim`, edges published, keyvalue size under cap.

### P4 — NCAAB live tier (needs P1 + P2)
- NCAAB league parameters for the engine. Team model from the NCAAB efficiency ratings
  producer (`f7ecf2d4`, adjusted O/D/tempo).
- A live lens builder registered in `_LIVE_LENS_SPORTS`, with game lines first and props
  only if a player model exists.
- Season opens early November 2026. Backtest on 2025-26 pbp before then; take the live
  reading on opening week.

### P5 — WNBA cut-over (needs P1 + P2 + P3)
- Replace the vendored tick and the linear `_wnba_live_*` lens with the P3 machinery under
  WNBA parameters.
- Delete the vendored imports in `wnba/live_lens.py` and `wnba/cards.py`.
- The season is over: verify by backtest on the 2026 season's pbp. The live reading is owed
  at the 2027 opener; say so in the lane.

### P6 — native smart-sim orchestrator (needs P1)
- Port `vendor/{nba,wnba}_betting_repo/src/*/sim/smart_sim.py:simulate_smart_game`, and everything it calls, into
  ONE league-parametric orchestrator (`syndicate/features/basketball_engine/orchestrator/`). The ~20 (in fact 29)
  helpers Syndicate had already replaced become direct calls (`hooks.py`). No globals are patched.
- Method, as P1: a port script with anchored edits (`scripts/port_basketball_orchestrator.py`), then a parity gate on
  real production games before the switch (`scripts/basketball_orchestrator_parity.py`). The standard's checklist,
  pipeline trace (`basketball_sim_engine_reference.md` Sec10) and reachability tests come with it.
- Also ported (pass 2), because the bridge imported them on the sim path: the team-advanced-stats BUILDERS
  (`advanced_stats_{boxscores,player_logs}`). The forks differ in algorithm, so each fork's divergent function is
  kept verbatim behind a `fork` switch.

**NBA FROZEN 2026-10-19** (lane nba-vendor-deletion-prep, user decision): `basketball_engine/engine.py`, `basketball_engine/orchestrator/`,
`nba/live_tick/` and `nba/source_cli/` are maintained source (`syndicate/features/basketball_engine/FROZEN_FROM_VENDOR.md`); the engine and orchestrator generators
are retired and the live-tick / source-CLI generators keep their WNBA arm only. Production ran no vendored NBA code
before this (`.syndicate/findings_2026-10-19_nba_vendor_deletion_scope.md`).
**WNBA FROZEN 2026-10-20** (lane `wnba-vendor-deletion-prep`, user decision): `wnba/live_tick/` and `wnba/source_cli/` are maintained
source too, and the live-tick / source-CLI generators are retired. Production ran and read nothing from the vendored WNBA tree
before this (`.syndicate/findings_2026-10-20_wnba_vendor_deletion_scope.md`); the two schedule rows below had already moved.

**Vendored uses that REMAIN on basketball paths outside the sim** (inventory 2026-10-09, line numbers on
`origin/main` at that date). Each needs its own decision; none is in P6's scope:

| area | where | what it uses | runs |
|---|---|---|---|
| ~~sim inputs (data, not code)~~ **MOVED 2026-10-12** (lane `basketball-props-models-native`) | `basketball_props_predictions.py` `_models_dir_for_source_root` | now `syndicate/features/basketball_engine/props_models/<league>` (byte-identical, git-tracked copies of the props files; `<source_root>/models` still wins). The vendor copies remain ONLY for vendored paths: WNBA `daily-update` fallback step 11 and `playoff_transition` retraining | fleet A/B: identical predictions, 287,680 cells |
| ~~live lens (NBA)~~ **MOVED 2026-10-12** (lane `nba-live-tick-native`, loan from P3) | `nba/live_lens.py` `_run_nba_live_lens_tick` | now `syndicate/features/nba/live_tick/`, generated by `scripts/port_basketball_live_tick.py` (see "Basketball live tick port" below). P3's native re-sim replaces a call to this port instead of the vendored import | every live-lens tick, live-odds-worker |
| ~~live lens (WNBA)~~ **MOVED 2026-10-12** (lane `nba-live-tick-native`, user request) | `wnba/live_lens.py` `_run_wnba_live_lens_tick` | now `syndicate/features/wnba/live_tick/`, same generator. P5's cut-over replaces a call to this port | every live-lens tick, live-odds-worker |
| ~~loop~~ **MOVED** (found 2026-10-19 by lane `nba-vendor-deletion-scope`) | `live_refresh_loop.py` `fetch-injuries` | now `python -m syndicate.features.<league>.source_cli.cli fetch-injuries` | every lineup-check interval |
| loop | `live_refresh_loop.py:4204` | `vendor/wnba_betting_repo/data/processed/schedule_2026.json` | always (WNBA commence times) |
| ~~history~~ **MOVED 2026-10-12** (lane `nba-live-tick-native`, loan from `nba-season-phase`) | `nba_history_refresh._vendor_fetch` | now `syndicate/features/shared/nba_player_logs_fetch.py`, a verbatim copy (AST-identical, `tests/test_nba_player_logs_fetch.py`); a live fleet A/B pulled 2025-26 through both: 26,651 rows, identical frames | 6 h throttle |
| ~~WNBA refresh: CLI game-input bootstrap~~ **MOVED 2026-10-13** (lane `nba-source-cli-native`, user decision) | `refresh_wnba_oddsapi_props._run_source_subprocess_cli_command`, `_run_source_predict_date` | now `python -m syndicate.features.wnba.source_cli.cli` from this repo: generated port (`scripts/port_basketball_source_cli.py --league wnba`) of fetch-schedule, fetch, build-features, fetch-injuries, write-pregame-expected-minutes, predict-date (25 modules / 8,313 lines; models copied byte-identical). Fleet parity, full bootstrap for slate 2026-10-17: 6/6 steps ok, 202,372 leaves, 0 diffs (`scripts/basketball_source_cli_parity.py --league wnba`). The vendored `daily-update` CPU retry on a predict-date failure was removed (0 fires in 30 days of logs; not ported) | every refresh |
| ~~WNBA refresh~~ **MOVED 2026-10-12** (lane `wnba-live-period-lines-native`) | `refresh_wnba_oddsapi_props._build_source_live_lines_payload` | now `syndicate/features/wnba/live_period_lines.py`, a port of the vendored app's `_live_oddsapi_period_totals_for_game` (parity on mocked OddsAPI responses, every branch); no vendored app import on that path. SHIPPED fleet e256bf42 (deploys.md 2026-10-12 17:42:14Z); live in-progress reading owed (GSV v ATL 10-17 or the 2027 opener) | was: every live-snapshot export while games are live |
| ~~WNBA refresh: source-app fallback~~ **REMOVED 2026-10-13** (lane `nba-source-cli-native`, user decision) | was `_load_source_app` (vendored app via the vendor-tree fallback root) + its branches | flagged branches dead (`SYNDICATE_WNBA_SOURCE_APP_FALLBACK=false` on every role). One branch was UNGATED: an empty local smart-sim build made cards_sim_detail import the vendored app and write from `/api/cards`; measured 09-24..10-13 only on no-game dates (the route returned the NEXT games' sims). Now no local games -> no file (`tests/test_wnba_source_app_fallback_removed.py`). `render.yaml` still declares the key (dead config, not pushed) | -- |
| ~~WNBA refresh~~ **REMOVED 2026-10-12** (lane `wnba-playoff-transition-off-vendor`) | was `refresh_wnba_oddsapi_props._run_playoff_transition_if_needed` | `wnba_betting.playoff_transition` never fired for WNBA: it keys on NBA game ids and `YYYY-YY` seasons, so it raised and returned `skipped` for every 2026 date (measured on the fleet; no receipt, no models). Removed, not ported. The NBA twin (`refresh_nba_oddsapi_props.py`) is `unavailable` on the fleet (no `nba_source/src`) | was: every WNBA run |
| ~~WNBA refresh: totals calibration~~ **MOVED 2026-10-13** (lane `nba-source-cli-native`) | `_ensure_wnba_totals_calibration` -> `scripts/build_wnba_totals_calibration.py` | imports `cli`, `config.paths`, `features_enhanced`, `games_npu` from `syndicate.features.wnba.source_cli` (the port `predict-date` runs; byte-identical models). Fleet A/B on copies of prod data, slates 08-15/09-20/10-07/10-17: prediction frames and calibration terms byte-identical (8/8 files; bias 13.282/11.024/10.334/11.304), the new arm loads no `wnba_betting` module (`tests/test_wnba_totals_calibration_native.py`) | daily |
| ~~WNBA refresh: history seed + predictions copy~~ **MOVED 2026-10-13** (lane `nba-source-cli-native`) | `_seed_games_history_from_checkout_if_fresher`, the predictions copy after the bootstrap | the seed reads `syndicate/features/wnba/seed_data/games_nba_api.csv` (blob-identical; the fleet history is fresher, so only a cold start can use it); the vendored `predictions_<date>.csv` candidate (only 05-27, 05-28, 10-01 exist) was removed; `_vendor_code_root` deleted | cold start / missing artifacts |
| ~~WNBA refresh: history builders' schedule~~ **MOVED 2026-10-13** (lane `nba-source-cli-native`, user decision; not in the 10-09 inventory) | `_refresh_derived_basketball_artifacts` -> `scripts/build_basketball_{player_logs,home_court_advantage}.py` `_schedule_path` | was the vendored `schedule_2026.csv` (frozen 09-25, no post-season): player_logs.csv stuck at 09-24 all playoffs (490 rows / 16 games unjoinable). Now the data-root `schedule_<season>.csv` that `fetch-schedule` rewrites each run. Fleet A/B: player_logs 8,653 -> 8,984 rows (old rows identical, +331 rows / 13 playoff games, newest 10-09); HCA kept regular-season only (`include_postseason=False`), bit-identical (313 games, delta 0.0081673) (`tests/test_basketball_history_schedule_native.py`) | every WNBA refresh |
| ~~WNBA refresh: recon tools~~ **MOVED 2026-10-13** (lane `nba-source-cli-native`) | `_build_local_optional_player_recon_artifacts` | loads `syndicate/features/wnba/recon_tools/{build_recon_players,build_live_player_lens_tuning}.py`, the vendored tools' bytes under a comment header (the lens-tuning tool's UTF-8 BOM moved above it; `tests/test_wnba_recon_tools_native.py`); fleet A/B on 4 dates (10-02/04/07/09): identical frames (recon_players 22/44/20/39 rows, lens tuning 57/56/31/42) | when player recon artifacts are missing |
| ~~NBA refresh: CLI game-input bootstrap + full-export `export-game-cards`~~ **MOVED 2026-10-12** (lane `nba-source-cli-native`) | `refresh_nba_oddsapi_props._run_source_subprocess_cli_command`, `_run_source_predict_date` | now `python -m syndicate.features.nba.source_cli.cli` from this repo: a generated port (`scripts/port_basketball_source_cli.py`) of the 8 commands (fetch-schedule, fetch, build-features, fetch-injuries, update-pbp-espn-history, build-lineup-teammate-effects, export-game-cards, predict-date), 21 modules / 7,553 lines, models copied byte-identical to `source_cli/repo/models`. Fleet parity, full bootstrap for slate 2026-10-13: 8/8 steps ok, 804,491 leaves, 0 diffs (`scripts/basketball_source_cli_parity.py`). 2026-10-13: update-pbp-espn-history and build-lineup-teammate-effects dropped from both refreshes and the port (lineup teammate effects retired; nothing reads their outputs), so 6 commands remain | once per date + every full export |
| ~~NBA refresh: history seed + predictions copy~~ **MOVED 2026-10-12** (lane `nba-source-cli-native`) | `_seed_games_history_from_checkout_if_fresher`, the predictions copy after the bootstrap | the seed reads `syndicate/features/nba/seed_data/games_nba_api.csv` (blob-identical to the vendored one; only a cold start can use it); the vendored `predictions_<date>.csv` candidate was removed (the vendored tree has none) | cold start / missing artifacts |
| ~~NBA refresh: recon tools~~ **MOVED 2026-10-12** (lane `nba-source-cli-native`) | `_build_local_optional_player_recon_artifacts` | loads `syndicate/features/nba/recon_tools/{build_recon_players,build_live_player_lens_tuning}.py`, the vendored tools' bytes under a comment header (`tests/test_nba_recon_tools_native.py`); fleet A/B on 3 dates: identical frames (recon_players 105/203/137 rows) | when player recon artifacts are missing |
| ~~NBA refresh: source-app fallback~~ **REMOVED 2026-10-13** (lane `nba-source-cli-native`, user decision) | was `_load_source_app` + 5 branches behind `SYNDICATE_NBA_SOURCE_APP_FALLBACK` (game cards, season betting card, cards sim detail, recon games, live lens / snapshot exports), plus the dead `_run_source_cli_command`/`_load_source_cli` | it could not run: the flag is false on every fleet role and the data bundle has no app.py; each branch replaced by its flag-off behaviour (`tests/test_nba_source_app_fallback_removed.py`). `render.yaml` still declares the key (dead config; not pushed, `blueprint_sync`) | -- |
| ~~NBA refresh: playoff transition~~ **REMOVED 2026-10-13** (lane `nba-source-cli-native`, user decision) | was `_run_playoff_transition_if_needed` + its receipt copy | never ran (loaded a data-disk `src` copy absent on the fleet: `unavailable` every run); had it run, it would have retrained game + props models, run 4 calibration scripts and rewritten the live-lens tuning override. Playoff retraining is a separate decision (`tests/test_nba_playoff_transition_removed.py`) | -- |
| ~~schedule~~ **MOVED** (found 2026-10-19 by lane `nba-vendor-deletion-scope`) | `schedule_adapter.py` `fetch-schedule` | now `python -m syndicate.features.<league>.source_cli.cli fetch-schedule` | fallback when no schedule file |
| identity | `wnba_fixture_identity.py:73` | the vendored `schedule_2026.csv` | always, when present |
| ~~boot~~ **REMOVED 2026-10-12** (lane `wnba-bootstrap-src-off-vendor`) | `scripts/bootstrap_data_root.py` `BOOTSTRAP_VENDOR_ROOTS` | no longer copies `vendor/wnba_betting_repo/src` onto the data disk; the vendored-app fallbacks load the vendor tree's own `src` (`_load_source_app`). The copy already on the fleet disk is left in place, unused | was: every boot |

Board and analytics helpers (`basketball_market_board.py`, `game_shape.py`, `basketball_momentum.py`,
`basketball_pbp.py`, `basketball_live_state.py`) and the NBA/WNBA cards only MENTION the vendored app in comments;
no runtime dependency was found there.

**Basketball live tick port** (2026-10-12, lane `nba-live-tick-native`; NBA, then WNBA at the user's request).
Faithful copy, not a re-model: P3's (NBA) and P5's (WNBA) re-sims are what replace the model.
- **What was ported.** Not only `_live_lens_tick_payload` (46 functions). The tick calls four vendored ROUTES
  in-process through `app.test_client()` (`/api/live_lens_tuning`, `/api/live_lines`, `/api/live_pbp_stats`,
  `/api/live_player_lens`), so the closure is **112 app.py functions (~10.3k lines) for NBA and 119 (~10.2k)
  for WNBA**. It also includes the `<league>_betting` `odds_api` / `teams` / `player_names` / `odds_bovada` (and
  WNBA `league`) closures and three helpers from `tools/daily_live_lens_audit.py`.
- **Generator.** `scripts/port_basketball_live_tick.py --league nba|wnba|all` (`--check` catches a hand edit).
  - It uses a scope-correct `symtable` closure and copies statements verbatim behind a hand-written import
    header. Every `<league>_betting.*` import becomes package-relative, and the audit-module loader imports the
    port. Package-module roots are solved to a fixed point from what the generated code imports.
  - A private Flask app carries only the four routes; the vendored minimal-UI `before_request` allowlist
    admits all four.
  - Validation: every global is bound and nothing vendored is imported, except the names in `KNOWN_UNDEFINED`.
- **Vendored defect FIXED in the port (WNBA, user decision 2026-10-12).**
  `_live_oddsapi_player_props_for_game._update_registry_bucket` reads `current_last_updates`, but the WNBA copy lost
  that keyword parameter (the NBA copy has it) while every caller still passes it.
  - Effect: each call raised TypeError and the enclosing `try` swallowed it. The WNBA live-props registry
    (`processed/live_lens_registry/`) was never written, and the first/last-seen, first/last line and price and
    observation maps the live player lens reads stayed `{}`. On the fleet the WNBA live tick ran on 12 days with
    no registry directory at all; NBA has one.
  - The port restores the parameter. It is the generator's only FIX (`FIXES`), and `--without-fixes` regenerates
    the verbatim, parity-proven text.
  - `tests/test_basketball_live_tick_fixes.py` pins that the two differ by exactly that line. It also checks the
    fixed port writes the registry and fills the maps on synthetic OddsAPI responses, while the verbatim text
    (the control) writes nothing and leaves them empty, with every other returned key identical.
  - The 2026-10-09 doctored parity never reaches this code (no OddsAPI event matched that slate), so it still reads
    0 diffs with the fix in place.
- **Behaviour that is deliberately not carried over** (none changes the tick's output on the fleet):
  - The vendored IMPORT ran `nba_betting.config.reconcile_repo_data_to_active()`. It copies the vendored
    repo's `data/` into the data root whenever the repo copy is newer. Fleet dry-runs on 2026-10-12 would copy
    0 of 178 (NBA) and 0 of 288 (WNBA) files, so the copy had converged; it could only matter after a vendor
    re-pull.
  - It also ran `load_dotenv()`. No `.env` exists on the fleet.
  - The vendored "repo data" fallback dir is now the data root itself, and every reader de-duplicates.
    - NBA: the vendored dir holds none of the files its readers look for (`live_lens_tuning_override.json`,
      `live_lens_adjustments_optimized_*`, `smart_sim_<date>_*`).
    - WNBA readers also look for `game_odds_` / `predictions_` / `closing_lines_` / `odds_` / `market_<date>`
      repo-first. The vendored copies are dated 2026-05-25..28 and 2026-10-01 only, and a live tick reads the
      slate in progress.
  - WNBA `BASE_DIR` / `WEB_DIR` point at a directory that does not exist. The two files read there
    (`predictions_<date>.csv` at the repo root, `web/assets/teams_wnba.json`) do not exist in the vendored tree.
  - Without the env var, the data root defaults to `data/<league>_source/data`, not the vendored repo. WNBA keeps
    the vendored order: `WNBA_BETTING_DATA_ROOT`, legacy `NBA_BETTING_DATA_ROOT`, then `/opt/render/project/data`.
- **Trace.** `live_lens_loop` (live-odds-worker, `SYNDICATE_ENABLE_LIVE_LENS_LOOP=true`) → `<league>/live_lens.py`
  `build_live_lens_snapshot` → `_run_<league>_live_lens_tick` → `<league>.live_tick.tick._live_lens_tick_payload`.
  The NBA tick is described below; the WNBA tick is the same with `WNBA_*` names.
  - **Reads:** ESPN/NBA-CDN scoreboards and summaries, OddsAPI events and odds, Bovada period lines (the
    network); `$NBA_BETTING_DATA_ROOT/processed/**`, about 3.5k files and 365 MB per tick on 2026-10-12:
    pbp_events, rotation_stints, cards_sim_detail, game_odds, props files; `$NBA_LIVE_LENS_DIR` (tuning
    override, momentum).
  - **Writes:**
    - `$NBA_LIVE_LENS_DIR/live_lens_{signals,projections}_<date>.jsonl`, read by `nba/cards.py`;
    - `processed/live_lens_registry/oddsapi_props_<date>_<event>.json`;
    - `processed/player_ids.csv`.
- **Parity.** `scripts/basketball_live_tick_parity.py --league nba|wnba`.
  - It records the vendored tick against the live network, with a call-counted clock, frozen `datetime`, the
    OddsAPI key stripped and each arm on its own copy of the data.
  - It then replays the port and the vendored tick (self-check) and compares every leaf of the return value
    plus every written file, the clock-call count and the tape misses. A planted change is the positive control.
  - `--doctor-live` rewrites a finished slate to read as in progress in ESPN scoreboards. It is for WNBA, which
    has no live game before Finals Game 1 on 2026-10-17. Both arms get the same doctored bytes, and the tape is
    marked. The live recording at Finals Game 1 is still owed.
  - Results: `deploys.md`. The suite keeps one recording, cut down by `reduce`
    (`tests/test_basketball_live_tick_parity.py`, one fixture per league).

## End-state check (whoever closes the last phase runs it)
`git grep -n "nba_betting_repo\|wnba_betting_repo\|vendor\." -- syndicate/features/nba
syndicate/features/wnba syndicate/features/ncaab syndicate/features/shared/basketball*
syndicate/features/shared/nba* syndicate/features/shared/wnba*
syndicate/features/shared/live_lens_loop.py` must return no runtime import on the
live-lens or sim path.

Vendored use OUTSIDE the live lens and sim (odds fetch, refresh scripts,
`schedule_adapter.py`, `live_refresh_loop.py`, `basketball_market_board.py`,
`game_shape.py`, `basketball_momentum.py`) is listed here, not silently out of scope. It
needs its own decision.

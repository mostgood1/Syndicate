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
| P1 | Native possession engine + resumable state | — | `basketball-native-engine` | **SHIPPED 2026-10-09** (fleet `63a58748`, no restart): `syndicate/features/basketball_engine/` (one engine, LeagueParams, `GameState` resume); parity 5,400/5,400 real production calls + 8 same-seed end-to-end sims identical on the deployed checkout (`deploys.md` 21:29:34Z). Owed: first newly simulated game on native. The vendored orchestrator gap P1 flagged is CLOSED by P6 (984312a8/38deec5c; the bridge loads no vendored module, verified 2026-10-10) |
| P2 | Native live game-state ingestion + rotation-stints producer | — (parallel with P1) | `basketball-native-live-state` | DONE 2026-10-10 (GOAL MET; deploys.md 2026-10-09 18:56:24Z, 20:34:28Z, 2026-10-10 14:25:14Z) |
| P3 | NBA native live re-sim, situations re-fit, cut the vendored tick | P1, P2 | | not started |
| P4 | NCAAB live tier on the native engine | P1, P2 (P3 helps) | `ncaab-native-live-tier` | blocked on P1/P2; prerequisite-free work DONE 2026-10-09 (`9002f65e`): the ONE shared rulebook `shared/basketball_league_rules.py` (P1 and P2 pin to it), NCAAB team-model inputs `ncaab/live_team_model.py` + checklist, 2025-26 pbp corpus (6,275 games, local) and baseline-to-beat + scoring shape (`docs/ai_context/ncaab_live_tier.md`: H2 +8.0 pts over H1, reversion -0.187, last-2:00 trailing fouls 1.6/min). No NCAAB player model, so game lines only. Live close needs OddsAPI in-play history (user decision). Live reading owed at opening week, Nov 2026 |
| P5 | WNBA cut-over to native live | P1, P2, P3 | `wnba-native-live-cutover` | blocked on P1-P3; prerequisite-free work DONE 2026-10-09: 2026 checkpoint corpus v2 (346 games; state = P2 LiveGameState, anchors = production smart-sim index) + vendored-call inventory + linear-lens baseline incl. cover/over (`.syndicate/findings_2026-10-09_wnba_live_vendored_inventory.md`). End-state grep must be widened (see findings). Live reading owed May 2027 (`#694`) |
| P6 | Native smart-sim ORCHESTRATOR (`sim/smart_sim.py:simulate_smart_game` + its vendored callees) | P1 | `basketball-native-orchestrator` | parity gate PASSED 2026-10-10 on real production games, same seed. NBA 22 games / 8 dates, 862,659 leaves. WNBA 13 games / 8 dates, 265,118 leaves. 0 differences in both, and all 34 end-to-end `smart_sim_*.json` byte-identical. Team-advanced-stats builders ported too (24 DataFrame comparisons, 0 differences). After the switch the sim bridge imports no vendored module. Fleet ff pending user approval. Remaining vendored uses outside the sim: see the P6 section (ONNX props models in `vendor/*/models` read on every props run) |

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

**Vendored uses that REMAIN on basketball paths outside the sim** (inventory 2026-10-09, line numbers on
`origin/main` at that date). Each needs its own decision; none is in P6's scope:

| area | where | what it uses | runs |
|---|---|---|---|
| **sim inputs (data, not code)** | `basketball_props_predictions.py:149` `_models_dir_for_source_root` | ONNX props models read from `vendor/<pkg>_repo/models` | effectively every props run (the data root has no `models/`) |
| live lens | `nba/live_lens.py:97`, `wnba/live_lens.py:65` | the vendored app's `_live_lens_tick_payload` | every live-lens tick (P3 / P5 own) |
| loop | `live_refresh_loop.py:664` | `python -m <pkg>.cli fetch-injuries` | every lineup-check interval |
| loop | `live_refresh_loop.py:4204` | `vendor/wnba_betting_repo/data/processed/schedule_2026.json` | always (WNBA commence times) |
| history | `nba_history_refresh.py:43,48` | `nba_betting.player_logs._fetch_season_player_logs` | 6 h throttle |
| WNBA refresh | `refresh_wnba_oddsapi_props.py` `_ensure_source_game_inputs` (:3846, :3924, :3975; :3878, :3907, :3801-3806, :4002) | `python -m wnba_betting.cli` fetch-schedule / fetch-injuries / predict-date (+ fetch, build-features, rotation builders, daily-update) | every full export (some when stale / per date / on failure) |
| WNBA refresh | `refresh_wnba_oddsapi_props.py:5778` -> :514/:537 | the vendored WNBA Flask app's `_live_oddsapi_period_totals_for_game` | every live-snapshot export while games are live, NOT flag-gated |
| WNBA refresh | `:6064`; `:824`, `:6187`, `:6297` | vendored app `/api/cards`; live exports | fallback / `SYNDICATE_WNBA_SOURCE_APP_FALLBACK` |
| WNBA refresh | `:5740` | `wnba_betting.playoff_transition` from `<source_root>/src` (the vendored copy `bootstrap_data_root.py:49` places there) | every run |
| WNBA refresh | `:142` -> `build_wnba_totals_calibration.py:105-114` | `wnba_betting.cli`, `config.paths`, `features_enhanced`, `games_npu` | daily |
| WNBA refresh | `:1305`, `:4529`; `:5676-5706` | vendored history seed / predictions copy; vendored recon and lens-tuning tools | fallback; when artifacts are missing |
| NBA refresh | `refresh_nba_oddsapi_props.py:840` | `python -m nba_betting.cli export-game-cards` | every full export |
| NBA refresh | `:2553-2679`, `:764`, `:2998`, `:3678-3704`, `:3826` | CLI game-input bootstrap, history seed, predictions copy, recon tools, source app | fallback / missing artifacts / `SYNDICATE_NBA_SOURCE_APP_FALLBACK` |
| schedule | `schedule_adapter.py:237` | `python -m <pkg>.cli fetch-schedule` | fallback when no schedule file |
| identity | `wnba_fixture_identity.py:73` | the vendored `schedule_2026.csv` | always, when present |
| boot | `scripts/bootstrap_data_root.py:49,338` | copies `vendor/wnba_betting_repo/src` onto `<data_root>/wnba_source/src` | every boot |

Board and analytics helpers (`basketball_market_board.py`, `game_shape.py`, `basketball_momentum.py`,
`basketball_pbp.py`, `basketball_live_state.py`) and the NBA/WNBA cards only MENTION the vendored app in comments;
no runtime dependency was found there.

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

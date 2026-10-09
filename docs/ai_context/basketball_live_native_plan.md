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
| P1 | Native possession engine + resumable state | — | | not started |
| P2 | Native live game-state ingestion + rotation-stints producer | — (parallel with P1) | | not started |
| P3 | NBA native live re-sim, situations re-fit, cut the vendored tick | P1, P2 | | not started |
| P4 | NCAAB live tier on the native engine | P1, P2 (P3 helps) | | not started |
| P5 | WNBA cut-over to native live | P1, P2, P3 | | not started |

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

# MLB live lens: what a port off the vendored app would have to carry `[2026-10-15, session 2d413211, lane mlb-live-lens-port-scope]`

**Question (user, 2026-10-15):** "move the mlb odds fetch off vendor". The odds fetch is already native: `scripts/fetch_mlb_oddsapi_local.py` has no vendor reference. The vendored use in that refresh is the **MLB live-lens report builder**. The user chose to scope a generated port before building anything.

## Where vendor is used today

- `scripts/refresh_mlb_oddsapi.py` `_build_local_live_lens_reports_payload` (:225):
  - loads `vendor/mlb_bettingv2/tools/web/flask_frontend.py` by path and calls `_live_lens_reports_payload(date, include_archive=False, slim=True)`;
  - runs at :1162 on each MLB refresh whose live-lens input hash changed, after trying the remote cron endpoint (`MLB_BETTING_BASE_URL` + cron token).
- `scripts/run_live_odds_refresh_worker.py:43` imports `start_live_lens_background_loop` from the same vendored app.

## Closure of those two entry points inside flask_frontend.py (21,040 lines)

Measured with an AST + symtable global-reference walk, in the spirit of `scripts/port_basketball_live_tick.py` (conservative: it may over-include).

- **562 top-level names:** 447 functions, 1 class, 56 module-level assignments.
- **13,609 source lines** (65% of the file).
- **Vendored packages reached:**
  - `sim_engine` (+ `live_mc`, `live_prop_ranking`, `market_pitcher_props`, `forward_tuning`, `data.roster_artifact`, `data.statsapi`);
  - `tools.daily_update_multi_profile`;
  - `tools.eval.build_season_eval_manifest`;
  - `tools.eval.settle_locked_policy_cards`;
  - `tools.oddsapi.fetch_daily_oddsapi_markets`.
  - Each has its own closure. `sim_engine.live_mc` is MLB's live Monte Carlo engine.
- **In-process Flask routes:** none. Only `app.logger` is used, unlike the basketball tick, which drives 4 routes through `test_client()`.
- **Module state:** 56 names, including thread/lock state for the background loop (`_LIVE_LENS_LOOP_THREAD/_LOCK/_STOP`, `_LIVE_LENS_PROCESS_LOCK_HANDLE`), payload/feed caches with TTLs, and data-dir constants.
- **Env read:**
  - `MLB_BETTING_DATA_ROOT`, `MLB_LIVE_LENS_DIR`, `LIVE_LENS_DIR`, `SYNDICATE_DATA_ROOT`;
  - `MLB_LIVE_LENS_LOOP_INTERVAL_SECONDS`, `MLB_LIVE_LENS_REPORT_REFRESH_INTERVAL_SECONDS`, `MLB_LIVE_ODDSAPI_REFRESH_INTERVAL_SECONDS`;
  - `MLB_LIVE_PITCHER_STRIKEOUTS_CORRECTION_PATH`, `MLB_LIVE_PROP_RANKING_CONFIG`, `WERKZEUG_RUN_MAIN`.

## Implication / proposed shape (not started)

This is a P6-class job, not a launcher swap. It is the basketball live-tick port (a generated, statement-verbatim closure port with `--check`, record/replay parity on the files it writes, and a planted control), plus a decision on the `sim_engine.*` / `tools.*` modules it reaches.

Two ways to handle those modules:
- **(a)** Port them into the closure too (`live_mc` is an engine, so expect a large closure and an engine-standard input checklist).
- **(b)** Keep them vendored for a first cut and port only the app slice, which would remove the 21k-line app load but not the vendored dependency.

A clean first step is the generator plus a `--report` (exact per-module closure sizes, including the vendored packages), then the parity harness. The MLB daily update (`tools/daily_update.py`, which owns `lineups_last_known_by_team.json`) is a separate, larger port that this closure also touches via `tools.daily_update_multi_profile`.

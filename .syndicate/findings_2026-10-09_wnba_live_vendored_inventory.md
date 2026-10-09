# WNBA live + sim path: every vendored call, and what replaces it — 2026-10-09

Lane `wnba-native-live-cutover` (P5 of `docs/ai_context/basketball_live_native_plan.md`).
Prerequisite-free half of P5: P1 / P2 / P3 had not started on 2026-10-09 (plan Status table, and no
`basketball-native-engine` / `basketball-native-live-state` / `nba-native-live-resim` lane in
`lanes.md`). Surveyed on `origin/main` at `b823d7f9` by `git grep -nE
"vendor\.|wnba_betting_repo|nba_betting_repo|vendor/|_vendor|importlib|sys\.path"` over
`syndicate/features/wnba/`, `syndicate/features/shared/{wnba*,basketball*,live_lens*,live_gameline_join,board_enrichment,live_refresh_loop}.py`,
`syndicate/blueprints/wnba.py`, and the scripts the fleet runs for WNBA. The anchor lines were
re-read by hand (`wnba/live_lens.py:65-71`, `cards.py:1097/1210`, `basketball_props_smart_sim.py:880-887/3285-3292`).

## Two blind spots in the plan's end-state grep (fix the grep before trusting it)

1. **`importlib.import_module(f"{package_name}.sim.events")` contains no `vendor.`** — the sim
   path's vendored loads (`basketball_props_smart_sim.py:885`, `:3292`, `:3991-3997`) go through
   `sys.path.insert(vendor/<pkg>_repo/src)` + a formatted module name. The grep in the plan would
   return clean while the vendored possession engine still IS the WNBA sim. Add
   `wnba_betting\.|_vendor_smart_sim_code_root_local|_import_real_` to the pattern.
2. **The grep's paths exclude `scripts/`.** The producer of WNBA `live_snapshots/live_lines_*`
   and `live_player_lens_*` loads `vendor/wnba_betting_repo/app.py` as a module from
   `scripts/refresh_wnba_oddsapi_props.py:5774-5778` (`_load_source_app`, used at :514/:537 and
   :824 via `app.test_client()`). Deleting the import in `wnba/live_lens.py` alone leaves this.

## Inventory

Path: **L** = live lens (tick / lens builder / liveProps / live game line), **S** = sim path
(pregame SmartSim whose `sim.players` the WNBA lens USES for liveProps), **O** = neither.

| # | file:line | vendored symbol | path | runtime today | replacement (phase) |
|---|---|---|---|---|---|
| 1 | `syndicate/features/wnba/live_lens.py:65,69` (`_run_wnba_live_lens_tick`, called :513) | `vendor.wnba_betting_repo.app._live_lens_tick_payload` | L | unconditional, both failures swallowed to `None`; RETURN VALUE DISCARDED — its only effect is writing `live_lens_signals_<d>.jsonl` / `live_lens_projections_<d>.jsonl` into `WNBA_LIVE_LENS_DIR` | P3's live re-sim writer under WNBA params; delete the call (P5) |
| 2 | `scripts/refresh_wnba_oddsapi_props.py:5774-5778` → :514/:537, :824 | loads `vendor/wnba_betting_repo/app.py`; `_live_oddsapi_period_totals_for_game`; `app.test_client()` for `/api/live_lines`, `/api/live_player_lens` | L | producer of `live_snapshots/live_lines_*` and `live_player_lens_*`, None-guarded | live lines from Syndicate's own OddsAPI live capture; player lens from P3 (P5) |
| 3 | `refresh_wnba_oddsapi_props.py:211, 6237-6282` | copies the vendor-written signals/projections JSONL, else builds them natively (`_build_local_live_lens_signals_artifact` :3183, `_projections_artifact` :3250) | L | a second, NATIVE producer of the same files already exists | becomes the only writer, fed by P3 (P5) |
| 4 | `cards.py:5033-5070` → `basketball_live_artifacts.py:506, :637` | reads the vendor-written signals/projections files (path via `live_lens_paths.resolve`, `WNBA_LIVE_LENS_DIR`) | L | 2nd-tier fallback of `build_live_player_lens_payload` (:6906) / `build_live_lines_payload` (:6990) when the snapshot is missing or >20 min old | same readers, P3-written files (P5) |
| 5 | `shared/live_lens_paths.py:11-15, 52-101` | mirrors vendor `_live_lens_artifacts_dir` | L | path logic only | keep; no vendored code |
| 6 | `shared/basketball_props_smart_sim.py:857-865, 883-885` (`_import_real_smart_sim_module_local`, used :894-908; callers :5272, :5788) | `sys.path.insert(vendor/wnba_betting_repo/src)`; `wnba_betting.sim.smart_sim.simulate_smart_game` | S | on success the vendored `simulate_smart_game` IS the WNBA sim (≈10 helpers monkeypatched with local ports :4700-4760); on failure the flat local stub | P1 native engine; delete with the flat fallback (P1) |
| 7 | `basketball_props_smart_sim.py:3290-3292, 3301, 3317` | `wnba_betting.sim.events.simulate_pbp_game_boxscore` / `simulate_event_level_boxscore`; monkeypatches `_sample_lineup` | S | try/except → deterministic stand-in | P1 (parity-gated), resume API for P3 |
| 8 | `basketball_props_smart_sim.py:3991-3997` → :4007, :4063 | `wnba_betting.advanced_stats_boxscores` / `.advanced_stats_player_logs` (`compute_team_advanced_stats_from_boxscores`) | S (sim input) | try/except → None (input silently absent) | port into Syndicate with P1; a model-engine-standard checklist row |
| 9 | `scripts/refresh_wnba_oddsapi_props.py:1169-1178, 1466, 3751, 3971, 3998` | subprocess `python -m wnba_betting.cli` (`predict-date`, `daily-update`, processed export) | S (pregame game predictions = the lens's ANCHORS `p_home_win` / `pred_total`) | runs on the refresh worker | out of P5's literal scope (pregame), but the live lens's anchors come from it — needs its own decision |
| 10 | `refresh_wnba_oddsapi_props.py:1305, 4525` | copies vendor `games_nba_api.csv`, `predictions_<d>.csv` | S | conditional copies | as #9 |
| 11 | `shared/live_refresh_loop.py:644-670` (via :889 `_should_force_sim_rerun`) | subprocess `wnba_betting.cli fetch-injuries`, cwd vendor | S (re-run trigger) | return code only | Syndicate injury feed (already exists for layer2) |
| 12 | `basketball_props_predictions.py:124-149, 154, 198, 430`; `basketball_props_edges.py:671` | vendor ONNX models dir; `sys.path.insert(source_root/"src")` | S-adjacent | `src/` absent in production → effectively no-op | delete with P1 |
| 13 | `refresh_wnba_oddsapi_props.py:5672-5683, 5732-5736` | vendor `tools/build_recon_players.py`, live-lens tuning tool; `wnba_betting.playoff_transition` | O | fallbacks | own decision (plan's "outside" list) |
| 14 | `live_refresh_loop.py:4204` | reads vendor `schedule_2026.json` (`_wnba_commence_times`) | O | refresh timing | own decision |
| — | `cards.py:1044-1058, 6124`; `live_lens_loop.py:58` | comments only (`:6124` documents a REMOVED call) | — | dead | none |

Clean (no vendored reference): `wnba_live_prop_projection.py`, `wnba_live_prop_probability.py`,
`wnba_live_prop_rows.py`, `live_gameline_join.py`, `board_enrichment.py`, `blueprints/wnba.py`,
`wnba/source_proxy.py` (`_vendored_web_asset` reads `syndicate/static/wnba/` — a misleading name).
`local_production.py` `SCHEDULED_JOBS` has no WNBA entry; the WNBA sim runs inside
`scripts/refresh_wnba_oddsapi_props.py`.

## What Syndicate consumes from the vendored tick (so P3's writer must produce exactly this)

- **signals** → `basketball_live_artifacts._build_signal_live_lines_payload` (:283-384): `market`,
  `live_line`/`line`, `side`/`selection`, `horizon`/`period` → `build_live_lines_payload` →
  `live_lens.live_line_by_event_id` → rank-card `live_line`.
- **projections** (`market == "player_prop"`) → `build_live_player_lens_payload_from_artifacts`:
  `proj`/`pace_proj`, `line`, `sim_mu`, `sim_mu_adjusted`, `win_prob`, `price_over`/`price_under`,
  `klass`, `side`, `edge`/`ev` → `build_wnba_market_board` (cards.py:3675), `home.py:6319/6385`,
  `wnba/props.py:184`, `blueprints/wnba.py:761`.
- **NOT consumed:** the vendor's game total / ATS / ML projections — the native gameLens recomputes
  them with the linear lens below.

## The linear lens being retired (exact, `syndicate/features/wnba/cards.py`)

- elapsed (`_wnba_elapsed_minutes` :1005): 10-min quarters, 5-min OT.
- **ML** (`_wnba_live_margin_win_prob` :1038): `p = (1-w)·p_pre + w·logistic(margin/2.1)`,
  `w = clamp(elapsed/40)`, `p_pre = betting.p_home_win`; None when `p_pre` is None.
  `_WNBA_LIVE_MARGIN_SCALE = 2.1` (:1097, refit by `#481` from 6+0.35·min_left).
- **Cover** (:1100): `logistic((margin + home_spread)/2.1)` blended toward `betting.p_home_cover`.
- **Total** (`_wnba_live_total_projection` :1155): `cur + rate·(40-e)`,
  `rate = (1-w)·pre/40 + w·cur/e`, `pre = betting.pred_total` else `betting.total`.
- **Over** (:1213): `logistic((proj-line)/3.2)` blended toward `betting.p_total_over`
  (`_WNBA_LIVE_TOTAL_SCALE = 3.2`, :1210).
- **Props** (`_estimated_live_projection` :5509 + `_garbage_time_minutes_factor` :5490): sim
  minutes target × garbage factor (Q4, |diff| ≥ 20: ×0.85 if sim min ≥ 28, ×1.15 if ≤ 15),
  blended `(1-bw)·sim_mean + bw·actual/played·target`, `bw = clamp(played/target, .25, .85)`.
  Uses `sim.players` — so the WNBA lens is reached by the sim path, unlike NBA's.

## The verification corpus

`scripts/build_wnba_live_checkpoint_corpus.py` -- one row per (game, checkpoint: end Q1 / Q2 / Q3,
5:00 Q4). **v2, 2026-10-09 ~21Z, supersedes v1 (~17Z):**

- **State = P2's `LiveGameState`** (`shared/basketball_live_state.py`, lane `basketball-native-live-state`),
  built on an AS-OF summary per checkpoint -- the same parser production's live tick uses, so P3/P5
  resume from what the backtest grades. v1's own tracker was deleted. Cross-check before deleting it,
  all 1,376 v1 cells: score, team fouls, both fives, per-player PF/PTS/REB/AST/3PM identical on every
  cell; differences only where expected (clock: P2 = the last play's, 5:00-5:25 at "5:00 Q4"; possession
  at 5:00 Q4 on 42 cells, where v1 LOOKED AHEAD and P2 reads past plays only).
- **As-of score = the sum of scoring plays to the cut, not the plays' running `homeScore`.** The
  running field lags the play sum on **36 of 347** games (1 to 132 consecutive plays) while the play
  sum reaches the official final on every kept game; 9 of 1,384 checkpoint cells sit inside such a lag.
  v1 and its tracker BOTH read the running field, so their agreement proved nothing on this point.
- **Anchors = what production's lens actually reads.** `betting.p_home_win` / `p_home_cover` /
  `p_total_over` / `pred_total` come from the per-game `smart_sim_<d>_<H>_<A>.json` via
  `refresh_wnba_oddsapi_props.py::_smart_sim_projection_index` (called, not re-implemented). **v1 used
  `predictions_<d>.csv`, a different estimate** (DAL v TOR 2026-08-12: p_home_win 0.657 vs 0.74;
  total 165.8 vs 180.0). Source: the `wnba-lines-props-backtest` as-of re-run, fleet
  `~/wnba_bt/archive/<d>/smart_sim_*.json` (340 games).
- ESPN pbp `sequenceNumber` is NOT chronological; the list order is (sorting on it broke 27 of 218).

| | v2 |
|---|---|
| games seen / kept | 347 / **346** (1 excluded: no plays). The 2 v1 `score` exclusions were the running-field lag above |
| by phase | **regular 332**, **playoffs 14** |
| rows | 1,384 = 346 x 4 |
| props-unreconciled games (kept for lines, `props_reconciled:false`) | 14 |
| anchors joined | **340 / 340** available (regular 331, playoffs 9), 0 unjoined |
| P2 stint minutes within 1 min of box | 99.97% of 6,901 |
| cells where P2's lineup fallback read the FINAL box minutes | 0 |
| dates | 2026-05-08 .. 2026-10-07 |

Persisted: fleet WSL `~/wnba_bt/live_checkpoints/` -- `wnba_live_checkpoints_2026.jsonl.gz` (sha256
`a648cb1a…f7302`), `.summary.json`, `linear_lens_baseline_2026.json`, `espn_cache_wnba_2026.tgz`
(rebuild with `--offline --sim-anchors <dir of the archive's smart_sim files>`). v1 kept beside it as
`v1_predcsv_anchors_*` -- do not use it.

### The bar: the CURRENT linear lens on v2 (anchored; `scripts/score_wnba_live_checkpoint_baseline.py --anchored`)

Total MAE vs the FINAL (incl. OT). Brier: ML vs the home win; cover vs margin + the sim's market
spread; over vs total > the sim's market total (pushes excluded). 95% bootstrap CI over games.
ESPN's live WP is a third-party ML reference.

| phase / checkpoint | n | total MAE [CI] | pregame-anchor MAE | ML Brier | ESPN | ML − ESPN [CI] | cover Brier [CI] | over Brier [CI] |
|---|---|---|---|---|---|---|---|---|
| regular / end Q1 | 331 | 12.46 [11.39, 13.51] | 14.94 | 0.1860 | 0.1861 | −0.0000 [−0.011, +0.010] | 0.2364 [0.225, 0.248] | 0.2209 [0.210, 0.232] |
| regular / end Q2 | 331 | 11.00 [10.04, 11.92] | 14.94 | 0.1538 | 0.1431 | **+0.0107 [+0.004, +0.017]** | 0.2045 [0.185, 0.224] | 0.1773 [0.159, 0.196] |
| regular / end Q3 | 331 | 7.96 [7.28, 8.79] | 14.94 | 0.1325 | 0.1238 | **+0.0087 [+0.003, +0.015]** | 0.1457 [0.121, 0.170] | 0.1138 [0.095, 0.135] |
| regular / 5:00 Q4 | 331 | 5.99 [5.34, 6.75] | 14.94 | 0.0997 | 0.0986 | +0.0011 [−0.003, +0.005] | 0.1088 [0.088, 0.133] | 0.0870 [0.069, 0.107] |
| playoffs / end Q1 | 9 | 14.96 | 12.70 | 0.2224 | 0.1952 | +0.027 [−0.033, +0.073] | 0.2666 | 0.2303 |
| playoffs / end Q2 | 9 | 13.96 | 12.70 | 0.1587 | 0.1273 | +0.031 [+0.004, +0.060] | 0.1486 | 0.2575 |
| playoffs / end Q3 | 9 | 7.69 | 12.70 | 0.0708 | 0.0656 | +0.005 [−0.011, +0.022] | 0.0529 | 0.2089 |
| playoffs / 5:00 Q4 | 9 | 4.28 | 12.70 | 0.0228 | 0.0249 | −0.002 [−0.013, +0.004] | 0.0151 | 0.0785 |

Readings: the linear ML is **level with ESPN's live WP at end Q1** and **worse at end Q2 and end Q3**
(CIs exclude 0), level again by 5:00 Q4. **CORRECTION:** v1 reported "worse at end Q1/Q2/Q3
(+0.019/+0.020/+0.012)"; the Q1 deficit was the WRONG ANCHOR, not the lens. Cover/over Brier are near
0.25 early (cover 0.236 at end Q1): little beyond a coin there. Playoffs: 9 anchored games -- report,
do not conclude.

Not in the corpus: the live CLOSE (no WNBA live line was ever captured --
`[wnba-live-edge-is-leakage]`), so grading is vs the final only; and the 6 kept games without an
as-of sim (no anchor, so the lens has no pregame `p_*`).

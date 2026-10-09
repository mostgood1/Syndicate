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

## The verification corpus (built this session)

`scripts/build_wnba_live_checkpoint_corpus.py` — one row per (game, checkpoint ∈ end Q1/Q2/Q3,
5:00 Q4) from ESPN pbp, state reconstructed from plays only (score, box-so-far, team fouls in
period, player PF/PTS/REB/AST/3PM, on-floor fives, next possession), the as-of pregame anchors,
ESPN's own live WP, the outcome, and the **linear lens's own prediction computed by the shipped
functions** (imported, not re-implemented). Regular season and playoffs are separate `phase`s.

**Built 2026-10-09** (offline from the ESPN cache, `--start 2026-05-01 --end 2026-10-31`):

| | value |
|---|---|
| games seen / kept | 347 / **344** (excluded: 2 `score` — the feed's last play is 2 pts short of the header, a feed defect; 1 `no_plays`) |
| by phase | **regular 330** (the full 15-team x 44 schedule), **playoffs 14** |
| rows | 1,376 = 344 x 4 checkpoints; every cell 330 / 14 |
| props-unreconciled games (kept for game lines, flagged `props_reconciled:false`) | 14 (a 1-2 count stat correction on one player) |
| as-of anchors joined | 338 games (regular 329, playoffs 9); 116 `predictions_<d>.csv` files, 05-08..10-01 |
| stint-reconstructed minutes within 1 min of the box | 6,901 / 6,901 (diffs span -0.50..+0.48 = the box's integer rounding; 0 players with zero pbp minutes) |
| dates | 2026-05-08 .. 2026-10-07 |

**Trap found and fixed while building:** ESPN's `sequenceNumber` is NOT chronological. Sorting on it
put the last play mid-game on 27 of 218 games and dropped the minutes match to 0.82; the feed's LIST
order is chronological (score reconciliation 205/218 -> 344/347 on the full set).

Persisted (scratch is per-session): fleet WSL `~/wnba_bt/live_checkpoints/` —
`wnba_live_checkpoints_2026.jsonl.gz` (sha256 `d1bf5580…5fbe26`), `.summary.json`, and
`espn_cache_wnba_2026.tgz` (rebuild with `--offline`). Anchors: `~/wnba_bt/archive/<d>/predictions_<d>.csv`.

### The bar: the CURRENT linear lens on this corpus (anchored games; `scripts/score_wnba_live_checkpoint_baseline.py --anchored`)

Total MAE vs the FINAL (incl. OT). ML Brier vs the home win. 95% bootstrap CI over games. ESPN's own
live WP at the same play is a third-party reference.

| phase / checkpoint | n | linear total MAE [CI] | pregame-anchor MAE | linear ML Brier [CI] | ESPN Brier | linear − ESPN dBrier [CI] |
|---|---|---|---|---|---|---|
| regular / end Q1 | 329 | 13.14 [12.05, 14.18] | 17.02 | 0.2057 [0.192, 0.220] | 0.1864 | **+0.0193 [+0.004, +0.034]** |
| regular / end Q2 | 329 | 11.31 [10.36, 12.25] | 17.02 | 0.1640 [0.146, 0.184] | 0.1437 | **+0.0202 [+0.011, +0.029]** |
| regular / end Q3 | 329 | 8.01 [7.30, 8.77] | 17.02 | 0.1359 [0.112, 0.162] | 0.1241 | **+0.0119 [+0.005, +0.019]** |
| regular / 5:00 Q4 | 329 | 6.20 [5.55, 6.93] | 17.02 | 0.1013 [0.079, 0.126] | 0.0992 | +0.0020 [−0.003, +0.007] |
| playoffs / end Q1 | 9 | 14.47 [8.36, 21.02] | 14.26 | 0.2407 | 0.1952 | +0.0455 [+0.017, +0.070] |
| playoffs / end Q2 | 9 | 13.16 | 14.26 | 0.1653 | 0.1273 | +0.0381 [+0.009, +0.077] |
| playoffs / end Q3 | 9 | 7.49 | 14.26 | 0.0708 | 0.0656 | +0.0052 [−0.012, +0.021] |
| playoffs / 5:00 Q4 | 9 | 4.30 | 14.26 | 0.0229 | 0.0249 | −0.0020 [−0.013, +0.004] |

Readings: the linear lens's ML is **measurably worse than ESPN's live WP at end Q1/Q2/Q3** (CI
excludes 0) and level by 5:00 Q4 — so a better live ML is demonstrably available from game state
alone. Playoffs n=9 anchored games: report, do not conclude. The pregame anchor MAE (17.0) is the
as-of SIM `pred_total`, not the market close.

**OWED for the P5 comparison (not in this corpus):** the pregame `p_home_cover` / `p_total_over`
anchors (production derives them from sim SAMPLES, `basketball_props_smart_sim.py:1406/1410`, not
from `predictions_<d>.csv`), so cover / over Brier cannot be scored for either side yet; and the
live CLOSE (no WNBA live line was ever captured — `[wnba-live-edge-is-leakage]`), so grading is vs
the final only.

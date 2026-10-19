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

## As-of engine inputs for the native re-sim (2026-10-12, user decision: record now, backtest after P3's re-fits)

`scripts/record_wnba_engine_inputs_asof.py` (main `0f222403`) re-ran today's production pregame path as of each
2026 date on a scratch root and persisted the first engine call per game through
`live_resim.persist_engine_inputs(..., league="wnba")` (P3 made `live_resim` league-parametric at this lane's
request). Ran on the fleet 2026-10-12 14:23-14:52Z, nice 19, 2 workers, frozen code `d74f1387` + the recorder
(`~/wnba_live_bt/CODE_USED.txt`).

| | |
|---|---|
| dates / games recorded | 116 / **340**, 0 failures, 0 zero-game dates |
| join to the corpus | 340 recorded == 340 anchored corpus games (0 either way); regular 331, playoffs 9 |
| production switches present | all four on every date (availability, rate shrink, prop dispersion, prop shape) |
| sides with an EMPTY lineup pool | 56 / 680 (8.2%): May 20/126, Jun 11/164, Jul 6/142, Aug 15/170, Sep 3/76 |
| output | fleet `~/wnba_live_bt/engine_inputs_asof/data/processed/engine_inputs/<date>/<HOME>_<AWAY>.pkl` |

Two production-equivalence gaps in the scratch recipe, found by the smoke and fixed before the run:
production's WNBA file switches were absent from the pristine copy (the engine would have run with availability
and rate shrink OFF), and `rotation_stints_history` was deleted (0 lineup pools on 3/3 smoke games) -> copied
truncated to date < D, player-checks files < D only. P3's NBA recorder had the same stints gap (fixed f7195eae).
The empty pools that remain are production's own behaviour (e.g. `rotation_minutes_conflict_with_current_signals`
for DAL and GSV on 2026-08-12), not a recorder defect. **Not reproducible as-of, stated:** the season-fit
lineup-effect tables (`lineup_effects` reason `missing_tables`); `pair_minutes_history` / `play_context_history`
feed only those tables, not the sim path. The inputs are TODAY's code as-of, not what production ran per date.

## Inventory re-check, 2026-10-12 21:4xZ (origin/main, after P1 + P6 shipped)

Method: an AST scan (imports, `importlib`/`sys.path`/`spec_from_file_location` calls, vendor path literals) over
`syndicate/features/{wnba,basketball_engine}` and `shared/{basketball*,wnba*,live_lens_loop,live_gameline_join}.py`
(73 files) -- not a name grep, so provenance docstrings in the native ports are not counted -- plus a read of the
`scripts/refresh_wnba_oddsapi_props.py` call sites, plus the fallback flag on every running fleet process
(presence/truthiness only, never the value).

| row | was | now |
|---|---|---|
| 1 `wnba/live_lens.py:65` vendored tick | runs unconditionally | **UNCHANGED -- the one vendored call that still runs on the WNBA live path.** P5 deletes it |
| 2 `_load_source_app` in `refresh_wnba_oddsapi_props.py` | live snapshot producer | live OddsAPI period lines now NATIVE (`wnba/live_period_lines.py`, lane `wnba-live-period-lines-native`); the 4 remaining call sites (live snapshot export :832, cards_sim_detail :6047, recon :6170, live-lens artifact export :6280) are present but every vendored fetch is gated by `SYNDICATE_WNBA_SOURCE_APP_FALLBACK`, which is **off on all 23 fleet python processes** (web, refresh-worker, live-odds-worker: set non-truthy; others absent). Dead at runtime; delete with P5 |
| 6-8 vendored `simulate_smart_game` / `sim.events` / advanced-stats imports | the WNBA sim | **GONE** -- P1 engine + P6 native orchestrator; the scan finds no vendored import on the sim path |
| 12 `sys.path.insert(source_root/src)` in props predictions/edges | no-op in prod | unchanged: `basketball_props_predictions.py:158/202/434`, `basketball_props_edges.py:672`. No-op in production (data root has no `src/`); in an as-of SCRATCH the pristine `src/` IS on the path -- harmless while nothing imports from it (P6: "the bridge loads no vendored module") |
| new: `shared/wnba_fixture_identity.py:73` | -- | reads `vendor/wnba_betting_repo/data/processed/schedule_2026.csv` (DATA, fixture identity / board) -- off the live and sim path; belongs to the plan's "outside" list |

## Native re-sim harness + smoke, and the on-floor match gap (2026-10-14 13:0xZ)

`scripts/backtest_wnba_live_resim.py` runs production's per-game `live_resim` sequence (league="wnba") at every
corpus row: resume from the corpus's own as-of summary -> recorded inputs -> `map_state_names` -> mechanisms from
the COMMAND LINE -> `resim_live_game` (stable seed). `score_wnba_live_checkpoint_baseline.py --native` pairs it with
the linear lens on the same rows (refusals counted). **SMOKE ONLY (user decision: the scoring run waits for P3's
re-fits):** 2 games x 4 checkpoints, 100 sims, engine defaults, PYTHONHASHSEED=0 -> 8/8 resimmed, 0 refusals,
3.5-10.6 s per 100 sims. Not a result.

**On-floor match gap (all 340 games, 5:00 Q4, read 2026-10-14):** 3,139 of 3,400 on-floor players (92.3%) map
onto the engine frame; **261 (7.7%) are ABSENT from the frame entirely** (name normalization is not the cause --
the 15 "variants" are first-name coincidences, e.g. Nia Brodie / Nia Coffey). `map_state_names` drops a side's whole
five on ANY miss, so **203 of 680 sides (30%) resume with a sampled lineup**, not the real one. Examples on
2026-05-08: Julie Vanloo, Betnijah Laney-Hamilton, Marina Mabrey, Shakira Austin, Gabby Williams (frames of 10-11
players). End-of-period checkpoints have no on-floor five by design (40/40 sampled: next period starts at a tip).
**Hypothesis, UNVERIFIED:** the pregame pool (as-of availability rule + pool cap) omits players with no recent
appearance for that team (opening day, trades, signings) -- production's own behaviour, so a live WNBA re-sim in
production would hit the same gap, and those players can get no live prop at all. Next: the rate by month and by
reason (availability exclusion vs pool cap vs not on the roster file), before deciding whether P5 needs a live
pool top-up from the box.

### On-floor gap by month: WNBA's pregame frame looks CAPPED at ~10, not only recency-limited (2026-10-14 13:2xZ)

5:00 Q4, all 340 recorded games (680 sides): real five resumed / player match / median frame size --
May 0.57 / 0.887 / 10; Jun 0.79 / 0.948 / 10; Jul 0.69 / 0.934 / 10; Aug 0.72 / 0.925 / 10; Sep 0.70 / 0.905 / 10
(Oct 2 sides). Regular 463/662, playoffs 14/18. The 261 absent players are NOT fringe: median 19 final minutes, 125
of them >= 20 min.

**This partly OVERTURNS my 13:0xZ hypothesis** ("players with no recent team games are excluded"): the May dip fits
recency, but after May the real-five rate is FLAT ~0.7 while the median frame never leaves 10 players. P3's NBA
reading (findings_2026-10-09 §11) ramps 0.45 -> 0.92 as frames grow 12.5 -> 17. For WNBA the leading candidate is
a frame-size cap of ~10 (below a real 11-12-player rotation), with recency on top in May. UNVERIFIED which code
sets it -- for the smart-sim roster/frame owner (P3 filed the lead).

### CORRECTION (2026-10-14 17:3xZ): the WNBA on-floor gap is the K=1 RECENCY rule, not the frame cap

Code (read, file:line): WNBA alone runs `_prune_pregame_rotation_pool` (`orchestrator/runtime.py:114`
`prune_pregame_pool=True`, NBA `:96` False; called `orchestrator/smart_sim.py:1481`) with `max_keep = 11` for WNBA
(`basketball_props_smart_sim.py:1693`); before it, `_drop_excluded` removes the WNBA recency exclusions
(`wnba_sim_availability.recency_exclusions`, K=1 = absent from the team's previous game; ON via file switch since
2026-10-05); and the pool is topped up from the roster ONLY when the props pool has < 8 players (`smart_sim.py:1358`).

Measured -- each of the 261 absent on-court players (5:00 Q4, 340 games) classified against the team's previous
game in the corpus: **217 (83%) sat out the team's previous game** (the recency rule's trigger), 19 had no prior
team game (opener), **12 (5%) played it with the frame at the 11 cap**, 13 played it with a frame < 11. The side's
frame held 8-10 players for 197 of the 261 -- **the cap rarely binds; frames sit near 10 because the recency rule
thins the props pool first.** Every month is recency-dominated (May 34 / Jun 41 / Jul 46 / Aug 60 / Sep 36).
**My 13:2xZ "frame capped at ~10" reading was wrong** (corrected to P3 the same hour). Caveat: "sat out the previous
game" is the rule's TRIGGER; that the rule (not some other filter) removed each player is not verified per player
(it has `playing_today` / injury re-inclusions).

Implication beyond P5: the availability rule (enabled 2026-10-05 by user decision on its pregame minutes gain) also
gives ZERO pregame minutes to players who then play ~19 median minutes after sitting one game -- 217 such on-court
instances at 5:00 Q4 alone. That is a pregame trade-off for the rule's owner, not something P5 changes.

## P5 BACKTEST RESULT (2026-10-16 17:2xZ): the native re-sim PASSES the pre-registered test

Run: `scripts/backtest_wnba_live_resim.py`, frozen `1c353e05` (WNBA resume parity vs origin/main `87e62aeb` 8/8
identical), production engine (nothing enabled after the 10-15 VALID read), mechanisms {}, 200 sims, PYTHONHASHSEED=0,
k inputs, all 1,360 anchored checkpoint rows, **0 refusals**. Scored by `score_wnba_live_checkpoint_baseline` pairing
(`p5_score.py`; fleet `~/wnba_live_bt/p5_run/p5_scores.json`). Native minus linear lens, negative = native better,
95% bootstrap CI over games:

| regular season (n=331 each) | total MAE | ML Brier | cover Brier | over Brier |
|---|---|---|---|---|
| end Q1 | +0.265 [-0.415, +0.963] | -0.0051 [-0.013, +0.003] | -0.0017 [-0.016, +0.013] | -0.0118 [-0.024, +0.000] |
| end Q2 | -0.256 [-0.839, +0.347] | **-0.0115 [-0.017, -0.005]** | -0.0096 [-0.022, +0.004] | -0.0034 [-0.013, +0.005] |
| end Q3 | -0.389 [-0.788, +0.001] | **-0.0085 [-0.014, -0.003]** | +0.0003 [-0.009, +0.009] | **-0.0058 [-0.011, -0.001]** |
| 5:00 Q4 | +0.048 [-0.166, +0.275] | -0.0035 [-0.008, +0.001] | -0.0020 [-0.009, +0.005] | +0.0001 [-0.003, +0.004] |

Playoffs (n=9 per cell): nothing significant either way. **Pre-registered falsification (lane block): native must beat
the linear lens with a CI excluding 0 at >= 1 checkpoint and lose at none -> MET** (ML end Q2 and Q3, over end Q3; no
cell worse). Caveat: 3 significant of 16 regular-season cell x market tests, all one direction -- consistent, small.
The ML gain lands where the linear lens trailed ESPN's live WP (+0.011 / +0.009 at end Q2 / Q3) and closes most of
it; like P3 on NBA, the gain is on margin/ML, not totals.

5:00 Q4 split by real five (k): both_real n=165 vs any_sampled n=166 -- no difference measurable on any market.

**This is the backtest gate only.** P5's goal still needs: the cut-over code (native re-sim replaces the vendored
tick at `wnba/live_lens.py:65` and the linear `_wnba_live_*` lens, plus the gated-off vendored-app fallbacks in
`refresh_wnba_oddsapi_props.py`), the widened end-state grep, and the live reading at the 2027 opener (`#694`).

## CUT-OVER BUILT (2026-10-16 17:5xZ; user decision "game lens only, coordinate"), flag OFF

- `syndicate/features/shared/basketball_props_smart_sim.py`: the pregame engine-input persist hook now also writes
  WNBA (`persist_engine_inputs(league="wnba")`, log `WNBA_ENGINE_INPUTS_PERSISTED`); NBA's key, path and log line are
  unchanged (P3's 38 tests pass). Write-only: same seed, same output (test).
- NEW `syndicate/features/wnba/live_resim.py`: WNBA team names registered for the board join; `SYNDICATE_WNBA_LIVE_RESIM`
  (absent = OFF) gates a dedicated tick thread (P3's `build_live_lens_snapshot(league="wnba")` -> `live/wnba_live_resim.json`)
  and the lens lookup. A snapshot older than 600 s, with a missing/unparseable `generatedAt`, for another game, or a
  REFUSED lane never reaches the lens. `p_win_given_no_push` (pushes excluded) is now shared with the backtest harness.
- `syndicate/features/wnba/cards.py::_build_wnba_game_lens`: for a live game with a native lane, the win probability,
  projected total, cover and over come from the re-sim; otherwise the linear lens exactly as before. The source stamp
  stays `live_projection` (what `live_gameline_join` accepts for wnba); NEW `projectionModel` = `native_resim` /
  `linear` and `simsRun` say which model produced the numbers.
- `syndicate/features/shared/live_lens_loop.py`: starts the WNBA thread beside NBA's and NCAAB's, only when switched on.
- Tests: `tests/test_wnba_live_resim.py` 12 (off -> linear, on -> native, stale/undated/refused/other-game fall back,
  pushes excluded, tick path, persist hook); 75 targeted existing tests pass.

NOT done by this lane, by decision: the vendored tick in `wnba/live_lens.py` (lane `nba-live-tick-native`'s port);
live props from the re-sim (no WNBA live prop line was ever captured to grade one). Inert until the switch is set:
no WNBA games until May 2027, and the switch is a user decision (todo #694 step 4).

## END-STATE CHECK (2026-10-19)

Scheduled task `wnba-p5-end-state-check`, todo #694 step 3, run 2026-10-19T16:08Z against origin/main `311d64b7`.
**Verdict: PASS** -- no runtime vendored import or load on the WNBA live or sim path.

The precondition held: `syndicate/features/wnba/live_lens.py::_run_wnba_live_lens_tick` now imports
`syndicate.features.wnba.live_tick.tick._live_lens_tick_payload` (commit 74a16106, lane `nba-live-tick-native`);
`vendor.wnba_betting_repo` appears in it only in the docstring.

**Method (widened, per "Two blind spots").** (a) An AST scan, not a name grep, of `syndicate/features/wnba/`,
`syndicate/features/basketball_engine/`, `syndicate/features/shared/{basketball*,wnba*,live_lens_loop,live_gameline_join}.py`
(110 files) for: imports of modules starting `vendor` / `wnba_betting` / `nba_betting`; calls to `importlib.import_module`,
`spec_from_file_location`, `sys.path.insert/append`, `__import__`; non-docstring string constants containing `vendor/`,
`vendor\` or `_betting_repo`. Plus a text grep for `"vendor"` path parts and `betting_repo` (catches
`os.path.join("vendor", ...)`, which the string rule cannot).
**Positive controls:** a planted file with all five forms -> 5 hits; `vendor/wnba_betting_repo/app.py` -> 46 hits.
The app.py control first returned PARSE_ERROR: **a UTF-8 BOM makes `ast.parse` fail, so a scanner that reads with
`utf-8` is blind to BOM files** -- `wnba/recon_tools/build_live_player_lens_tuning.py` was one. Re-run with `utf-8-sig`;
every number here is from that run. (b) `scripts/refresh_wnba_oddsapi_props.py` scanned the same way.

| hit | kind | what it loads | path | runtime vendored? |
|---|---|---|---|---|
| `shared/basketball_boxscores_history.py:54,184,301` | `importlib.import_module` | `syndicate.features.shared.basketball_props_smart_sim` | sim inputs (box-score history) | no |
| `shared/basketball_boxscores_history.py:376` | `__import__` | `os` | sim inputs | no |
| `shared/basketball_props_predictions.py:158,202,434` | `sys.path.insert(<source_root>/src)` | nothing: no `wnba_betting`/`nba_betting` import follows anywhere in scope | pregame props (outside live; sim-adjacent) | no -- inert residue, named |
| `shared/basketball_props_predictions.py:272` | `__import__` | `json` | pregame props | no |
| `shared/basketball_props_edges.py:672` | `sys.path.insert(<source_root>/src)` | nothing (as above) | pregame props edges (outside) | no -- inert residue, named |
| `scripts/refresh_wnba_oddsapi_props.py:26` | `sys.path.insert` | REPO_ROOT | refresh (outside) | no |
| `scripts/refresh_wnba_oddsapi_props.py:5490` | `spec_from_file_location` | `syndicate/features/wnba/recon_tools/*.py` (Syndicate copies) | refresh (outside) | no |
| `scripts/refresh_wnba_oddsapi_props.py:6479` | string | the refusal message for a `vendor/` `--source-root` | refresh (outside) | no |
| `shared/wnba_card_provenance.py:43` | `VENDOR = "vendor"` | a provenance label | board | no |

Every other match is a provenance docstring/comment (`Source: vendor/... (sha256 ...)` headers in `wnba/live_tick/`,
`wnba/source_cli/`, `basketball_engine/orchestrator/`). **`wnba/live_tick/` (the ported tick) has zero hits.**

**(b) `_load_source_app`: no call sites remain.** Neither `_load_source_app` nor `_source_app_fallback_enabled` exists
in the script; deleted in b61c7b52 ("delete the vendored source-app fallback"). There is therefore no gated-off
fallback to list. The script's `predict-date` runs `python -m syndicate.features.wnba.source_cli.cli`, and the games
history seed is `syndicate/features/wnba/seed_data/games_nba_api.csv` -- both in-repo.

**Named, not blocking:** the four `sys.path.insert(<source_root>/src)` lines are dead residue of the vendored props
CLI (they add a path nothing imports from). Removing them is a cleanup for the props lane, not P5.

Not covered: `vendor/` data files read by a runtime path via a computed path (only literal path strings are caught);
NBA's own live/sim path (out of scope for P5).

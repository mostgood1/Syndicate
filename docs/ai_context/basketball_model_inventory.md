# Basketball model inventory — what exists and where

> 2026-08-18, lane `basketball-model-owner`. Basketball's counterpart to the
> MLB/soccer/football "what exists and where" documents. Catalog only — for
> input-population findings and the pipeline trace, see
> `docs/ai_context/basketball_sim_engine_reference.md`.

---

## 1. Sim engine

**Two vendored copies of one possession-level Monte Carlo engine, one per
league, driven through a single shared Syndicate bridge:**

| | |
|---|---|
| WNBA engine | `vendor/wnba_betting_repo/src/wnba_betting/sim/smart_sim.py` (4,930 lines) |
| NBA engine | `vendor/nba_betting_repo/src/nba_betting/sim/smart_sim.py` (structurally identical, separate package) |
| supporting | `events.py` (possession engine), `quarters.py` (quarter-target sim), `connected_game.py` (rotation/minutes modelling, largest single file in either package) — same three names in both vendored trees |
| entry point | `simulate_smart_game()` |
| granularity | possession -> quarter -> game, with Dirichlet-weighted rotation/minutes modelling |
| config | `SmartSimConfig(n_sims=2000 default, use_pbp=True, priors_days_back=21, roster_mode)` — production runs `n_sims=100` (`REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS`, `render.yaml:1017-1018`; confirmed on real production artifacts 2026-08-15, see reference doc Sec0b/Sec7) |

**NCAAB has no sim engine.** Confirmed by grep across
`syndicate/features/ncaab/` for `simulate_smart_game|smart_sim|sim_engine|monte
carlo` — zero matches. NCAAB instead consumes a pre-computed recommendations
payload from an **external mirror**: `syndicate/features/ncaab/sources.py:151-158`
(`recommendations_payload`/`mirrored_recommendations_payload`) reads
`_load_mirror_json("recommendations", f"recommendations_{selected_date}.json")`
from `preferred_artifact_roots(__file__, env_var="SYNDICATE_NCAAB_SOURCE_ROOT",
local_dir_name="ncaab_source")` — i.e. a directory/env var pointing at
someone else's already-computed output, not a model this repo runs. There is
no `vendor/ncaab_betting_repo` or equivalent in this checkout. This is a
**design gap, not an input-population gap** — nothing to backfill inside this
lane, matching the lane brief's explicit instruction. Already tracked at
`todo.md` line ~323-325 (inside `#440`): *"7 of 8 sports have a real Monte
Carlo pregame engine. NCAAB has none."*

---

## 2. Bridge / shared layer (`syndicate/features/shared/`)

| module | role |
|---|---|
| `basketball_props_smart_sim.py` (5,222 lines) | THE bridge. Imports the real vendor module when possible (`_import_real_smart_sim_module_local`), falls back to a flat stub (`_simulate_smart_game_local`) on any import exception, and — whichever module it gets — monkeypatches ~20 of that module's own named data-loading helpers for Syndicate-local ports (`_call_source_simulate_smart_game_local`, `:3842-3995`). See reference doc Sec0 for why this makes "did the vendor import succeed" a necessary-but-not-sufficient reachability question. |
| `basketball_props_onnx.py` (572 lines) | A THIRD parallel implementation of player-priors computation (`compute_player_priors_local`), independently verified (this lane, via AST) to produce the same 13 `_pm` rate keys the vendor's own `player_priors.py` does. Also carries ONNX-model prediction fallbacks (`_predict_props_without_models_local`, name suggests trained-model scoring, not audited in this pass beyond the priors function). |
| `basketball_props_edges.py` (637 lines) | Not read in depth this pass — edge/recommendation computation downstream of sim output. In lane's read-only scope; no findings recorded. |
| `basketball_props_predictions.py` (495 lines) | Orchestrates the props-refresh call into the smart-sim bridge (`export_props_predictions_with_smart_sim_local`, line 445-449) — the `smart_sim_n_sims` parameter threading point. |
| `basketball_props_calibration.py` (320 lines) | Not read in depth this pass. Name suggests a calibration layer distinct from the four per-game JSON artifacts in reference doc Sec5 — worth reconciling in a future pass (does this module produce/consume those files, or is it unrelated?). Open question, not answered here. |
| `basketball_market_board.py` (718 lines) | Cross-sport market-board rendering. Relevant to, but not the subject of, the WNBA/MLB `run_margin_dist`/`total_runs_dist` key-collision noted in `.syndicate/learnings.md` (2026-08-16 entry) — that defect is in a CONSUMER of this engine's output artifact, downstream of everything the input checklist audits. Cross-checked per the lane brief; does not affect this lane's checklist scope (see reference doc Sec6.6). |
| `basketball_live_artifacts.py` (708 lines) | Not read in depth this pass. No `n_sims`/`draws` reference found (grepped) — appears to be artifact I/O plumbing rather than a second sim call site. |
| `basketball_boxscores_history.py` (293 lines) | Not read in depth this pass. Likely the writer/normalizer for `boxscores_history.csv`, the file both leagues' `PlayerPriors` computation actually depends on (neither mirror has a `player_logs.csv`; both fall back to this file — reference doc Sec3). |

---

## 3. Per-sport feature module maturity

### NBA (`syndicate/features/nba/`)
Files: `archive.py`, `betting_card.py`, `betting_recap.py`, `cards.py`
(145,836 bytes), `features.py`, `game_detail.py`, `intelligence_analysis.py`,
`live_game_accuracy.py`, `live_lens.py`, `live_lens_daily_accuracy.py`,
`live_prop_accuracy.py`, `live_prop_audit.py`, `market_accuracy.py`,
`picks.py`, `props.py`, `sources.py`.

- Reads sim output via `cards_sim_detail_<date>.json`
  (`nba/cards.py:539,2625`), not the bridge directly.
- Has NO raw `smart_sim_<date>_*.json` glob fallback (grepped — zero matches),
  unlike WNBA (below).
- Has dedicated `betting_card.py`/`betting_recap.py`/`features.py` routes WNBA
  does not.
- Explicit in-code self-description as the newer/thinner pass:
  `nba/cards.py:2543` — *"This first NBA Syndicate pass maps committed
  processed game-card, slate, and SmartSim artifacts into the shared board
  shell instead of leaving NBA behind the generic placeholder route."* No
  equivalent language in WNBA's `cards.py`.
- Route count (raw `@bp.get/post/route` in `blueprints/nba.py`): **57**
  — not fewer than WNBA's 51 despite the "first pass" framing; the
  difference is architectural split (see below), not endpoint count.

### WNBA (`syndicate/features/wnba/`)
Files: `archive.py`, `cards.py` (331,938 bytes — **over 2x NBA's**),
`game_detail.py`, `intelligence_analysis.py`, `live_game_accuracy.py`,
`live_lens.py`, `live_lens_daily_accuracy.py`, `live_prop_accuracy.py`,
`live_prop_audit.py`, `market_accuracy.py`, `picks.py`, `props.py`,
`source_proxy.py`, `sources.py`. No `betting_card.py`/`betting_recap.py`/
`features.py` — that logic lives inside `picks.py`/`cards.py` instead.

- Reads sim output via `cards_sim_detail_<date>.json`
  (`wnba/cards.py:1305,1315,1337`) **plus** an additional raw
  `smart_sim_<date>_*.json` glob-and-merge fallback NBA lacks
  (`_raw_smart_sim_index` + `_merge_sim_indexes`, `wnba/cards.py:540-564`,
  used at `:1386`).
- Has `source_proxy.py` (a mirror/proxy pattern for source-app text/styles)
  with no NBA equivalent.
- Exposes more live-data builders directly at the cards layer
  (`build_live_lines_payload`, `build_live_pbp_stats_payload`,
  `build_live_player_lens_payload` — `blueprints/wnba.py:29-33`), where NBA
  keeps the equivalents in a separate `live_lens.py` module
  (`blueprints/nba.py:28-32`).
- **Net read**: WNBA is the more mature/battle-tested module by file size and
  fallback depth (matches its status as the reference basketball migration
  target); NBA is structurally cleaner/more modular but functionally thinner
  in a few specific spots (no raw-artifact fallback).
- Neither module imports `basketball_props_smart_sim` directly — both
  consume its OUTPUT artifact only, matching the "web reads, workers write"
  architecture rule in `CLAUDE.md`.

### NCAAB (`syndicate/features/ncaab/`)
Files: `cards.py`, `game_detail.py`, `intelligence_analysis.py`,
`live_lens.py`, `mirror_export.py`, `results_archive.py`, `season.py`,
`sources.py`. See Sec1 — no sim engine, consumes an external mirror's
pre-computed recommendations. `mirror_export.py` is a generic CSV->JSON
exporter for that mirror with no model logic of its own.

---

## 4. Existing ad-hoc audit tools (`vendor/{wnba,nba}_betting_repo/tools/`)

Same script set in both vendor trees (NBA has a few extra `_tmp_*` scratch
files WNBA lacks). These are what already existed before this lane's
structural checklist — read to avoid duplicating known coverage, not replaced
by it (they check different things: roster-name coverage, minutes-budget
sanity, backtest calibration — not consumed-vs-populated engine inputs).

| tool | checks | gates? |
|---|---|---|
| `audit_smart_sim_player_coverage.py` | diffs each `smart_sim_<date>_<HOME>_<AWAY>.json` roster against the expected player pool from `props_predictions_<date>.csv` (+ odds-book props snapshot) | **yes** — `SystemExit(2)` on any finding |
| `audit_smart_sim_minutes.py` | per-team `min_mean` sums to ~200 (WNBA) / ~240 (NBA, different constant — the two copies are NOT byte-identical here); per-player cap (44.0 default) | **yes** — `return 1` on bad rows, `return 2` if no data at all. **NBA copy lacks WNBA's `cards_sim_detail` fallback** — will hard-fail on missing-raw-files days where WNBA soft-skips |
| `audit_smart_sim_coverage_range.py` | multi-day version of player-coverage audit over a `--start`/`--end` range | no — descriptive only |
| `audit_smartsim_roster_sources.py` | detects whether SmartSim rosters were augmented beyond the pregame props pool using post-game boxscore data (lookahead-risk / leakage check) | no (except empty-input `return 2`) — descriptive |
| `audit_prop_player_aliases.py` | calls the live `/api/cards` payload in-process, fuzzy-matches prop-line players missing from the SmartSim boxscore to likely name aliases | **yes** — `return 2` if any unresolved issues |
| `audit_slate_prob_backtest.py` | calibration (predicted-bin vs realized win rate), Brier score, `win_prob` distribution, random-baseline comparison against a `backtest_top_recommendations.py --kind slate_prob` ledger | no — descriptive (`return 0` unless the ledger itself fails to load) |

**Other `audit_*.py` scripts present (11 total per vendor tree) not in the
lane brief's list, relevant to sim-input auditing**:

| tool | checks | gates? |
|---|---|---|
| `audit_injuries_counts_consistency.py` | cross-checks `injuries_counts` against `league_status`/`props_predictions` for conflicting exclusion state | **yes** — `return 2` on conflicts |
| `audit_rosters_today.py` | trade-day guardrail: daily roster-file freshness + `league_status` team assignments vs processed season rosters | **yes** — multiple `SystemExit(2\|4)` paths |
| `audit_sim_engine_data_gaps_range.py` | file existence + pregame-signal column coverage (expected minutes, starters, as-of timestamp) over a date range | **yes**, when `--fail-on-missing-expected-minutes`-style flags are passed |
| `audit_stale_exclusions_range.py` | stale injury exclusions over a date range | no — descriptive |
| `audit_stale_exclusions_today.py` | single-day stale-exclusions audit | **yes** — `SystemExit(2)` on findings |

**None of these is the CONSUMED-vs-POPULATED gate `model_engine_standard.md`
requires.** They check roster-name coverage, minutes-budget sanity, injury
freshness, and slate-level backtest calibration — real and useful, but none
of them asks "does the engine read a field nothing feeds." That gap is what
`scripts/basketball_sim_input_checklist.py` fills.

---

## 5. Known open gaps, with todo.md IDs

| id | one-line | status |
|---|---|---|
| `#440` | Sim-engine track pin; includes the basketball no-sampling-fallback hypothesis and the `n_sims=100 vs 2000 default` observation | PLANNED, referenced throughout this lane's docs; Level 0 of the new checklist upgrades the fallback question from hypothesis to a twice-measured negative (still not proven impossible on the live worker — see reference doc Sec2) |
| `#454` | Play-by-play is an unused offline modelling substrate, 5 of 8 sports (not 8) | OPEN, unowned. Its own census explicitly lists **NCAAB as having NO pbp**, alongside NHL and soccer; WNBA and NBA both have real pbp files. Not this lane's scope to fix. |
| `#455` | WNBA `/api/live_pbp_stats` serves a frozen all-null skeleton for live/final games, reads as `ok: True` | OPEN, unowned. Different layer (live in-game endpoint, not the pregame sim-input checklist this lane built) — noted, not touched. |
| `#456` | NBA `/api/live_pbp_stats` serves a snapshot from the wrong day under the requested day's label | Fix built + tested, NOT DEPLOYED. Same note as `#455`. |
| new (this lane) | WNBA `team_advanced_stats` producer never emits a `games` column; NBA's does | See `docs/ai_context/basketball_sim_engine_reference.md` Sec4 and the new todo.md item this lane added |
| new (this lane) | Four optional per-game calibration artifacts (`smart_sim_total_calibration.json`, `intervals_band_calibration.json`, `intervals_time_profile.json`, `player_stat_calibration.json`) have builder tools in `vendor/*/tools/` that no scheduled pipeline invokes | See reference doc Sec5 and the new todo.md item |
| new (this lane) | None of `team_advanced_stats_*.csv`, `player_logs.csv`, `player_priors_*.csv`, or the four calibration JSON filenames appear in `HOT_ARTIFACT_PATTERNS` | See reference doc Sec7 and the new todo.md item |

**`#342`** (WNBA live-edges suppression-rule parity) is already closed —
verified via `todo.md` grep, not re-litigated here.

---

## 6. What this lane did NOT do

- Did not build an NCAAB sim engine (explicitly out of scope per the lane
  brief).
- Did not touch `board_enrichment.py`, `run_live_odds_refresh_worker.py`, or
  `wnba_fixture_identity.py` (held by other open lanes).
- Did not fix the WNBA `games`-column gap, the unwired calibration builders,
  or the `HOT_ARTIFACT_PATTERNS` gap — flagged, not remediated, per the
  audit-and-report scope of this lane.
- Did not re-derive the `n_sims=100` production reading fresh (Render 502'd
  during this session) — cited the existing 2026-08-15 measurement instead of
  re-asserting it as new.
- Did not deploy, push, or commit.

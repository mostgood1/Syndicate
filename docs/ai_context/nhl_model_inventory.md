# NHL model inventory — what exists and where

> 2026-08-18, lane `nhl-model-owner`. NHL's counterpart to the
> MLB/basketball "what exists and where" documents (`basketball_model_inventory.md`
> is the closest sibling in structure). Catalog only — for input-population
> findings, the pipeline trace, and the Elo backtest, see
> `docs/ai_context/hockeysim_engine_reference.md`.

---

## 1. Sim engine

**One Syndicate-native engine, `hockeysim`, replacing a vendored trained-NN
engine — NOT a straight port, a deliberate redesign.**

| | |
|---|---|
| engine | `syndicate/features/nhl/sim_engine/hockeysim/` — 34 files |
| entry points | `projection.project_game` (pregame xG/Poisson/Elo → expected goals + period lambdas), `game_market_sim.simulate_from_period_lambdas` (fast ML/spread/total path), `engine.HockeySim` (possession-level boxscore/props sim) |
| what it replaced | `vendor/nhl_betting_repo/nhl_betting/models/nn_games.py` — a trained neural net. `projection.py`'s own docstring: *"the Syndicate-native replacement for the vendor's trained NN game model... rather than porting the neural net, it derives per-team expected goals from an xG / Poisson / Elo formulation."* This was a deliberate architecture change, not a migration-in-progress. |
| calibration | **Two separate profile objects, easily conflated** (see reference doc §2): `projection.ProjectionProfile` (truth-calibrated, Phase 3b, `#440`) governs pregame expected goals; `calibration_profile.SimConfig` / `NHL_CALIBRATION_PROFILE_DEFAULT` (still the absorbed vendor's original constants, never truth-calibrated) governs in-sim mechanics — dispersion, special-teams multipliers, faceoff knobs. |
| granularity | pregame projection → per-period goal lambdas → fast game-market sim (ML/spread/total) **and separately** → possession-level boxscore sim (props) |
| truth layer | `historical_truth/` — real finished-game feeds from `api-web.nhle.com`, cached locally (1,312 games, 2025-10-07..2026-04-16, `nhl_source/data/truth/raw/landing_*.json`, untracked mirror output). Used for the Phase 3 truth baseline (`docs/reports/hockeysim_phase3_truth_baseline_report.md`), Phase 3b calibration (`hockeysim_phase3b_calibration_report.md`), and (new, this session) the Elo producer. |

**This is more mature on the sim-math side than CLAUDE.md's "Module maturity"
table implies** — that table describes board/UI migration status, not the
sim engine, which is closer to soccer's (real, calibrated, truth-baselined)
than "active migration, varying completeness" suggests.

---

## 2. Feature module inventory (`syndicate/features/nhl/`)

| file | size | role |
|---|---|---|
| `cards.py` | 46,126 bytes | main board — reads `predictions_{date}.csv` / `predictions_sim_{date}.csv` / `props_recommendations_{date}.csv` directly (`processed_path(...)`) |
| `live_lens.py` | 31,689 bytes | in-game live projection surface |
| `market_accuracy.py` | 12,802 bytes | model-vs-market accuracy tracking |
| `sources.py` | 9,949 bytes | artifact mirror path resolution |
| `picks.py` | 8,765 bytes | picks surface |
| `betting_recap.py` | 7,861 bytes | recap surface |
| `archive.py` | 6,066 bytes | daily archive |
| `player_props_reconciliation.py` | 5,818 bytes | props settlement reconciliation |
| `props_lines.py` | 3,611 bytes | props market-line handling |
| `intelligence_analysis.py` | 1,802 bytes | intelligence-layer integration |
| `live_lens_daily_accuracy.py`, `live_game_accuracy.py` | <1KB each | thin accuracy-tracking shims |

No `betting_card.py`/`features.py` split the way basketball's NBA module has
— NHL's `cards.py` is the single largest file and carries most of the board
logic directly, closer to WNBA's shape (one large `cards.py`) than NBA's
(split across dedicated files) per `basketball_model_inventory.md`'s §3
comparison.

`syndicate/blueprints/nhl.py` is the Flask blueprint; it does not call
`build_nhl_artifacts.py` or the sim engine directly — consistent with the
"web reads, workers/self-generation write" rule (see reference doc §7 for the
specific self-generation mechanism this sport uses instead of the
worker-push-to-web pattern MLB/basketball use).

---

## 3. Producer / script inventory (`scripts/`)

| script | role | new this session? |
|---|---|---|
| `build_nhl_artifacts.py` | the daily producer — `build_predictions_for_date`, `build_recommendations_for_date`, `build_props_for_date` | no |
| `refresh_nhl_oddsapi.py` | odds refresh + owns local-generation gating (`SYNDICATE_NHL_SOURCE_CLI_GENERATION`) | no |
| `refresh_nhl_source_mirror.ps1` | cold-start mirror refresh | no |
| `nhl_sim_input_checklist.py` | the CONSUMED-vs-POPULATED gate `model_engine_standard.md` §1 requires — **did not exist before this session** | **yes** |
| `build_nhl_elo_artifact.py` | Elo producer from cached truth data | **yes** |

**No dedicated audit/checklist tooling existed in the vendor tree before this
session.** `vendor/nhl_betting_repo/nhl_betting/scripts/` holds
`backtest_daily_summary.py`, `build_two_seasons(_web).py`, `daily_update.py`,
`first10_eval.py`, `infer_odds_from_edges.py`, `reexport_onnx.py`,
`train_nn_games.py`, `train_nn_props.py` — training/backtest/build tooling for
the now-replaced NN engine, not input-population auditing. This contrasts with
basketball, which inherited a rich `audit_*.py` set (11+ tools per vendor tree)
from its own vendor repos; NHL had none of that class of tool at all until
`nhl_sim_input_checklist.py` this session.

---

## 4. Known open gaps, with `todo.md` IDs

| id | one-line | status |
|---|---|---|
| `#463` | This session's findings: `elo_rating` + `goals_per_60` staleness FIXED; `shots_per_60`/`blocks_per_60`/`penalties_per_60`/`faceoff_win_pct`/player weights/`special_teams` (7 keys) genuinely absent, 16 alarms remain | FOUND, MEASURED, PARTIALLY FIXED this session |
| `#454` | Play-by-play is an unused offline modelling substrate — NHL is one of only 3 sports (with soccer, NCAAB) with **zero** pbp files ingested | OPEN, unowned. Directly relevant to §3's finding: extending the truth-loader's parser (needed for `special_teams`/team-rate data, reference doc §5) and building real pbp ingestion are related but not identical asks — pbp would give shot-by-shot/event-level detail this session's fixes don't touch at all. |
| `#440` | Sim-engine track pin (cross-sport); this session's work is NHL's contribution to it | PLANNED, referenced throughout |

**`.syndicate/audit_2026-08-14_models.md`** (line 170/192) already flagged NHL's
`market_anchoring.py` circularity (current book prices as a model input,
making market-relative evaluation near-circular by construction) — carried
forward as a standing caveat in the reference doc §7, not re-litigated here.

---

## 5. What this lane did NOT do

- Did not build the `special_teams` per-team PP/PK data pipeline — flagged as
  likely the single highest-value remaining gap (reference doc §5), but it
  needs the truth-loader's landing-feed parser extended first, a real
  data-pipeline build, not a wiring fix attempted or half-attempted here.
- Did not build per-team `shots_per_60`/`blocks_per_60`/`penalties_per_60`/
  `faceoff_win_pct` or player usage weights — same reason.
- Did not build a real xG (expected goals) model — the reader and allowlist
  exist; the shot-quality model producing the data does not, and building one
  is a distinct, substantial modelling project, not an input-population fix.
- Did not turn on `elo_blend_weight` — measured that a naive win/loss Elo
  shows no edge over a constant baseline at the current `elo_home_adv`, and
  left the mechanism populated-but-off with that measurement recorded
  (reference doc §6), per the standard's mechanism-vs-estimator discipline.
- Did not truth-calibrate `calibration_profile.py`'s `SimConfig` (shot/goal
  dispersion, special-teams multipliers, faceoff knobs) — flagged in the
  correction (reference doc §2) as a distinct, still-open gap from the
  `ProjectionProfile` calibration that WAS already done.
- Did not wire `nhl_sim_input_checklist.py` into `/preflight` or
  `migration_gate.py` — built and verified standalone; gating integration is
  a follow-up.
- Did not fully trace NHL's per-service self-generation mechanism to a single
  definitive call site (reference doc §7) — traced it far enough to confirm
  production actually serves real data and to name the likely mechanism
  (`SYNDICATE_NHL_SOURCE_CLI_GENERATION`, defaults enabled), but stopped short
  of a file:line-exact trace once the "is this broken" question was answered
  (it is not).
- Did not deploy. All changes are local/committed-pending; `predictions_*.csv`'s
  self-generation means this sport's runtime behavior does not depend on a
  push deploy the way MLB's roster-artifact reuse trap does — but the elo/xG
  allowlist and `goals_per_60` fix still need a normal code deploy to reach
  Render like any other `.py` change.

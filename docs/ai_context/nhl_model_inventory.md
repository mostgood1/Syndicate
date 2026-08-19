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
| `nhl_sim_input_checklist.py` | the CONSUMED-vs-POPULATED gate `model_engine_standard.md` §1 requires — **did not exist before this session**; corrected mid-session (reference doc §2b) | **yes** |
| `build_nhl_elo_artifact.py` | Elo producer from cached truth data | **yes** |
| `build_nhl_special_teams_artifact.py` | PP%/PK%/committed-per-game producer from cached truth data (extended `nhl_statsweb_loader.parse_landing` to capture penalties) | **yes** |

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
| `#463` | This session's findings: `elo_rating` + `goals_per_60` staleness + `special_teams` (`pp_pct`/`pk_pct`/`committed_per_game`) FIXED; `special_teams_cal` (7 keys) WIRED (reachable, not yet calibrated); `shots_per_60`/`blocks_per_60`/`penalties_per_60`/`faceoff_win_pct`/player weights genuinely absent, 9 alarms remain | FOUND, MEASURED, PARTIALLY FIXED this session |
| `#454` | Play-by-play is an unused offline modelling substrate — NHL is one of only 3 sports (with soccer, NCAAB) with **zero** pbp files ingested | OPEN, unowned. Directly relevant to §3's finding: extending the truth-loader's parser (already done once this session, for penalties; team-rate data would need it extended further, reference doc §5) and building real pbp ingestion are related but not identical asks — pbp would give shot-by-shot/event-level detail this session's fixes don't touch at all. |
| `#440` | Sim-engine track pin (cross-sport); this session's work is NHL's contribution to it | PLANNED, referenced throughout |

**`.syndicate/audit_2026-08-14_models.md`** (line 170/192) already flagged NHL's
`market_anchoring.py` circularity (current book prices as a model input,
making market-relative evaluation near-circular by construction) — carried
forward as a standing caveat in the reference doc §7, not re-litigated here.

---

## 5. What this lane did NOT do

- **Did** build the `HockeyTeamFeatures.special_teams` (`pp_pct`/`pk_pct`/
  `committed_per_game`) PP/PK data pipeline — extending the earlier session's
  framing, which had wrongly attributed this field to a different, unreachable
  parameter (`special_teams_cal`, corrected in reference doc §2b). Verified
  with a reachability test (elite PP outscores poor PP on average, 80 seeded
  runs) — not yet a calibration backtest of the effect SIZE.
- **Did** wire `special_teams_cal`'s 7 keys (reference doc §2c) — moved onto
  `SimConfig` (`pp_shot_cal_mult` etc), resolved via `build_nhl_sim_config`,
  mapped and passed by `player_props._special_teams_cal`. Values initially
  unchanged from the old neutral defaults (a wiring fix, not yet a calibration
  change); reachability-tested the same way as `pp_pct` above.
- **Did** calibrate `pp_goal_cal_mult`/`pk_goal_cal_mult` against real truth
  (reference doc §2d, full report `docs/reports/hockeysim_special_teams_goal_cal_report.md`).
  Added a new truth metric (`sh_goal_share`, from a new `sh_goals_home/away`
  parser extension — no new fetch) and ran the REAL engine over thousands of
  simulated games to search for the multiplier matching it. Result:
  `pp_goal_cal_mult` needed no correction (the existing mechanism was already
  accurate); `pk_goal_cal_mult` needed a real one — uncalibrated, the engine
  simulated shorthanded goals at more than double the real rate. Corrected to
  `0.4645`, locked in a test. Deliberately did NOT attempt per-team
  differentiation of either multiplier — that would double-count against the
  already-per-team `pp_pct`/`pk_pct` signal (reference doc §2d/§5).
- **Did** bulk-fetch the `boxscore` endpoint (`scripts/fetch_nhl_boxscore_cache.py`,
  1,297 new fetches, 0 failures — only 11/1,312 games were cached before) and
  build `historical_truth/boxscore_shot_strength.py` to parse per-team PP/PK
  SHOT volume (distinct from the goal-share truth above; the `landing` feed
  has no shot-by-strength-state breakdown). Cross-validated against the
  independent `landing` feed's SOG count (55.27 vs 55.66 — close agreement,
  two different endpoints/parsers).
- **Did** calibrate `pp_shot_cal_mult`/`pk_shot_cal_mult` against that new
  truth (reference doc §2e, full report
  `docs/reports/hockeysim_special_teams_shot_cal_report.md`). Found and fixed
  a real methodology bug along the way: a naive sequential fit (pp then pk)
  left a ~5% verification gap even at 260,000 simulated shots, because the two
  targets share a denominator and the uncalibrated pk correction shifts it
  substantially. Fixed with a JOINT alternating fit (3 rounds) plus a full
  round-robin team-pairing (removes a second variance source). Result:
  `pp_shot_cal_mult=0.9108` (real, modest correction), `pk_shot_cal_mult=0.3369`
  (real, substantial — shots-while-shorthanded were over-simulated ~2.8x,
  matching the same direction/magnitude as `pk_goal_cal_mult`'s correction,
  circumstantial evidence of one shared root cause rather than two). Final
  verification: 318,093 simulated shots, both targets matched almost exactly.
- **Did** build genuine per-team PP/PK SHOT-volume differentiation (reference
  doc §2f, full report `docs/reports/hockeysim_per_team_shot_rate_report.md`)
  — a NEW mechanism, not a calibration. `historical_truth.boxscore_shot_strength.compute_team_shot_rate_index`
  produces `pp_shot_index`/`pk_shot_index_allowed` per team, normalized by
  PP/PK OPPORTUNITY count (not raw shot count, to avoid conflating "how often
  on the power play" with "how many shots once there"). Wired into `engine.py`'s
  `home_factor`/`away_factor` shot-volume terms alongside the existing global
  multipliers. Measured: mean ≈1.006 across 32 real teams (confirms proper
  normalization); real spread NJD 1.237x to MTL 0.802x; EDM lands near the
  top (1.137x), the same team independently measured with the league's best
  PP goal rate — two unrelated data sources agreeing. **Verified the existing
  global calibration did not need re-fitting**: with real per-team indices
  active, the league-wide simulated aggregate still matches truth closely
  (`pp_shot_share` 0.1478 vs 0.1488, `sh_shot_share` 0.0279 vs 0.0272,
  158,826 simulated shots) — the per-team layer shifts which team gets more
  shots in a matchup, not the league average. Reachability-tested.
- **Did** build genuine per-team blocked-shot-rate differentiation (reference
  doc §2g, full report `docs/reports/hockeysim_per_team_block_rate_report.md`)
  — closing the last special-teams gap. `historical_truth.boxscore_block_rate.compute_team_block_rate_index`
  produces `block_rate_index` per team from the same `boxscore` cache §2e/§2f
  already bulk-fetched (blocks/shots-faced ratio, normalized against the
  league-wide ratio — the ONLY basis available, since blocked shots carry no
  strength-state split in this source at all, unlike PP/PK shots). Measured:
  1,312 games, league block rate 33.77%, 14.19 blocks/game/team, mean index
  0.9999 (confirms normalization); real spread PHI (1.102x)/VGK (1.098x)/MTL
  (1.091x) highest, NSH (0.867x)/CHI (0.869x) lowest, ~27% top-to-bottom.
  Wired into `engine.py`, scaling the blocking team's own probability right
  before the block roll, clamped `[0.02, 0.95]`. **Verified the league-wide
  average did not shift**: 200 round-robin pairings, 24.635 avg blocks/game
  neutral vs 24.475 real-indexed — noise-level. Reachability-tested. Explicitly
  did NOT calibrate the ABSOLUTE block rate (simulated ~12.2-12.3/team/game
  sits below the real 14.19) — the base constants (`block_rate_ev` etc.)
  remain the vendor's original guess; only relative per-team scale was built,
  matching this task's scope.
- Did not build per-team `shots_per_60`/`blocks_per_60`/`penalties_per_60`/
  `faceoff_win_pct` (the GLOBAL team rates the props engine's `TeamRates`
  reads) or player usage weights — needs the truth-loader's parser extended
  further (beyond the penalties extension already done this session). This is
  distinct from the PP/PK-specific shot/block differentiation just built above.
- Did not re-run the goal-multiplier calibration (§2d, earlier this session)
  with the joint-fit method the shot-multiplier bug discovery motivated —
  flagged as an open methodology-consistency gap, not a known error (its own
  verification was already reasonably tight).
- Did not calibrate the ABSOLUTE block rate to real truth (§2g leaves the base
  constants at the vendor's uncalibrated 0.45/0.55/0.35), build strength-state-specific
  per-team blocking (no data source distinguishes it), or investigate the
  faceoff multiplier's interaction with the new per-team shot/block indices
  (§2f/§2g) — the faceoff effect is EV-only by default and untouched by this
  pass.
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

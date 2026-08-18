# NHL Sim Engine (hockeysim) — reference, input state, and operating procedure

> 2026-08-18, lane `nhl-model-owner`. hockeysim's counterpart to
> `docs/ai_context/mlb_sim_engine_reference.md` (MLB) and
> `docs/ai_context/basketball_sim_engine_reference.md` (NBA/WNBA) — the
> `model_engine_standard.md` treatment applied to this engine specifically. For
> the module/file catalog (what exists and where, independent of input
> population), see `docs/ai_context/nhl_model_inventory.md`.
>
> **Read `docs/ai_context/model_engine_standard.md` first** — this document is
> that standard applied to one engine, not a substitute for it. Every number
> below is `[measured against this checkout]` unless marked otherwise; per the
> standard's §3b, a local-checkout measurement is not a production fact — see
> §7.

---

## 1. The pipeline, file:line at each hop

```
refresh_odds_sources._run_command  (odds-refresh step; sim_run_ledger.py:53 classifies it)
  -> scripts/refresh_nhl_oddsapi.py           _run_owned_generation, gated by
                                               SYNDICATE_NHL_SOURCE_CLI_GENERATION (default ON)
    -> scripts/build_nhl_artifacts.py
         build_predictions_for_date              -> predictions_{date}.csv
         build_recommendations_for_date          -> recommendations_sim_{date}.csv
         build_props_for_date                    -> props_recommendations_{date}.csv
      -> hockeysim/features/loaders.py
           build_slate_features(date)
             load_team_xg_map / load_team_elo_map / load_lineups / load_starting_goalies
             build_team_features(name, xg_map, elo_map)     :182
             build_game_features(..., project=True)          :238 (project defaults True — reachable)
               apply_projection(home, away)                  hockeysim/projection.py :206
                 project_game(...)                            Poisson / xG / Elo formulation
      -> hockeysim/adapters.py :: build_game_prediction        -> HockeyGamePrediction
      -> hockeysim/artifacts.py :: write_predictions_csv       -> predictions_{date}.csv (PREDICTIONS_COLUMNS)
      -> hockeysim/player_props.py :: <TeamRates from features>
      -> hockeysim/engine.py :: HockeySim (boxscore/possession-level sim)   -> props_recommendations_{date}.csv
```

**Writes, in flight** (`data/nhl_source/data/processed/`):

| path | content |
|---|---|
| `predictions_{date}.csv` | game-level ML/spread/total/period/EV — what `nhl/cards.py` reads for the main board |
| `predictions_sim_{date}.csv`, `recommendations_sim_{date}.csv` | sim-detail variants |
| `props_recommendations_{date}.csv` | player-market recommendations (SOG/GOALS/ASSISTS/POINTS/SAVES/BLOCKS) |
| `lineups_{date}.csv`, `starting_goalies_{date}.csv`, `roster_snapshot_{date}.csv` | per-date roster inputs |
| `team_xg_{season}.csv` / `team_xg_latest.csv` | xG input — **no producer writes this file; see §5** |
| `team_elo_{season}.csv` / `team_elo_latest.csv` | Elo input — **new this session, see §4** |

---

## 2. A correction to `todo.md` — the Phase 3b calibration WAS applied

`todo.md`'s `#440` note claimed *"hockeysim's Phase 3b calibrated deltas were
computed and never applied."* **This was wrong**, and it is the same failure
shape MLB's own reference doc names in §2b — grepping the wrong file and
publishing a claim from it. `docs/reports/hockeysim_phase3b_calibration_report.md`'s
"Applied profile overrides" table lists 5 fields
(`league_baseline_goals_per_60`, `league_xg_per_60`, `home_ice_attack_mult`,
`away_ice_attack_mult`, `period_shares`). Those live in **`projection.py`'s
`ProjectionProfile`**, not **`calibration_profile.py`'s `SimConfig`** — two
separate profile objects with adjacent, easily-conflated names (one governs
the *pregame expected-goal* derivation, the other the *in-sim* mechanics:
dispersion, special-teams multipliers, faceoff knobs). Grepping the deltas
against `calibration_profile.py` returns nothing, which is exactly what
produced the wrong claim.

**Confirmed applied, three ways:**
- The values in `projection.py`'s `NHL_PROJECTION_PROFILE` match the report's
  table exactly, with inline provenance comments citing the truth baseline.
- `git log` on `projection.py`: commit `29fac7ce`, titled *"NHL revamp Phase 3b
  (applied): calibrate projection profile to full-season truth."*
- **Reachable, not just present**: `loaders.build_game_features`'s `project`
  parameter defaults to `True` (`features/loaders.py:250`), so
  `apply_projection` — and therefore the calibrated profile — runs on every
  slate build by default, with no flag to flip.

`SimConfig`'s own baseline (`NHL_CALIBRATION_PROFILE_DEFAULT` in
`calibration_profile.py`) is a **different, genuinely uncalibrated** set of
constants — "the values the absorbed engine shipped with," per its own
docstring — covering shot/goal dispersion and special-teams multipliers. That
one really has never been truth-calibrated. Worth a future pass, but it is not
the same claim `todo.md` made, and conflating the two is exactly what produced
the wrong original claim.

`calibration_profile.py` already resolves through the Phase 5 versioned-profile
seam (`load_versioned_profile`, `#440` Part 4) — a no-op today (no artifact
exists at `calibration_profile_path("nhl")`), but the mechanism to ship a
calibrated `SimConfig` as a JSON artifact rather than a source edit already
exists if that future pass wants it.

---

## 3. Input provenance — where each input is produced and applied

| input | produced by | applied in | population `[this checkout]` |
|---|---|---|---|
| `xgf_per_60` / `xga_per_60` | **no producer exists** — `load_team_xg_map` reads `team_xg_{season}.csv`, which nothing writes | `projection._offense_rate` / `_defense_rate` (falls back to `goals_per_60`, then league baseline) | 0% — genuinely absent, §5 |
| `elo_rating` | **NEW**: `historical_truth/elo_builder.py` + `scripts/build_nhl_elo_artifact.py`, from 1,312 cached real games | `projection._elo_win_prob`, gated at `elo_blend_weight` (default `0.0`) | 100% after the fix (§4); blend deliberately still off |
| `goals_per_60` | `apply_projection` back-fills from `proj_home_goals`/`proj_away_goals` (**NEW** this session) | `player_props.py`'s `TeamRates` construction, then `engine.py` (shots/goals allocation, saves) | was 0% (stuck at the stale `2.9` default) → 100%, matchup-adjusted, after the fix |
| `shots_per_60`, `blocks_per_60`, `penalties_per_60`, `faceoff_win_pct` | **no producer exists** — `build_team_features` never sets them | same `TeamRates` construction, direct passthrough (`player_props.py:43-48`) | 0% — genuinely absent, §5 |
| `shot_weight`, `goal_weight`, `block_weight` (player) | **no producer exists** — `build_player_features` never sets them | player-level allocation weighting inside `engine.py` | 0% — genuinely absent, §5 |
| `special_teams` (dict; 7 keys) | **no producer exists** | `player_props.py:90-91` → `engine.py`'s `special_teams_cal.get(key, NEUTRAL)`, 7 sites | 0% — every team, every game — genuinely absent, §5 |
| `period_goal_lambdas` | `apply_projection`, from the (now-corrected) projection | `game_market_sim.py` — the **main board's** ML/spread/total | 100%, and this is what makes the main board unaffected by everything else in this table |

**The main-board / props-engine split is the load-bearing fact in this
table.** `game_market_sim.py` (moneyline/spread/total, what `predictions_{date}.csv`
serves to `nhl/cards.py`) consumes **only** `period_goal_lambdas`. Every other
row feeds `player_props.py` → `engine.py`, the boxscore/possession-level sim
behind player props (SOG/GOALS/ASSISTS/POINTS/SAVES/BLOCKS). A reader who
checks "does the NHL board work" by looking at moneyline/spread/total would
correctly conclude yes, while every prop market runs on entirely
undifferentiated, league-average team rates. **Checking one does not check
the other** — the same lesson as MLB's BVP row, in a different shape: here
the trap is two SIM PATHS sharing one contract, not two files sharing one
concept.

---

## 4. What was built this session

| thing | state | gate |
|---|---|---|
| `historical_truth/elo_builder.py` — chronological Elo, no-lookahead pregame view, Brier-score helper | built, tested (`tests/test_hockeysim_elo_builder.py`) | pure function, no gate needed |
| `scripts/build_nhl_elo_artifact.py` — producer, run against 1,312 cached real games | built, run: 32 teams rated | writes `team_elo_{season}.csv` / `team_elo_latest.csv` |
| `elo_map` wiring — `loaders.load_team_elo_map` → `build_team_features` → `build_game_features` → `build_slate_features` | built, tested end-to-end against real mirrored data (`test_build_game_features_populates_elo_end_to_end`) | reachable by default, no flag |
| `goals_per_60` back-fill in `apply_projection` | built, tested (56 existing projection/loaders/engine/props/adapter tests still pass) | reachable by default, no flag |
| `HOT_ARTIFACT_PATTERNS`: `team_xg_*.csv`, `team_elo_*.csv` | added | makes both auditable via `/api/ops/artifacts/*`; does not by itself produce xG data |
| `scripts/nhl_sim_input_checklist.py` — the gating checklist `model_engine_standard.md` §1 requires | built, exits 1 (16 alarms) | not yet wired into `/preflight` or `migration_gate.py` — next step for whoever picks this up |

**All of it is additive and reachable-by-default** — no new flag was
introduced that needs to be flipped later. The one thing deliberately left OFF
is `elo_blend_weight`, and §6 explains why with a measurement, not caution
alone.

---

## 5. Genuinely absent (not merely unfed) — 16 alarms, `scripts/nhl_sim_input_checklist.py`

`[measured against this checkout: 9 mirrored dates 2026-06-02..2026-07-09,
10 team-sides, 297 players — per §7, UNMEASURED against Render, not 0%,
until checked there]`

```
--- HockeyTeamFeatures ---
  0.0%   blocks_per_60      FAIL  consumed but NEVER populated
  0.0%   faceoff_win_pct    FAIL  consumed but NEVER populated
  0.0%   penalties_per_60   FAIL  consumed but NEVER populated
  0.0%   shots_per_60       FAIL  consumed but NEVER populated
  0.0%   xga_per_60         FAIL  consumed but NEVER populated
  0.0%   xgf_per_60         FAIL  consumed but NEVER populated

--- HockeyPlayerFeatures ---
  0.0%   block_weight       FAIL  consumed but NEVER populated
  0.0%   goal_weight        FAIL  consumed but NEVER populated
  0.0%   shot_weight        FAIL  consumed but NEVER populated

--- special_teams (7 keys, AST-walked from engine.py, not hand-listed) ---
  0.0%   pp_shot_multiplier    0.0%   pk_shot_multiplier
  0.0%   pp_goal_multiplier    0.0%   pk_goal_multiplier
  0.0%   blocks_ev_rate        0.0%   blocks_pk_rate     0.0%   blocks_pp_def_rate
```

Each of these needs **real per-team/per-player data the current truth loader
does not capture**, not a wiring fix — the same "needs a definition first"
class MLB's remaining 5 fall into, not the "just populate an existing pipe"
class `elo_rating` and `goals_per_60` were:

- **Team rates** (`shots_per_60`/`blocks_per_60`/`penalties_per_60`/
  `faceoff_win_pct`): `historical_truth.HistoricalGameRecord` captures goals,
  SOG, and period splits — not blocks, penalty minutes, or faceoff outcomes.
  The `api-web.nhle.com` landing feed likely carries more than
  `nhl_statsweb_loader.parse_landing` currently extracts; extending the parser
  is the first step, not the last.
- **`xgf_per_60`/`xga_per_60`**: the reader (`load_team_xg_map`) and the
  allowlist entry both exist now. The underlying shot-quality model needed to
  produce `team_xg_*.csv` does not — this is a real xG model (shot location,
  type, on-ice state), not a rate a truth-loader extension alone would give.
  Falls back to `goals_per_60` gracefully in the meantime.
- **Player weights** (`shot_weight`/`goal_weight`/`block_weight`): usage-share
  weighting for the props allocator; needs per-player game logs the current
  loaders don't read.
- **`special_teams`**: needs PP/PK opportunity and conversion data split by
  strength state. `HistoricalGameRecord` already has `pp_goals_home/away` (PP
  **goals**) but not PP **shots** or PK opportunities/goals-against — closer
  to buildable than team rates, but still needs the parser extended, not just
  the existing fields aggregated.
  **This is likely the single highest-value remaining gap**: special-teams
  differentiation is one of the most bettor-relevant dimensions in hockey, and
  every multiplier the props engine applies for it is currently at its
  hardcoded neutral default, for every team, unconditionally.

---

## 6. Measured — the Elo backtest, and why blending stays off

`[measured against this checkout's cached truth data, 1,312 games, 2025-10-07..2026-04-16]`

A simple win/loss Elo (K=20, scale=400, matching `ProjectionProfile.elo_scale`)
does **not** demonstrate predictive edge over a trivial baseline in one
season:

| model | Brier score | vs. baseline |
|---|---|---|
| constant home-win-rate (0.5221) | **0.24951** | baseline |
| Elo, `home_advantage=50` (the profile's existing `elo_home_adv` default) | 0.25060 | **worse** |
| Elo, `home_advantage=25` (best of a 0/25/50/75/100 sweep) | 0.24870 | marginally better, noise-level over n=1,312 |

Lower is better; 0.25 is what a coin flip scores. This is the same discipline
MLB's reference doc applies in its §5 ("no demonstrated edge anywhere") and
the standard's §4.4-4.5: **populate the input, measure the mechanism, and do
not turn on a blend weight just because the plumbing now works.**
`elo_blend_weight` stays at its existing default `0.0`. This is not
withheld-pending-caution — it is a measured result that says a naive win/loss
Elo, at least at the currently-configured home-ice bump, does not clear the
bar. A goal-differential Elo, a multi-season sample, or Elo informed by the
(currently also-absent) xG signal are the natural next attempts, not
re-sweeping this same formulation.

---

## 7. Standing caveat on production — a genuine architectural difference from MLB

MLB's pattern is worker-computes → `HOT_ARTIFACT_PATTERNS` push → web-reads.
**NHL's is not**, and this matters when reading anything above against a
production question:

- `predictions_{date}.csv` matches **no** `HOT_ARTIFACT_PATTERNS` entry
  (checked programmatically against all 122 patterns) — by MLB's logic this
  would mean the file can never reach the web service. **It does anyway**:
  confirmed live 2026-08-18, `syndicate-an21.onrender.com/nhl/api/cards?date=2026-06-09`
  served real, non-placeholder projected scores (`"Carolina Hurricanes 5.7 |
  Vegas Golden Knights 5.9"`) sourced from `/opt/render/project/data/nhl_source/data/processed/predictions_2026-06-09.csv`
  — web's **own** disk path (`syndicate-data-web`, a separate Render disk from
  refresh-worker's `syndicate-data-refresh-worker` — confirmed in `render.yaml`).
- The likely mechanism, from code (not yet fully traced to a single call
  site): `render.yaml` sets `SYNDICATE_NHL_SOURCE_CLI_GENERATION` on multiple
  services (default enabled per `refresh_nhl_oddsapi.py::_source_cli_generation_enabled`),
  and `projection.py`'s own docstring notes the projection is "pure math
  (stdlib only, no numpy / pandas / network) so it is trivially unit-testable
  and safe to call from anywhere" — i.e., this engine was deliberately built
  cheap enough that **each service independently regenerates its own local
  NHL artifacts** rather than one producer pushing to the others. This is
  architecturally different from MLB's expensive Monte Carlo, which genuinely
  needs single-computation-then-push.
- **Do not generalize MLB's allowlist-gap-means-broken pattern to NHL without
  checking.** `team_xg_*.csv`/`team_elo_*.csv` were allowlisted this session
  anyway (§4) — that is still correct practice per the standard's §3
  ("maintaining the allowlist is part of shipping an input"), and if this
  self-generation mechanism is ever centralized onto one service, those two
  files will need the allowlist that's now already in place.
- **`market_anchoring.py` circularity, inherited caveat**: `.syndicate/audit_2026-08-14_models.md`
  (line 170/192) already flags that NHL uses current book prices as a model
  input (`market_anchoring.py`), making any market-relative/CLV evaluation of
  this engine near-circular by construction until accounted for. Nothing in
  this session's work changes that; repeating it here so it isn't lost between
  documents.
- All population numbers in §5 are `[this checkout]` only. Per
  `model_engine_standard.md` §3b, that is **UNMEASURED against production**,
  not a production fact — the next step for whoever picks up §5's remaining
  gaps is `scripts/nhl_sim_input_checklist.py --publish` run on whichever
  service actually generates NHL artifacts (still to be pinned down precisely
  per the point above), the same "worker publishes the bounded report" pattern
  MLB's checklist uses.

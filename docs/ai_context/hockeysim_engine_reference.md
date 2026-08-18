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
             load_team_xg_map / load_team_elo_map / load_team_special_teams_map / load_lineups / load_starting_goalies
             build_team_features(name, xg_map, elo_map, special_teams_map)     :267
             build_game_features(..., project=True)          :330 (project defaults True — reachable)
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
| `team_special_teams_{season}.csv` / `_latest.csv` | PP%/PK%/committed-per-game input — **new this session, see §4** |

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

## 2b. A correction to THIS document's own first pass — `special_teams` is TWO unrelated things

The first version of this document (and the checklist that produced its findings) reported
`HockeyTeamFeatures.special_teams` as CONSUMED for 7 keys (`pp_shot_multiplier`, `pk_shot_multiplier`,
`pp_goal_multiplier`, `pk_goal_multiplier`, `blocks_ev_rate`, `blocks_pk_rate`, `blocks_pp_def_rate`),
AST-walked from `engine.py`'s `(special_teams_cal or {}).get(...)` call sites. **That attribution
was wrong.** `special_teams_cal` is a SEPARATE parameter from `st_home`/`st_away` — the dict
`build_team_features` actually populates is threaded to `st_home`/`st_away`
(`player_props.py:90-91`), whose real consumed keys are `pp_pct`, `pk_pct`, `committed_per_game`
(`engine.py:677-678,973-980`). `special_teams_cal` is plumbed end-to-end (`runtime.py` ->
`engine.py`, twice, both defaulting to `None`) but **no caller anywhere ever passes it a value** —
confirmed structurally (`scripts/nhl_sim_input_checklist.py`'s `special_teams_cal_reachability()`)
and by direct grep across `syndicate/features/nhl/`. This is the exact same shape as the BVP trap
in MLB's own reference doc and the `predictions_*.csv`/allowlist near-miss in §7 below: a plausible
first read, from the right AST technique pointed at the wrong variable name.

**The corrected picture:**
- `HockeyTeamFeatures.special_teams` (`pp_pct`/`pk_pct`/`committed_per_game`) — genuinely
  CONSUMED+UNPOPULATED, and now FIXED this session (§4).
- `special_teams_cal` (the 7 multiplier/block-rate keys) — was genuinely CONSUMED but
  **UNREACHABLE**, a stricter alarm than unpopulated per the standard's §4.3: populating
  `HockeyTeamFeatures` could never have fixed this even in principle, because nothing read it into
  that parameter. **Now wired, §2c.**

---

## 2c. `special_teams_cal` wired — reachable, not yet calibrated

Fixing an UNREACHABLE parameter needs a call-site change, not a data producer — done by moving the
seven values onto `SimConfig` itself (`pp_shot_cal_mult`/`pk_shot_cal_mult`/`pp_goal_cal_mult`/
`pk_goal_cal_mult`/`block_rate_ev`/`block_rate_pk`/`block_rate_pp_def`, `engine.py`), the SAME
calibration seam (`build_nhl_sim_config`, the Phase-5 versioned-profile artifact) every other
engine-level constant already uses, rather than inventing a second mechanism. `player_props.py`'s
`_special_teams_cal(cfg)` maps those fields back onto the 7 engine-facing key names and
`build_prop_projections` now passes the resolved dict at its `run_hockeysim_game(...)` call —
resolved ONCE per game (not per-sim, since it does not vary by seed).

**Values are unchanged from the old inline `.get(key, DEFAULT)` fallbacks** — this is a wiring fix,
not a calibration change (confirmed: `_special_teams_cal(build_nhl_sim_config())` reproduces the
exact old defaults, and all 224 hockeysim/nhl tests, including the pre-existing ones, pass
unmodified). Per the standard's §4.4 (mechanism vs estimator), making a parameter reachable and
turning it on with new values are two separately-justified steps — this session did only the first.

**Three of the seven keys (`block_rate_ev`/`block_rate_pk`/`block_rate_pp_def`) read, by their own
inline comment** ("higher block rate on PK segments vs EV; lower on PP defending side"), **as a
league-wide physics constant**, not a team-differentiating input — correctly placed as `SimConfig`
fields rather than something a future per-team producer should target.

**Reachability tested** (§4.3, not just "it runs without raising"):
`tests/test_hockeysim_engine.py::test_special_teams_cal_pp_goal_mult_actually_changes_output`
proves `pp_goal_cal_mult=2.5` outscores `pp_goal_cal_mult=0.5` on average across 80 seeded runs,
everything else held identical. `scripts/nhl_sim_input_checklist.py` now reports `special_teams_cal`
as reachable and, since nothing has changed a value away from its default yet, explicitly labels
each key "reachable, still at its neutral default — not yet calibrated" rather than silently
passing it as `ok` — the population-vs-calibration distinction stays visible instead of collapsing
into a single boolean.

---

## 3. Input provenance — where each input is produced and applied

| input | produced by | applied in | population `[this checkout]` |
|---|---|---|---|
| `xgf_per_60` / `xga_per_60` | **no producer exists** — `load_team_xg_map` reads `team_xg_{season}.csv`, which nothing writes | `projection._offense_rate` / `_defense_rate` (falls back to `goals_per_60`, then league baseline) | 0% — genuinely absent, §5 |
| `elo_rating` | **NEW**: `historical_truth/elo_builder.py` + `scripts/build_nhl_elo_artifact.py`, from 1,312 cached real games | `projection._elo_win_prob`, gated at `elo_blend_weight` (default `0.0`) | 100% after the fix (§4); blend deliberately still off |
| `goals_per_60` | `apply_projection` back-fills from `proj_home_goals`/`proj_away_goals` (**NEW** this session) | `player_props.py`'s `TeamRates` construction, then `engine.py` (shots/goals allocation, saves) | was 0% (stuck at the stale `2.9` default) → 100%, matchup-adjusted, after the fix |
| `shots_per_60`, `blocks_per_60`, `penalties_per_60`, `faceoff_win_pct` | **no producer exists** — `build_team_features` never sets them | same `TeamRates` construction, direct passthrough (`player_props.py:43-48`) | 0% — genuinely absent, §5 |
| `shot_weight`, `goal_weight`, `block_weight` (player) | **no producer exists** — `build_player_features` never sets them | player-level allocation weighting inside `engine.py` | 0% — genuinely absent, §5 |
| `special_teams` (dict; `pp_pct`/`pk_pct`/`committed_per_game`) | **NEW**: `historical_truth/special_teams_builder.py` + `scripts/build_nhl_special_teams_artifact.py`, from real PP goals + parsed penalty data | `player_props.py:90-91` → `st_home`/`st_away` → `engine.py:677-678,973-980` (PP/PK goal-rate adjustment) | 0% → 100% after the fix (§4) — see §2b for the correction to what this row used to say |
| `special_teams_cal` (7 keys — separate parameter, see §2b/§2c) | **NEW**: `SimConfig`'s 7 new fields, resolved via `build_nhl_sim_config` and mapped by `player_props._special_teams_cal` | `engine.py`'s multiplier/block-rate adjustments, 7 `.get()` sites | reachable now (§2c); values unchanged from the old neutral defaults — wired, not yet calibrated |
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
| `historical_truth/special_teams_builder.py` — PP%/PK%/committed-per-game aggregation, small-sample floor (`MIN_OPPORTUNITIES_FOR_RATE=15`) | built, tested (`tests/test_hockeysim_special_teams_builder.py`) | pure function, no gate needed |
| `scripts/build_nhl_special_teams_artifact.py` — producer, run against 1,312 cached real games | built, run: 32 teams rated, league avg PP% 18.8% — matches real-world NHL PP% range and reproduces known team tendencies (Edmonton highest, Philadelphia/Calgary lowest) as an external sanity check | writes `team_special_teams_{season}.csv` / `_latest.csv` |
| `nhl_statsweb_loader.parse_landing` extended to capture minor-penalty counts per team | built, tested; league-wide implied PP% from the raw counts (18.8%) matches the builder's own output exactly | feeds the special-teams builder; no new fetch needed (used the existing 1,312-game cache) |
| `special_teams_map` wiring — `loaders.load_team_special_teams_map` → `build_team_features` → `build_game_features` → `build_slate_features` | built, tested end-to-end (`test_build_game_features_populates_special_teams_end_to_end`) | reachable by default, no flag |
| `HOT_ARTIFACT_PATTERNS`: `team_xg_*.csv`, `team_elo_*.csv`, `team_special_teams_*.csv` | added | makes all three auditable via `/api/ops/artifacts/*`; does not by itself produce xG data |
| `SimConfig`'s 7 new fields + `player_props._special_teams_cal` — wires `special_teams_cal` (§2c) | built, tested (2 new reachability/mapping-fidelity tests) | reachable by default now; values unchanged, so no behavior change until a future calibration pass |
| `scripts/nhl_sim_input_checklist.py` — the gating checklist `model_engine_standard.md` §1 requires; corrected mid-session per §2b, updated again for §2c | built, exits 1 (**9 alarms**, down from 16 once `special_teams_cal` became reachable) | not yet wired into `/preflight` or `migration_gate.py` — next step for whoever picks this up |

**All of it is additive and reachable-by-default** — no new flag was
introduced that needs to be flipped later. The one thing deliberately left OFF
is `elo_blend_weight`, and §6 explains why with a measurement, not caution
alone. `special_teams`'s PP%/PK%/committed-per-game feed the engine's EXISTING
goal-rate adjustment unconditionally (no new gate to flip), so populating it
changes live output directly — unlike Elo, there is no separate blend weight
to leave off. Per the standard's §4.3 ("presence is not reachability — write
the reachability test FIRST"), `tests/test_hockeysim_engine.py::test_special_teams_pp_pct_actually_changes_output`
proves the DIRECTION is right before trusting the magnitude: an elite power
play (`pp_pct=0.35`) outscores a poor one (`pp_pct=0.08`) on average across 80
seeded runs, holding every other input identical. That is a reachability
proof, not a calibration backtest — unlike §6's Elo Brier-score measurement,
nobody has yet measured whether the SIZE of this effect matches real NHL
special-teams variance, only that the sign is correct. Worth a follow-up
measurement before leaning on it for props at scale.

---

## 5. Genuinely absent (not merely unfed) — 9 alarms, `scripts/nhl_sim_input_checklist.py`

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
```

(`HockeyTeamFeatures.special_teams`'s real 3 keys — `pp_pct`/`pk_pct`/`committed_per_game` —
are FIXED this session, §4, and no longer appear above; see §2b for how an
earlier pass of this document mis-attributed 7 OTHER keys to that field.
`special_teams_cal`'s 7 keys are also no longer here — wired reachable, §2c —
though none of them has been CALIBRATED away from its neutral default yet, a
distinct claim from "fixed"; the checklist reports this explicitly rather than
folding it into a plain `ok`.)

Each of the remaining fields needs **real per-team/per-player data the current
truth loader does not capture** — the same "needs a definition first"
class MLB's remaining 5 fall into, not the "just populate an existing pipe"
class `elo_rating`, `goals_per_60`, and `special_teams` were:

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
- **`special_teams_cal`'s 4 multiplier keys, CALIBRATED values specifically**
  (the wiring itself is done, §2c — this is about what value to put there,
  not how to deliver it): a real per-team `pp_shot_multiplier`/`pk_shot_multiplier`
  would double-count against `special_teams`'s `pp_pct`/`pk_pct` if derived from
  the same signal (the standard's §4.4 mechanism-vs-estimator trap) — a
  LEAGUE-WIDE truth-calibration pass (does the simulated PP-goal SHARE match
  `TruthMetrics.pp_goal_share` on average, the same style of check Phase 3b
  ran for the projection layer) is the right next step, not a per-team
  producer for these specifically.
- **PP/PK SHOT rates, the data those multipliers would need if made
  per-team anyway**: the `api-web.nhle.com` **boxscore** endpoint (distinct
  from the **landing** endpoint the truth loader reads) carries per-goalie
  `evenStrengthShotsAgainst`/`powerPlayShotsAgainst`/`shorthandedShotsAgainst`
  splits — verified against one cached sample game this session
  (`ingestion/nhl_web.py`'s existing `boxscore()` client already fetches and
  caches this; only 11 games are cached locally today vs. 1,312 for
  `landing`). A bulk fetch (~1,300 games, rate-limited, same pattern as the
  truth loader) is the remaining step, not a new endpoint to discover.

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

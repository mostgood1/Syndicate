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

## 2c. `special_teams_cal` wired — reachable (calibration is §2d)

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
everything else held identical. `scripts/nhl_sim_input_checklist.py` reports `special_teams_cal`
as reachable and, per key, whether its live value still matches the old neutral default or has
since been calibrated — the population-vs-calibration distinction stays visible instead of
collapsing into a single boolean (see §2d for which key changed).

---

## 2d. `pp_goal_cal_mult`/`pk_goal_cal_mult` calibrated against real truth

Full report: `docs/reports/hockeysim_special_teams_goal_cal_report.md`. Summary:
`scripts/calibrate_nhl_special_teams_goal_mult.py` runs the REAL engine (synthetic-but-neutral
rosters, real per-team `pp_pct`/`pk_pct`, league-average base rates) over thousands of simulated
games and searches for the multiplier that makes simulated `pp_goal_share`/`sh_goal_share` match
the real truth values — a new truth metric added this pass (`sh_goal_share`, from a new
`sh_goals_home`/`sh_goals_away` field on `HistoricalGameRecord`, parsed from the landing feed's
`strength == "sh"` goals; did not exist as a measurable target before).

| multiplier | truth target | before (mult=1.0) | after | verdict |
|---|---|---|---|---|
| `pp_goal_cal_mult` | `pp_goal_share` 0.1944 | 0.1938 | — | **already correct.** The `pp_pct` mechanism + existing `pp_shots_mult=1.4` were doing their job; the fitted correction (1.0013-1.0029 across iterations) is noise, not signal. Left at `1.0`. |
| `pk_goal_cal_mult` | `sh_goal_share` 0.0250 | 0.0538 | **0.4645** | **real, substantial correction.** Uncalibrated, the engine simulated shorthanded goals at MORE THAN DOUBLE the real rate. Converged and stable across iterations. |

**Why one needed a correction and the other didn't**: `cal_pp_gl_mult` scales the attacking team's
PP-goal rate — the primary, well-modeled event. `cal_pk_gl_mult` scales the defending
(shorthanded) team's OWN goal rate during that same segment — shorthanded goals, a rare event
whose base formula (`0.9 * pk_pct`, `engine.py:1000`) was evidently never fit against a real rate
(there was no truth metric to fit it against until this session).

**What this does NOT cover**, deliberately: `pp_shot_cal_mult`/`pk_shot_cal_mult` (no truth target
for PP/PK shot volume specifically — needs the boxscore endpoint's per-goalie strength-state shot
splits, §5) and the three `block_rate_*` keys (no truth target for blocked-shot rate by strength
state). Per-team differentiation of these two calibrated multipliers was deliberately NOT
attempted — they are league-wide correction constants layered on top of the already-per-team
`pp_pct`/`pk_pct` signal; making them per-team too would double-count against that signal
(`model_engine_standard.md` §4.4).

**Locked in a test**, not just a doc claim:
`tests/test_hockeysim_props.py::test_special_teams_cal_production_default_carries_the_calibration`
asserts `_special_teams_cal(build_nhl_sim_config())["pk_goal_multiplier"] == 0.4645` — a future
edit to the profile constant fails a test, not silently drifts.

---

## 2e. `pp_shot_cal_mult`/`pk_shot_cal_mult` calibrated against real truth (boxscore bulk fetch)

Full report: `docs/reports/hockeysim_special_teams_shot_cal_report.md`. This closes the gap §5
flagged as the last remaining special-teams item: the `landing` feed has no shot-by-strength-state
breakdown, so `pp_shot_cal_mult`/`pk_shot_cal_mult` had no truth target until this pass.

**New this session**: `scripts/fetch_nhl_boxscore_cache.py` bulk-fetched the separate `boxscore`
endpoint for all 1,312 regular-season games (1,297 new fetches, 0 failures — only 11 were cached
before). `historical_truth/boxscore_shot_strength.py` parses per-goalie strength-state shot splits
into `pp_shot_share`/`sh_shot_share` truth targets, mirroring `pp_goal_share`/`sh_goal_share`'s
role for the goal multipliers. Cross-validated: the derived shots/game (55.27) nearly matches the
independently-sourced `landing` feed's SOG count (55.66); PP shots convert at a materially higher
rate than average (14.88% of shots, 19.44% of goals) — matches known real hockey.

| multiplier | truth target | before (mult=1.0) | after | verdict |
|---|---|---|---|---|
| `pp_shot_cal_mult` | `pp_shot_share` 0.1488 | 0.1514 (round 1) | **0.9108** | real, modest (~9%) correction |
| `pk_shot_cal_mult` | `sh_shot_share` 0.0272 | 0.0755-0.0780 | **0.3369** | real, substantial correction — shots-while-shorthanded were over-simulated ~2.8x |

**A methodology bug this calibration found and fixed, worth carrying forward**: a first,
sequential fit (pp fully fit while pk held at the stale 1.0, then pk fit) left a ~5% verification
gap even at 260,000 simulated shots — far larger than sampling noise. Root cause: `pp_shot_share`
and `sh_shot_share` share a denominator (`total_shots`), and the uncalibrated ~3x SH-shot
inflation biased the pp fit. **Fixed with a JOINT alternating fit** (3 rounds, each multiplier
re-fit against the other's current best estimate) plus a full round-robin pairing (992 ordered
team pairs) instead of random sampling, to remove a second, smaller variance source. Final
verification (318,093 simulated shots): `pp_shot_share` 0.1476 vs 0.1488 target, `sh_shot_share`
0.0272 vs 0.0272 — exact.

**Left as a documented, not-yet-confirmed gap**: the earlier goal-multiplier calibration (§2d)
predates this discovery and used the original sequential method. Its own verification was
reasonably tight, so there's no direct evidence it has the same bias — but it was never re-run
jointly to confirm. Cheap to redo; flagged rather than silently assumed fine.

**Circumstantial but notable**: `pk_shot_cal_mult`'s correction (~2.8x over-simulated) and
`pk_goal_cal_mult`'s (~2.2x over-simulated, §2d) point the same direction at similar magnitude,
both governing the same rare shorthanded-team-does-something event class, fit independently
against independent truth sources. Suggests one shared bias in the PK segment-allocation logic
upstream of both multipliers, not two unrelated miscalibrations — not chased further this session.

**What this section originally flagged as future work — now built, §2f.**

---

## 2f. Per-team PP/PK shot-rate differentiation — a NEW mechanism, not a calibration

Full report: `docs/reports/hockeysim_per_team_shot_rate_report.md`. Closes the gap §2e left open:
until this pass, `HockeyTeamFeatures.special_teams` had NOTHING differentiating shot VOLUME per
team (`pp_pct`/`pk_pct` differentiate GOAL conversion; `cal_pp_sh_mult`/`cal_pk_sh_mult` are
LEAGUE-WIDE calibration constants) — every team's PP/PK shot generation was identical.

**The new signal**: `historical_truth.boxscore_shot_strength.compute_team_shot_rate_index` —
`pp_shot_index` = (team's PP shots / team's PP opportunities) normalized against the same
league-wide ratio; `pk_shot_index_allowed` the PK-side counterpart. Deliberately normalized by
OPPORTUNITY count (from `special_teams_builder`'s penalty-derived counts), not raw per-game shot
count, to avoid conflating "how often on the power play" (already `committed_per_game`'s job)
with "how many shots once there" — the genuinely new, independent signal. Measured on real data:
mean ≈ 1.006 across 32 teams (confirms proper normalization), real spread NJD 1.237x to MTL
0.802x. EDM lands near the top (1.137x) — the same team independently measured as having the
league's best PP GOAL rate (§2d) — two unrelated data sources agreeing on one team's PP quality.

**Wiring**: `engine.py` reads `st_home.get("pp_shot_index", 1.0)`/`st_away.get("pk_shot_index_allowed", 1.0)`
(and the symmetric pair) once per game, multiplied directly into the existing `home_factor`/
`away_factor` shot-volume terms alongside `pp_mult_shots`/`pk_mult_shots`. `scripts/build_nhl_special_teams_artifact.py`
now writes both as two ADDITIONAL columns on the SAME `team_special_teams_{season}.csv` (not a
second artifact), degrading to the neutral default when no `boxscore` cache exists.

**Verified the existing global calibration (§2e) did NOT need re-fitting**, not assumed: because
the new indices are constructed to average ≈1.0 league-wide, re-running the full round-robin
simulation with REAL per-team indices active reproduces the same league aggregate the global fit
already matched (`pp_shot_share` 0.1478 vs 0.1488 truth, `sh_shot_share` 0.0279 vs 0.0272 truth,
158,826 simulated shots) — the per-team layer changes which team gets more/fewer shots in a given
matchup, not the league-wide average.

**Reachability tested**: `test_special_teams_pp_shot_index_actually_changes_shot_volume` proves
`pp_shot_index=1.8` produces more HOME shots than `pp_shot_index=0.4` on average, 80 seeded runs,
everything else held identical.

**What this section originally flagged as future work — now built, §2g.** Faceoff-driven
interaction with the new shot index was not evaluated (the faceoff multiplier is EV-only by
default and untouched by this pass).

---

## 2g. Per-team block-rate differentiation — closes the last special-teams gap

Full report: `docs/reports/hockeysim_per_team_block_rate_report.md`. `block_rate_ev`/
`block_rate_pk`/`block_rate_pp_def` (`engine.py`'s `p_block_ev`/`p_block_pk`/`p_block_pp_def`) had
no per-team differentiation, and — unlike every other special-teams constant this session touched —
had **never been checked against a real block rate at all**; the vendor's shipped defaults
(0.45/0.55/0.35) were never measured against anything before this pass.

**The new signal**: `historical_truth.boxscore_block_rate.compute_team_block_rate_index` —
`block_index` = (team's blocks / team's shots faced) normalized against the same ratio league-wide.
`shots faced` = opponent SOG + own blocks (shot attempts aren't in this endpoint — only SOG and
blocks are), the SAME basis mismatch `engine.py`'s own comment on `block_rate_ev` already flags;
using a RATIO relative to the same wrong-basis league average cancels the mismatch out, same
technique §2f already used. Measured on real data: 1,312 games, league block rate 33.77%, 14.19
blocks/game/team, mean index 0.9999 (confirms normalization). Real spread: PHI (1.102x)/VGK
(1.098x)/MTL (1.091x) block the most; NSH (0.867x)/CHI (0.869x) the least — ~27% top-to-bottom.
**No strength-state split exists in the source data** — one combined index is applied to all three
of the engine's existing strength-state constants; their structural difference (higher on the PK,
lower on the PP) stays intact, only the per-team scale on top is new.

**Wiring**: `engine.py` reads `st_home.get("block_rate_index", 1.0)`/`st_away.get(...)` once per
game, multiplies the BLOCKING team's own probability right before the block roll, clamped to
`[0.02, 0.95]`. `scripts/build_nhl_special_teams_artifact.py` writes `block_rate_index` as a third
additional column on the same `team_special_teams_{season}.csv`, sharing ONE read pass over the
`boxscore` cache with the §2f shot-index computation.

**Verified the league-wide average did NOT shift**: 200 real round-robin team pairings, neutral
index → 24.635 avg total blocks/game; real per-team index → 24.475 — a ~0.6% difference, noise-level,
confirming the per-team layer redistributes blocks between teams without moving the league aggregate.

**What this does NOT do — stated plainly**: does NOT calibrate the ABSOLUTE block rate to truth.
Simulated per-team average (~12.2-12.3/game) sits below the real measured 14.19/game — the base
constants (0.45/0.55/0.35) remain the vendor's original, uncalibrated guess. Only relative per-team
differentiation was built, matching this task's scope.

**Reachability tested**: `test_special_teams_block_rate_index_actually_changes_block_volume` —
`block_rate_index=1.8` produces measurably more HOME blocks than `0.3`, 80 seeded runs.

**This closes the special-teams track this session set out to build**: PP/PK goal conversion
(per-team + league calibration, §2b/§2d), PP/PK shot volume (per-team + league calibration,
§2e/§2f), blocked-shot tendency (per-team + league calibration, §2g/§2h). What remains open in
special teams: strength-state-specific per-team blocking (no data source distinguishes it) and a
true shot-attempt basis for the block roll itself (§2h).

**Checklist bug found and fixed while verifying this section**: `nhl_sim_input_checklist.py`'s
population-counting loop checked a hardcoded `("pp_pct", "pk_pct", "committed_per_game")` tuple
that was never updated when §2f added `pp_shot_index`/`pk_shot_index_allowed` to the AST-derived
`special_teams_consumed_keys()` — so the checklist reported all three (and now `block_rate_index`)
as **0.0% FAIL, "consumed but NEVER populated"**, while `load_team_special_teams_map` was directly
confirmed (via a standalone Python check against this checkout's real data) to populate all six
keys on every team-side. Fixed by driving the population loop off the same
`special_teams_consumed_keys()` function the report table already uses, so the two can no longer
drift apart. Post-fix, all 6 keys correctly report 100% and the alarm count returns to 9. A live
instance of `model_engine_standard.md`'s own warning about hardcoded key lists vs. AST walks —
caught in the checklist meant to catch it elsewhere.

---

## 2h. Absolute block-rate calibration — the base constants, not just the per-team layer

Full report: `docs/reports/hockeysim_absolute_block_rate_cal_report.md`. §2g built PER-TEAM
relative differentiation but explicitly left `block_rate_ev`/`block_rate_pk`/`block_rate_pp_def`'s
ABSOLUTE level uncalibrated — the vendor's shipped 0.45/0.55/0.35 had never been checked against a
real block rate. This pass closes that.

**Why a single shared scale, not three independent fits**: the truth source has exactly ONE
league-wide target (blocked shots carry no strength-state breakdown in the `boxscore` payload at
all), so fitting 3 constants independently would be underdetermined. `scripts/calibrate_nhl_block_rate.py`
fits ONE proportional scale factor applied uniformly to all three, preserving their existing
structural ratio (higher on the PK, lower on the PP) — the only degree of freedom the data supports.

**Truth target**: `blocks_per_game(team) = 14.1905` (1,312 games, same figure §2g already
established). Fit with `block_rate_index` held NEUTRAL (isolates the absolute-level fit from the
per-team layer, mechanism-vs-estimator), converged in 5 proportional-correction iterations:
13.2613 → 14.2800 → 14.1821 → 14.1958 → 14.1975 against target 14.1905.

**Result**: `block_scale = 1.0631` (a modest ~6.3% correction) → `block_rate_ev=0.4784`,
`block_rate_pk=0.5847`, `block_rate_pp_def=0.3721`.

**Verified twice**, fresh seed, full 992-pairing round-robin (19,840 games each): 14.2606 with
`block_rate_index` still neutral, 14.2583 with the REAL per-team index active — both ~0.5% above
target, confirming (again, now against the calibrated base) that the per-team layer doesn't disturb
the league-wide level.

**Locked in a test**: `test_special_teams_cal_production_default_carries_the_calibration` now
asserts `blocks_ev_rate=0.4784`/`blocks_pk_rate=0.5847`/`blocks_pp_def_rate=0.3721` instead of the
old neutral 0.45/0.55/0.35.

**What remains open**: the vendor's ORIGINAL EV:PK:PP-def ratio itself (0.45:0.55:0.35) was never
independently validated — this pass preserves it, not re-derives it, because no strength-state-split
truth source exists to fit it against. The engine's block roll also still runs on the SOG-equivalent
"shot" event population, not a true shot-attempt basis — this calibrates the compensating constant
to match real output, it doesn't remove the underlying basis mismatch itself.

---

## 2i. A real xG (expected goals) model — the last genuinely-absent gap from §5

Full report: `docs/reports/hockeysim_xg_model_report.md`. `xgf_per_60`/`xga_per_60` had a reader
(`loaders.load_team_xg_map`, wired into `build_team_features`/`build_game_features` from a PRIOR
session) but NO PRODUCER — `projection.py`'s `_offense_rate`/`_defense_rate` silently fell back to
`goals_per_60`, then the league baseline, on every team, every game. This builds a real producer.

**New data, not a new reader**: neither the `landing` feed nor the `boxscore` feed carries shot
location. `play-by-play` (`/v1/gamecenter/{id}/play-by-play`) does — every Fenwick event carries
`xCoord`/`yCoord`, `shotType`, `situationCode`. `NhlWebIngestClient.play_by_play()` (new) +
`scripts/fetch_nhl_playbyplay_cache.py` (new) bulk-fetched all 1,312 regular-season games (1,307
new fetches, 0 failures, ~492s).

**Fenwick, not Corsi**: `blocked-shot` events record the BLOCK coordinate, not the shooter's
release point — using it for distance/angle would systematically understate distance. Every public
NHL xG model fits on Fenwick (SOG + missed + goals) for exactly this reason; so does this one.

**`sign(xCoord)`, not `homeTeamDefendingSide` bookkeeping**: a shot recorded in the offensive zone
has coordinates naturally closer to the net it's attacking, so `sign(xCoord)` identifies the
attacked net directly — the same standard shortcut public NHL xG models use, trading a little
noise on rare neutral-zone attempts for a much simpler implementation.

**Model**: `sklearn.linear_model.LogisticRegression` on distance, angle, shot type (one-hot),
strength state (one-hot, from `situationCode`), is-rebound (same-team Fenwick attempt within 3s),
is-empty-net. **Team identity is deliberately NOT a feature** — the model cannot overfit to a
specific team's shooting/goaltending quality, so scoring every shot with the model fit on the FULL
dataset is safe for the team-level aggregation; the holdout split exists only to validate
calibration.

**Holdout validation** (games the model never trained on, 262 games / 22,218 shots): **AUC=0.7450**
(in line with public models on a comparable feature set), **Brier=0.0667** (beats the naive
base-rate baseline ≈0.0685), and a calibration table monotonic and closely tracked across all 10
deciles of predicted probability — see the full report for the table.

**Aggregation**: league avg xGF/60 = xGA/60 = **3.1826**, within ~1.8% of the real, truth-calibrated
`league_baseline_goals_per_60` (3.1269) this codebase already uses — the expected structural
property of a well-fit logistic model's mean prediction matching its mean outcome. Real per-team
spread: CAR (3.83)/COL (3.69) highest, CHI (2.73)/SEA (2.80) lowest — matches known 2025-26 team
strength (Carolina/Colorado strong possession teams, Chicago rebuilding), external validation in
the same style as EDM's independently-measured best PP (§2d/§2f).

**Stated plainly, not glossed over**: `is_rebound` (−0.1269) and the tip-in/deflected shot-type
coefficients came out NEGATIVE — the opposite sign hockey intuition predicts. A real, measured
finding, not adjusted to match a prior; flagged as an open question in the full report, not chased
further this pass.

**Checklist impact**: alarm count drops from 9 to **7**, the lowest measured this session.

**What remains open**: no rush-shot feature, no per-shooter/goaltender talent layer (deliberately —
would need a genuinely new signal, not this shot-quality base), and not independently re-verified
against the goal/shot-multiplier calibrations (§2d-§2h) since `xgf_per_60`/`xga_per_60` feed a
different code path (the pregame projection / main board) than those calibrations tuned (the
possession/segment props sim) — see §3's "main-board / props-engine split" note.

---

## 2j. Team rates (`shots_per_60`/`blocks_per_60`/`penalties_per_60`/`faceoff_win_pct`) — 2 of 4 are a confirmed dead gate

Full report: `docs/reports/hockeysim_team_rates_report.md`. Closes 4 of §5's remaining
genuinely-absent `HockeyTeamFeatures` fields, with an important qualifier stated up front.

**Built**: `historical_truth/team_game_rates.py` parses `shots_per_60`/`blocks_per_60` from the
`boxscore` cache (SOG straight from the league's own recorded field; blocks reuse §2g's parser) and
`faceoff_win_pct` from the `play-by-play` cache's `faceoff` events (`eventOwnerTeamId` is the
WINNING team — verified against `rosterSpots`, 0/70 mismatches in a spot-check). Run against all
1,312 games: 1,312/1,312 joined. League avg blocks/60 = **14.19**, an EXACT match to §2g/§2h's
independently-computed truth — cross-validates two separately-built modules. League avg
faceoff_win_pct = 0.5001 (structural sanity check: every faceoff has one winner, one loser).
Real spread: COL/CAR lead shots/60 — the SAME two teams that independently led xGF/60 in §2i.

**`penalties_per_60` has no new producer** — it reuses `special_teams_builder.py`'s already-computed
`committed_per_game` (the exact same quantity), which just wasn't being read into this SEPARATE
top-level field before. Fixed in `loaders.py`.

**The dead-gate finding, stated plainly rather than glossed over**: `player_props.py`'s
`_team_rates()` reads all 4 fields into `TeamRates` (satisfying the checklist's population check),
but `engine.py` only reads `TeamRates.shots_per_60`/`.goals_per_60`/`.faceoff_win_pct`.
**`.blocks_per_60` and `.penalties_per_60` are never read anywhere in `engine.py`.** Proven, not
assumed: `TeamRatesReachabilityTest` shows an extreme swing on `shots_per_60`/`faceoff_win_pct`
producing a clear directional SOG difference, while the SAME extreme swing on
`blocks_per_60`/`penalties_per_60` (fixed seed) produces a **byte-identical** projection set — the
same class of bug as basketball's `#467`, present from the start rather than introduced later.

**Why this wasn't force-fixed with a new consumption mechanism**: block generation is already fully
modeled by the truth-calibrated `block_rate_ev`/`pk`/`pp_def` + `block_rate_index` (§2g/§2h) — a
strictly more granular, per-shot-event mechanism. Bolting `blocks_per_60` onto it risks exactly the
double-counting §4.4 warns against. `penalties_per_60` has no market or mechanism to drive at all
(no PIM market exists). Both would be real design decisions, not population fixes — flagged
explicitly as an open follow-up, not silently marked "fixed."

**Checklist impact**: alarm count drops from 7 to **3** (the checklist can't see the dead-gate
distinction — it only traces one hop, `HockeyTeamFeatures` field → populated boolean, the same
scope every field is measured at). Remaining 3: player-level usage weights (`shot_weight`/
`goal_weight`/`block_weight`), a distinct, still-open gap.

---

## 2k. Player usage weights (`shot_weight`/`goal_weight`/`block_weight`) — checklist reaches PASS

Full report: `docs/reports/hockeysim_player_weights_report.md`. Closes the last 3 genuinely-absent
inputs §5 tracked — `scripts/nhl_sim_input_checklist.py` now reports a full **PASS**.

**Unlike §2j's dead gate, these were ALREADY reachable**: `engine.py`'s `_weighted_choice` reads
all three directly to decide which on-ice skater gets credited for a shot/goal/block, with a
documented position/TOI heuristic fallback when absent (forwards get more shot-weight, defensemen
more block-weight) — reasonable, but unable to differentiate a top-line sniper from a 4th-line
grinder at the same position/TOI. This pass supplies real, individually differentiated data on top
of that existing heuristic (which remains the fallback for anyone below the games floor).

**The new signal**: `historical_truth/player_game_rates.py` parses the `boxscore` cache's
per-skater `sog`/`goals`/`blockedShots` (already bulk-fetched, no new fetch) into a per-game
average per player — exactly the unit `engine.py`'s own fallback-heuristic comment specifies.
Floor at 5 games (`MIN_GAMES_FOR_PLAYER_WEIGHT`), below which a player is omitted, not guessed.
Run against all 1,312 games: 47,231 skater-game records, **828 players rated**. Real spread, top
`shot_weight`: N. MacKinnon (4.375 shots/game), A. Matthews, C. Gauthier, J. Hughes, C. McDavid —
real, well-known elite scorers, the same style of external validation every per-team signal this
session built has passed.

**Wiring**: `loaders.load_player_rates_map()` (new — the first per-PLAYER, not per-team, reader in
this package, keyed by integer `player_id`) + `build_player_features`'s new `player_rates_map`
parameter, threaded through `build_game_features`/`build_slate_features`. All three fields stay
`Optional[float]` (unlike the team-rate fields) — `None` is the CORRECT "no data" signal, since
`engine.py` already handles it via the heuristic.

**Reachability tested at the MECHANISM level** (these were already wired, so population-reachability
alone proves nothing new): 3 new tests in `test_hockeysim_engine.py`, each holding TOI/position
identical between two synthetic players and varying ONLY the field under test — `shot_weight=8.0`
vs `0.2` (more shots credited), `block_weight=6.0` vs `0.1` (more blocks credited), and
`goal_weight=3.6` vs `0.2` with `shot_weight` held FIXED (more goals per shot — the finishing-rate
mechanism, not attribution volume). All three pass.

**Checklist impact**: alarm count drops from 3 to **0**. Full PASS.

**What remains open**: no goaltender-specific weight (untouched — not part of the genuinely-absent
list); the position/TOI heuristic fallback is unchanged for anyone below the 5-game floor
(intentional); not cross-validated against real per-player prop-market outcomes (a distinct, larger
backtest project, matching the scope boundary §6's Elo backtest drew for its own mechanism).

---

## 2l. `blocks_per_60`/`penalties_per_60` — the dead gate, REMOVED rather than force-fixed

Full report: `docs/reports/hockeysim_team_rates_report.md` (§2j) flagged this as an explicit open
decision — build a real consumption mechanism, or delete the two dead fields. This closes it:
**deleted**, after confirming neither field could gain a legitimate consumer without duplicating
data that is already live through a different, already-verified path.

**Why removal, not a new mechanism — checked, not assumed.** Reading `engine.py`'s actual segment-
generation code (`engine.py:715-719`) confirms `special_teams`'s `committed_per_game` (real,
truth-calibrated, §2b) is *already* what drives how much PP/PK time each game generates — the exact
quantity a `penalties_per_60` mechanism would need to drive. Wiring `TeamRates.penalties_per_60`
into anything would have meant a SECOND signal for the same real-world quantity, double-counted
against the first. Block volume has the same shape: it is entirely governed by the truth-calibrated
per-shot `block_rate_ev`/`pk`/`pp_def` + `block_rate_index` mechanism (§2g/§2h) — no team-level rate
input exists anywhere in that code path, and adding one would duplicate what the per-shot
probability already determines. Neither field had a place left to legitimately plug into.

**What was deleted, traced through the whole chain, not just the dataclass fields**:
- `HockeyTeamFeatures.blocks_per_60`/`.penalties_per_60` and `TeamRates.blocks_per_60`/
  `.penalties_per_60` (`contracts.py`, `models.py`) — the two dead fields themselves.
- `player_props._team_rates()` — stopped constructing `TeamRates` with either kwarg.
- `loaders.build_team_features()` — stopped wiring `rates_map["blocks_per_60"]` and
  `special_teams["committed_per_game"]` into the now-nonexistent `penalties_per_60` field.
- `historical_truth/team_game_rates.py` — `blocks_per_60` computation removed entirely (was reusing
  `boxscore_block_rate.parse_boxscore_block_rate`, which stays alive and consumed for §2g's
  per-team `block_rate_index` — only THIS module's now-redundant reuse of it was cut).
  `parse_boxscore_sog_and_blocks` renamed `parse_boxscore_sog` (it only parses SOG now).
- `scripts/build_nhl_team_rates_artifact.py` — `blocks_per_60` CSV column dropped from new writes.
  The reader (`load_team_rates_map`) tolerates an old CSV that still has the column — reads past it,
  never resurrects it.
- Three calibration scripts (`calibrate_nhl_block_rate.py`, `calibrate_nhl_special_teams_shot_mult.py`,
  `calibrate_nhl_special_teams_goal_mult.py`) — dropped the now-invalid `blocks_per_60=12.0,
  penalties_per_60=3.0` kwargs from their `TeamRates(...)` fixture construction.
- Tests: the two "dead gate, byte-identical output" reachability tests (`test_hockeysim_props.py`)
  are replaced with regression tests asserting the fields are absent from
  `__dataclass_fields__` — the ORIGINAL reachability proof is what justified the deletion, not
  discarded, just superseded by a cheaper guard now that there's no field left to test reachability
  of. `test_hockeysim_team_game_rates.py` and `test_hockeysim_loaders.py` updated to match the
  trimmed schema; one new test confirms an OLD CSV with a leftover `blocks_per_60` column still
  loads cleanly (backward-compatible read, not a hard schema break for anyone still holding an
  older artifact on disk).

**Verified**: `nhl_sim_input_checklist.py` — still a full PASS; the `--- HockeyTeamFeatures ---`
section is now EMPTY (nothing left to report: every field it used to track is either removed or
100% reachable). 323 hockeysim/nhl tests pass (net count unchanged — 2 dead-gate tests replaced by
2 regression tests, 1 new backward-compat test, 1 fewer parsing test now that blocks are out of
this module's scope). `scripts/build_nhl_team_rates_artifact.py` re-run against the full 1,312-game
cache to confirm the trimmed CSV schema writes cleanly.

**Precedent set for future dead-gate findings**: per `model_engine_standard.md`'s own discipline,
"presence is not reachability" cuts both ways — a field can fail that test in two directions.
Either build the missing consumer (this session's default, for everything else in §2j/§2k), or, when
building one would duplicate an already-live signal, delete the dead field entirely rather than
leave it populated-and-silently-unused. Leaving it "populated but confirmed dead" is worse than
either: it looks fixed to anything checking population alone (exactly what the checklist's own
1-hop scope cannot see, §2j) while doing nothing.

---

## 3. Input provenance — where each input is produced and applied

| input | produced by | applied in | population `[this checkout]` |
|---|---|---|---|
| `xgf_per_60` / `xga_per_60` | **NEW**: `historical_truth/shot_xg_model.py` + `scripts/build_nhl_xg_artifact.py`, a real logistic shot-quality model fit on 112,888 play-by-play Fenwick shots (§2i) | `projection._offense_rate` / `_defense_rate` (falls back to `goals_per_60`, then league baseline) | 0% → 100% after §2i; the last genuinely-absent input from this row's original §5 listing |
| `elo_rating` | **NEW**: `historical_truth/elo_builder.py` + `scripts/build_nhl_elo_artifact.py`, from 1,312 cached real games | `projection._elo_win_prob`, gated at `elo_blend_weight` (default `0.0`) | 100% after the fix (§4); blend deliberately still off |
| `goals_per_60` | `apply_projection` back-fills from `proj_home_goals`/`proj_away_goals` (**NEW** this session) | `player_props.py`'s `TeamRates` construction, then `engine.py` (shots/goals allocation, saves) | was 0% (stuck at the stale `2.9` default) → 100%, matchup-adjusted, after the fix |
| `shots_per_60`, `faceoff_win_pct` | **NEW**: `historical_truth/team_game_rates.py` + `scripts/build_nhl_team_rates_artifact.py`, from boxscore + play-by-play (§2j) | same `TeamRates` construction, direct passthrough (`player_props.py:43-48`) | 0% → 100% after §2j; REACHABLE (engine.py reads both) |
| `blocks_per_60`, `penalties_per_60` | **REMOVED** (§2l) — were populated (§2j) then proven a confirmed dead gate (`engine.py` never read either) and deleted from `HockeyTeamFeatures`/`TeamRates` entirely, traced through every reference site, rather than force-wired into a mechanism that would have duplicated already-live real data | n/a — field no longer exists | n/a — this row exists only so the deletion is discoverable from the provenance table, not a live input |
| `shot_weight`, `goal_weight`, `block_weight` (player) | **NEW**: `historical_truth/player_game_rates.py` + `scripts/build_nhl_player_rates_artifact.py`, from boxscore per-skater stats, 828 players rated (§2k) | player-level allocation weighting + finishing-rate multiplier inside `engine.py`'s `_weighted_choice` | 0% → 100% (>= 5 games) after §2k; ALREADY reachable pre-fix (position/TOI heuristic), now real per-player data on top |
| `special_teams` (dict; `pp_pct`/`pk_pct`/`committed_per_game`, GOAL conversion) | **NEW**: `historical_truth/special_teams_builder.py` + `scripts/build_nhl_special_teams_artifact.py`, from real PP goals + parsed penalty data | `player_props.py:90-91` → `st_home`/`st_away` → `engine.py:677-678,973-980` (PP/PK goal-rate adjustment) | 0% → 100% after the fix (§4) — see §2b for the correction to what this row used to say |
| `special_teams` (dict; `pp_shot_index`/`pk_shot_index_allowed`, SHOT volume — §2f) | **NEW**: `historical_truth/boxscore_shot_strength.py`, from boxscore shot splits + opportunity counts | same `st_home`/`st_away` dict, different keys → `engine.py`'s `pp_mult_shots`/`pk_mult_shots` application | 0% → 100% after §2f; a genuinely new per-team signal, not a calibration of an existing one |
| `special_teams` (dict; `block_rate_index`, BLOCK tendency — §2g) | **NEW**: `historical_truth/boxscore_block_rate.py`, from boxscore blocked-shot + SOG counts | same `st_home`/`st_away` dict → `engine.py`'s `p_blk_home`/`p_blk_away` scaling before the block roll | 0% → 100% after §2g; a genuinely new per-team signal, not a calibration of an existing one |
| `special_teams_cal` (7 keys — separate parameter, see §2b/§2c/§2d/§2e/§2h) | **NEW**: `SimConfig`'s 7 new fields, resolved via `build_nhl_sim_config` and mapped by `player_props._special_teams_cal` | `engine.py`'s multiplier/block-rate adjustments, 7 `.get()` sites | reachable (§2c); `pk_goal_cal_mult=0.4645` (§2d), `pp_shot_cal_mult=0.9108`, `pk_shot_cal_mult=0.3369` (§2e), and all 3 `block_rate_*` keys (§2h, 0.4784/0.5847/0.3721) truth-calibrated — only `pp_goal_cal_mult` still at its neutral default (measured statistically indistinguishable from 1.0) |
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
| `sh_goals_home`/`sh_goals_away` on `HistoricalGameRecord` + `TruthMetrics.sh_goal_share` — new truth metric, parsed from `strength == "sh"` goals | built, tested (isolated fixture; existing `_landing()` fixture untouched) | feeds the calibration below; no new fetch, same 1,312-game cache |
| `scripts/calibrate_nhl_special_teams_goal_mult.py` + calibrated `pk_goal_cal_mult=0.4645` (§2d) | built, run, applied to `NHL_CALIBRATION_PROFILE_DEFAULT`, locked in a test | reachable by default; a REAL behavior change (shorthanded-goal rate roughly halved to match truth) |
| `scripts/fetch_nhl_boxscore_cache.py` — bulk-fetched the `boxscore` endpoint (1,297 games, 0 failures) | built, run | new substrate; only 11/1,312 games were cached before |
| `historical_truth/boxscore_shot_strength.py` — parses PP/PK/EV shot splits, new `pp_shot_share`/`sh_shot_share` truth targets | built, tested (9 tests), cross-validated against the independent `landing` feed's SOG count | feeds the calibration below |
| `scripts/calibrate_nhl_special_teams_shot_mult.py` + calibrated `pp_shot_cal_mult=0.9108`/`pk_shot_cal_mult=0.3369` (§2e) | built, run (joint alternating fit + full round-robin pairing, after finding and fixing a sequential-fit interaction bug), applied, locked in tests | reachable by default; a REAL behavior change (shot volume during PP/PK segments now matches truth) |
| `historical_truth.boxscore_shot_strength.compute_team_shot_rate_index` + `pp_shot_index`/`pk_shot_index_allowed` wired into `engine.py` (§2f) — a NEW per-team mechanism, not a calibration | built, tested (reachability + loader + unit tests), verified the existing global calibration did not need re-fitting | reachable by default; a REAL behavior change (per-team shot-volume variation, previously nonexistent) |
| `historical_truth.boxscore_block_rate.compute_team_block_rate_index` + `block_rate_index` wired into `engine.py` (§2g) — a NEW per-team mechanism, closing the last special-teams gap | built, tested (reachability + loader + unit tests), verified the league-wide average block count did not shift (24.635 neutral vs 24.475 real-indexed, 200 pairings) | reachable by default; a REAL behavior change (per-team block-volume variation, previously nonexistent) |
| `scripts/calibrate_nhl_block_rate.py` + calibrated `block_rate_ev=0.4784`/`block_rate_pk=0.5847`/`block_rate_pp_def=0.3721` (§2h) — a single shared scale factor, the only degree of freedom 1 league-wide target supports for 3 constants | built, run (proportional-correction fit, 5 iterations), verified twice on the full round-robin (14.2606 neutral-index / 14.2583 real-index vs 14.1905 target), locked in a test | reachable by default; a REAL behavior change (overall block volume ~6.3% higher, matching truth instead of an unmeasured vendor guess) |
| `NhlWebIngestClient.play_by_play()` + `scripts/fetch_nhl_playbyplay_cache.py` — bulk-fetched 1,312 real games (1,307 new, 0 failures) | built, run | new substrate; the play-by-play endpoint had never been fetched before this session at all |
| `historical_truth/shot_xg_model.py` + `scripts/build_nhl_xg_artifact.py` — a real logistic xG model (distance/angle/shot-type/strength/rebound/empty-net), fit on 112,888 Fenwick shots (§2i) | built, run, holdout-validated (AUC=0.7450, Brier=0.0667, calibration table tracked across all 10 deciles), tested (21 new unit + loader tests) | reachable by default; closes §5's original listing for `xgf_per_60`/`xga_per_60` |
| `historical_truth/team_game_rates.py` + `scripts/build_nhl_team_rates_artifact.py` — `shots_per_60`/`faceoff_win_pct` from boxscore + play-by-play (§2j) | built, run (1,312/1,312 games joined), tested | reachable by default; a REAL behavior change |
| `blocks_per_60`/`penalties_per_60` — REMOVED (§2l) after §2j proved them a confirmed dead gate | deleted from `HockeyTeamFeatures`/`TeamRates` and every reference site (loaders, `player_props`, the producer script, 3 calibration scripts), traced through the whole chain, not just the dataclass fields | `nhl_sim_input_checklist.py`'s `--- HockeyTeamFeatures ---` section is now EMPTY — nothing left unreachable to report |
| `historical_truth/player_game_rates.py` + `scripts/build_nhl_player_rates_artifact.py` — real per-player `shot_weight`/`goal_weight`/`block_weight`, 828 players rated from 47,231 skater-game records (§2k) | built, run, tested (15 parser + 6 loader + 3 mechanism-level reachability tests), external sanity check (MacKinnon/Matthews/Hughes/McDavid top the shot-volume list) | ALREADY reachable pre-fix (engine.py's own position/TOI heuristic); this replaces that heuristic with real per-player data, proven at the mechanism level, not just population |
| `scripts/nhl_sim_input_checklist.py` — the gating checklist `model_engine_standard.md` §1 requires; corrected mid-session per §2b, updated again for §2c | built, **exits 0 — full PASS** (down from 16 alarms at the start of this session) | not yet wired into `/preflight` or `migration_gate.py` — next step for whoever picks this up; also does not (and structurally cannot, at its current 1-hop scope) distinguish "populated" from "reachable" — see §2j |

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

## 5. Genuinely absent (not merely unfed) — 0 alarms, `scripts/nhl_sim_input_checklist.py` reports a full PASS

`[measured against this checkout: 9 mirrored dates 2026-06-02..2026-07-09,
10 team-sides, 297 players — per §7, UNMEASURED against Render, not 0%,
until checked there]`

Every field this document originally tracked as genuinely absent now has a real producer:
`elo_rating` (§4), `goals_per_60` staleness (§4), `special_teams`'s 3 real keys (§2b/§4),
`special_teams_cal`'s 7 keys — wired (§2c) and truth-calibrated except `pp_goal_multiplier`
(deliberately neutral, §2d) — `xgf_per_60`/`xga_per_60` (§2i), `shots_per_60`/`faceoff_win_pct`
(§2j), and the 3 player usage weights (§2k, closing this section out). `blocks_per_60`/
`penalties_per_60` (2 of the original 4 team-rate fields) were populated (§2j), proven a
**confirmed dead gate**, and then REMOVED entirely (§2l) rather than left populated-but-unreachable
— the checklist's own population check cannot see the dead-gate distinction, only §2j's dedicated
mechanism-level reachability tests could, which is exactly why the fields don't exist to check
anymore rather than why the checklist grew a new exception.

**Nothing in this section is repeated here** — see the referenced sections for what was built, how
it was verified, and what (§2h's unvalidated EV:PK:PP-def ratio; §2i's rebound/tip-in sign anomaly;
the team-rate/player-weight producers' small-sample floors) is explicitly still open within each.

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
now-real xG signal (§2i) are the natural next attempts, not re-sweeping this
same formulation.

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

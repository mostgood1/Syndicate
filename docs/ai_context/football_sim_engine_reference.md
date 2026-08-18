# The Football Sim Engine — smartsim2 (NFL + NCAAF) reference

> Written 2026-08-18, lane `football-model-owner`. This is football's copy of
> what `mlb_sim_engine_reference.md` is for MLB: the worked example that
> `docs/ai_context/model_engine_standard.md` §2 makes mandatory.
>
> **Read this before changing anything under `syndicate/features/football/`.**
> The single most important fact in it is in §3, and it is not visible from any
> test, log line, or UI surface.

---

## 0. The headline, measured

**The engine has a fully-built advanced-analytics intake. Every production
entrypoint passes it nothing.**

`scripts/football_sim_input_checklist.py` (this engine's gate, §6) reads the
engine's own call sites structurally and finds **9 feature blocks / 65 keys**
that `drive_priors.py` consumes. It then reads every construction site of
`SmartSim2SimulationInput`:

| entrypoint | kind | passes `feature_generation_payload`? |
|---|---|---|
| `scripts/generate_smartsim2_nfl_projections.py` | **production** | **NO** |
| `scripts/generate_smartsim2_nfl_preseason_projections.py` | **production** | **NO** |
| `scripts/generate_smartsim2_ncaaf_projections.py` | **production** | **NO** |
| `scripts/backtest_nfl_preseason_projection.py` | analysis | no |
| `scripts/analyze_nfl_injury_adjustment_sides.py` | analysis | no |
| `.../smartsim2/calibration/baseline_audit.py` | analysis | **passes one, and it is INERT** |

**0 of 3 production entrypoints.** So `build_drive_priors` receives `payload =
{}` on every NFL and NCAAF game the platform serves, every one of the 65 keys
falls to a neutral default, and the only signal reaching the Monte Carlo is the
four rating scalars (`home/away_offense_rating`, `home/away_defense_rating`) plus
`pace_seconds_per_play`'s hardcoded 24.0.

### It is not a small effect

Measured 2026-08-18 by running `build_drive_priors` with an empty payload (what
production does) against the same game with the payload the feature layer can
already supply — **21 of 21 drive-prior fields move**:

| prior | production (empty) | with payload | delta |
|---|---|---|---|
| `offense_index` | 0.560 | 0.785 | +0.225 |
| `defense_index` | 0.475 | 0.584 | +0.109 |
| `pace_index` | 0.400 | 0.150 | −0.250 |
| `returning_production_index` | **0.500** | 0.720 | +0.220 |
| `coach_continuity_index` | **0.500** | 0.900 | +0.400 |
| `player_usage_index` | **0.250** | 0.543 | +0.293 |
| `market_prior_index` | **0.500** | 0.368 | −0.133 |
| `transfer_volatility_index` | **0.200** | 0.300 | +0.100 |
| `drive_success_probability` | 0.349 | 0.410 | +0.060 |
| `touchdown_probability` | 0.183 | 0.223 | +0.040 |
| `expected_clock_seconds` | 150.96 | 175.47 | +24.51 |

The bolded values are the hardcoded neutral constants in `drive_priors.py`.
**Every NFL and NCAAF game in production carries those identical numbers.**

At the score level, 400 seeds per arm on one game through `simulate_game` with
`NFL_CALIBRATION_PROFILE`:

| | empty (production) | with payload | delta |
|---|---|---|---|
| margin | 1.667 | 0.542 | **−1.125** |
| total | 48.428 | 46.742 | **−1.685** |
| home win% | 54.25% | 47.75% | **−6.50 pts** |

A 6.5-point win-probability swing is far larger than any edge this platform
claims to find.

### The one payload that IS passed is inert — and it nearly fooled this gate

`calibration/baseline_audit.py:287` *does* pass a `feature_generation_payload`.
It contains `{game_id, season, week, market_total, market_spread_home}` — and
**not one of those is a key the engine reads.** `_extract_block` wants a nested
block named `market_features`/`market`/`betting`; a flat `market_total` is
invisible to it.

The first version of the checklist asked only *"is a payload passed"* and
reported this site as **wired**. It now checks the payload's literal keys against
the consumed block names and reports `INERT PAYLOAD`. **A gate that asks about
presence rather than reachability green-lights exactly the half-fix it exists to
catch** — and the half-fix here is the likely shape of a careless wiring pass.

### Read §5 before "fixing" this

The delta above is **not** the improvement available from wiring the payload in.
The NFL profile is a *frozen calibrated* profile fit with the payload empty, so
wiring it in is adding mechanisms to a calibrated engine. See §5.

---

## 1. There are TWO football models and they are unrelated

This is the fact that makes every other football question confusing until you
know it.

**Track A — `FootballSimulationAdapter`** (`syndicate/features/football/adapters.py`)
- `load_features` (`:245`, `:256`) → `build_football_simulation_input`
  (`features/loaders.py:526`) → `FootballGameFeatures` carrying the full advanced
  stack (nflverse EPA, rbsdm success/explosive/red-zone, market, pace, 19,400
  player-usage rows on a 2025 wk1 load).
- `simulate_games` (`:265`) → `_game_projection` (`:110`) is a **closed-form
  linear formula with hardcoded coefficients** (`epa_component * 4.5`,
  `success_component * 8.0`, …). **It never calls smartsim2.** No Monte Carlo, no
  drives.
- Callers: `feature_lift_analysis.py`, `player_prop_lift_analysis.py`,
  `season_validation.py`, and tests. **All offline analysis. Nothing user-facing.**
- `NflAdapter` / `NcaafAdapter` (`sim_engine/nfl_adapter.py`, `ncaaf_adapter.py`)
  have **zero non-self callers**.

**Track B — smartsim2** (`sim_engine/smartsim2/`)
- The real Monte Carlo drive engine. Produces every projection a user sees.
- Fed by the three `generate_smartsim2_*` scripts, which build
  `SmartSim2SimulationInput` **by hand from four scalars**.

**The two tracks never meet.** Track A owns the features; Track B owns the
users. `drive_priors._extract_block` accepts block names (`team_metrics`,
`advanced_metrics`, `market_features`, `pace_features`) that are *exactly* the
field names Track A produces — the seam was designed and never connected.

---

## 2. The pipeline trace (§2 of the standard — file:line at every hop)

### NFL regular season
```
scripts/run_refresh_worker.py
  _SEASON_PROJECTION_SPORTS = ("nfl", "ncaaf")                        (:2321)
  gated by SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN            (:2324)
      -- ABSENT env => DISABLED. Fires 21:00Z = 16:00 CDT.
  _season_projection_script_args -> generate_smartsim2_<sport>_projections.py (:2370-2372)
  _SEASON_PROJECTION_MAX_RUNTIME_SECONDS = 45*60                      (:2375)
    -> scripts/generate_smartsim2_nfl_projections.py
         team_rating() from data/nfl_source/pbp_<season>.csv  (nflverse EPA)
         adjust_team_rating_for_injuries()                            (:402-409)
         SmartSim2SimulationInput(...)   <-- NO feature_generation_payload (:414)
         simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)    (:423)
           -> smartsim2/game_simulator.py:simulate_game               (:67)
             -> smartsim2/drive_simulator.py:simulate_drive           (:195)
               -> build_drive_priors(simulation_input, ...)           (:204)
                 -> smartsim2/drive_priors.py:build_drive_priors      (:230)
                      payload = _copy_mapping(source.feature_generation_payload)  (:232)
                      ^^^ {} in production. 9 blocks / 65 keys default. ^^^
         write_projection_artifact(...)                               (:515)
   writes: data/nfl_source/smartsim2_projections_<season>_wk<week>.csv
   read by: syndicate/features/nfl/cards.py:483, :777  (read_projection_artifact)
            syndicate/features/nfl/picks.py, archive.py,
            syndicate/blueprints/ask_the_syndicate_data.py, ops.py
```

### NFL preseason (separate script, separate artifact — live NOW)
```
scripts/run_refresh_worker.py:_launch_autorun_preseason_projections   (:2873)
  _preseason_projection_script_args -> generate_smartsim2_nfl_preseason_projections.py (:2868)
    -> shrunk_rating(...)  nudges ratings toward league-neutral by nonstarter share
       SmartSim2SimulationInput(...)  <-- NO payload                  (:165)
       simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)          (:174)
   writes: data/nfl_source/smartsim2_preseason_projections_<season>_wk<week>.csv
            (via nfl_artifact_output_root(), :2860)
   read by: syndicate/features/nfl/preseason_cards.py, preseason_projection.py
```

### NCAAF
```
same autorun tuple (:2321) -> generate_smartsim2_ncaaf_projections.py
  week from syndicate/features/ncaaf/sources.py:ncaaf_target_week     (:2343-2346)
  offense_defense_rating(team, ppa_index)   <-- CFBD PPA, not EPA
  SmartSim2SimulationInput(...)  <-- NO payload                       (:199)
  simulate_game(sim_input, profile=NCAAF_CALIBRATION_PROFILE)         (:208)
  write_projection_artifact(...)                                      (:306)
   writes: <data_root>/ncaaf_source/data/smartsim2_projections_<season>_wk<week>.csv (:2367)
   read by: syndicate/features/ncaaf/cards.py:34
```

**Note the artifact-root asymmetry**: NFL resolves through
`nfl_artifact_output_root()`; NCAAF hardcodes `data_root / "ncaaf_source" /
"data"`. `run_refresh_worker.py:2360-2367` calls this out explicitly and refuses
to generalise one sport's layout from the other's.

---

## 3. The input inventory (§5's first box)

Measured by `scripts/football_sim_input_checklist.py --season 2025 --week 1`,
over **272 real NFL games** from the production feature loader (not fixtures).
NCAAF is **UNMEASURED** — its loader returns 0 games (see §4).

| block | engine accepts these names | keys read | NFL populated | verdict |
|---|---|---|---|---|
| `offensive_metrics` | `offensive_metrics`, `offense_metrics`, **`team_metrics`**, `offense`, `offensive` | 18 | **100%** | FED |
| `advanced_metrics` | `advanced_metrics`, `advanced`, `game_metrics` | 7 | **100%** | FED |
| `market_features` | `market_features`, `market`, `betting` | 6 | **100%** | FED |
| `defensive_metrics` | `defensive_metrics`, `defense_metrics`, `defense`, `defensive` | 7 | **0%** | **MISROUTED** |
| `pace` | `pace`, `pace_features`, `tempo`, `clock` | 4 | **0%** | **NULL AT SOURCE** |
| `player_usage` | `player_usage`, `usage`, `players` | 12 | **0%** | **WRONG GRAIN** |
| `returning_production` | `returning_production`, `returning`, … | 3 | 0% | EXPECTED_SPARSE (NCAAF-only) |
| `coach_continuity` | `coach_continuity`, `coach`, `continuity` | 2 | 0% | EXPECTED_SPARSE (NCAAF-only) |
| `transfer_impact` | `transfer_impact`, `transfer`, `portal` | 6 | 0% | EXPECTED_SPARSE (NCAAF-only) |

**The three 0% rows have three DIFFERENT remedies. This is §4.1 of the standard —
"absent" and "unfed" and "misnamed" look identical from the outside and are not
the same defect.** Each was localised by reading the actual loaded object:

**`defensive_metrics` — MISROUTED, the data exists.**
`FootballGameFeatures.defensive_metrics` is `{}`, but `team_metrics` carries all
seven keys `_defense_strength` reads: `defensive_epa`, `epa_allowed`,
`success_rate_allowed`, `home_defensive_epa`, `away_defensive_epa`,
`home_success_rate_allowed`, `away_success_rate_allowed` — at 100%.
`loaders.py:526+` `setdefault`s them onto `team_metrics` and never onto
`defensive_metrics`. The engine's defensive alias list does not include
`team_metrics` (its offensive one does). **Remedy: route, don't build.**
Partially masked today because `_defense_strength` also reads `advanced_metrics`
for `home/away_defensive_epa`, which *is* fed.

**`pace` — GENUINELY NULL, this one is a data pipeline job.**
`pace_features == {'pace': None}`, and `team_metrics['home_pace_secs_play']`,
`['away_pace_secs_play']`, `['pace_seconds_per_play']`, `['secs_per_play']` are
**all `None`**. The keys exist; the values were never produced. `rbsdm_metrics`
`setdefault`s `home_pace_secs_play` from a source returning `None`. **Remedy:
populate the source.** (I first guessed "name mismatch" from the key list and was
wrong — the field audit corrected it. §4.1 again.)

**`player_usage` — RIGHT DATA, WRONG GRAIN.**
19,400 `FootballPlayerFeatures` rows on a 2025 wk1 load, each carrying
`snap_share`, `target_share`, `route_participation`, `carry_share`. But
`FootballGameFeatures` has **no `player_usage` attribute at all**, and the engine
reads a *game-level* block. The aggregation already exists and works —
`adapters.py:_team_player_usage` returns real numbers (`target_share 0.0305`,
`route_participation 0.0657`). Nothing puts its output on the game.
**Remedy: attach the existing aggregate.** Note `snap_share` and `air_yard_share`
came back `0.0` in that aggregate — worth checking separately, not assumed broken.

---

## 4. NCAAF is UNMEASURED, and the season opens 2026-08-29

`FootballSimulationAdapter(sport="ncaaf").load_features(...)` returns **0 games**
for both 2025 and 2026, week 1. Consistent with `state.md`: *"NCAAF has the
contract and no producer."*

**This is reported as UNMEASURED, never as 0% populated.** A gate that maps
"could not measure" onto its permissive branch is not a gate — so the checklist
raises an ALARM for it rather than a note.

Practical consequence: **every NCAAF statement in §3 is a projection from the NFL
measurement, not a measurement.** Before the 08-29 opener, NCAAF needs its own
run of the checklist against a real slate. The three NCAAF-only blocks
(`returning_production`, `coach_continuity`, `transfer_impact`) have builders
already — `build_ncaaf_returning_production_snapshot.py`,
`build_ncaaf_coach_continuity_snapshot.py`,
`build_ncaaf_transfer_portal_snapshot.py` — whose output has **never been shown
to reach the engine**, because no NCAAF entrypoint passes a payload either.

---

## 5. Wiring the payload in is a TWO-PART change (§4.4 — the expensive rule)

**Do not simply pass the payload and call it an improvement.**

`NFL_CALIBRATION_PROFILE` is the *frozen NFL Production Candidate*
(`smartsim2/calibration_profile.py`). `NCAAF_CALIBRATION_PROFILE` is v2
(`627a99c2`, "close red-zone conversion gap"). **Both were fit against a payload carrying nothing the engine reads.**
`baseline_audit.py` — which *is* in the fit chain (`truth_audit.py:49` →
`build_baseline_audit_snapshot_and_inputs`) — passes a payload of
`{game_id, season, week, market_total, market_spread_home}`, none of which
`drive_priors` consumes. Functionally identical to empty. Every other entrypoint
in the calibration and backtest chain passes no payload at all.

Worth noting for whoever does the re-fit: `baseline_audit._build_simulation_input`
*does* feed the typed `pace_seconds_per_play` from the game row's
`home_pace_secs_play`/`away_pace_secs_play` — so **the calibration corpus has
pace that the production feature loader returns as `None`** (§3). The re-fit and
production do not currently see the same pace input.

So the fitted rates have already absorbed the average effect of the neutral
defaults. The standard's §4.4 is exact about what happens next:

> adding two mechanisms to a calibrated engine produced a **negative interaction
> in 4 of 4 markets**. The fitted rates already absorb the average effect of a
> missing mechanism, so re-adding it double-counts.

The −1.685 total and −6.50 win-point deltas in §0 are **what the wiring does to
an un-refitted engine**. They are a measurement of the *disturbance*, not of the
*improvement*. Shipping the wiring without a re-fit is shipping half a change,
and §4.4 says that is worse than shipping neither.

**The obligation, stated so it cannot be skipped:**
1. Wire the payload (mechanism).
2. **Re-fit** `CalibrationProfile` for NFL and NCAAF against historical truth
   with the payload live (`smartsim2/calibration/`, `historical_truth/`).
3. Score against the market, not against climatology (§5's ninth box).

Also relevant, and already earned elsewhere in this repo: a single-feature
measurement against un-refitted rates **understates** a suppressed feature
(§4.5). A small delta on one of these nine blocks is weak evidence that the block
does not matter.

Note `calibration_profile.py`'s own comment: NFL is currently **all 1.0
multipliers** — the profile seam is wired (`964c89a4`) but carries no fitted
content, so `load_versioned_profile` returns the frozen default. The re-fit in
step 2 has somewhere to land.

---

## 6. The gate

```bash
py -3 scripts/football_sim_input_checklist.py --season 2025 --week 1
```

Three levels, none of them a name grep:

- **Level 0 — entrypoint wiring.** AST census of every
  `SmartSim2SimulationInput(...)` site: does it pass a payload? *Football-specific
  and the one that matters here* — a key can be perfectly populated and still
  never reach the engine. MLB and soccer have no equivalent because they have one
  entrypoint each.
- **Level 1 — consumed surface.** AST over `drive_priors.py` for
  `_extract_block(sources, [names])`, `_first_float(block, [keys])`, and
  `block.get("key")`. Read from the literal argument lists, so a renamed key
  changes the report instead of silently passing.
- **Level 2 — population.** Over real games from the production feature loader.
  Below `MIN_GAMES_FOR_A_RATE = 8` it reports **UNMEASURED**, never 0%.

Exits non-zero on any alarm. Suitable for `/preflight` or `migration_gate.py`.

`--json <path>` writes the bounded report artifact so production can be audited
without streaming raw inputs (§3 of the standard).

### The instrument-blindness trap this gate already fell into

The **first** run of level 2 passed `season=None`. The loader fell back to a
degenerate single-game context and every block read **"0.0% populated on 1
game"** — which is indistinguishable from a total data outage, and was in fact a
broken instrument. The real load at `season=2025, week=1` returns **272 games**
with `team_metrics` carrying **28 keys**.

`MIN_GAMES_FOR_A_RATE` exists because of that. **A 0% is evidence only once the
instrument is known to be able to read non-zero.**

---

## 7. Standard compliance — where this engine stands

| §5 requirement | status |
|---|---|
| Input inventory (`consumed?` / `populated%`) | **DONE** — §3 |
| Gating checklist script, exits 1 | **DONE** — `scripts/football_sim_input_checklist.py` |
| Pipeline trace, file:line, incl. what it writes | **DONE** — §2 |
| Every input disk-backed via `SYNDICATE_DATA_ROOT` | **NOT AUDITED** |
| Every input allowlisted in `HOT_ARTIFACT_PATTERNS` | **NOT AUDITED** |
| Reuse/caching flags documented + rebuild procedure | **NOT AUDITED** — no `--use-*-artifacts` analogue found; MLB's reuse trap may not apply |
| Reachability test per flagged feature (`off != on`) | **DONE for the payload** (§0, 21/21 + score-level). Not done per-block. |
| Mechanisms vs estimators, with the re-fit obligation | **DONE** — §5 |
| A market-relative scoreboard | **NOT DONE** — see `docs/reports/nfl_validation_report.md`, `smartsim_betting_performance_report.md` for what exists |
| Known-sparse fields documented with reasons | **DONE** — `EXPECTED_SPARSE` in the checklist |

**Not audited is not "fine".** Those four rows are the next lane's work, not a
clean bill of health.

# Sim engines — catalogue, placement, cadence, and plan

> **Pinned as `#440` in `docs/ai_context/todo.md`** — the canonical cross-session
> list. That entry is a pointer only; **this file is the artifact**. Update this
> file, not the pointer.
>
> **Track boundary:** the sim track owns everything up to and including the
> projection artifact; the betting-engine track owns everything from the
> projection artifact to the graded bet. Two seams are shared and are named in
> `#440` — `shared/intelligence_evaluation.py` (Phase 7) and the prediction
> ledger write path (Phase 6). Agree an owner before either phase starts.
>
> **No lane is open on this.** Nothing here is started and no file is claimed.
> Whoever picks up Phase 0/1 opens the lane then — claiming files now would
> block the other track for no reason.

Written 2026-08-16. Sources: live Render env-vars read from all three services
(104 / 90 / 73 keys), every engine package read directly, `live_refresh_loop.py`,
`live_lens_loop.py`, `run_refresh_worker.py`, `run_live_odds_refresh_worker.py`,
`refresh_odds_sources.py`, `ops_refresh.py::_active_sports_for_date`,
`soccer/sources.py`. Ledger context: lane `odds-cadence-off-the-mlb-peak`
(SCOPED, not started) and its falsification test, 2026-08-16 02:1xZ.

> **CORRECTION, 2026-08-16.** An earlier draft of this document said NBA and
> WNBA had "props only, no game sim". **That was wrong.** `simulate_smart_game`
> is a full possession-level Monte Carlo returning score distributions,
> `p_home_win`, `p_home_cover` and `p_total_over`, and its output is persisted
> per game. The error came from trusting the `REGISTRY` prose in
> `refresh_odds_sources.py` (which describes the *props* artifacts) instead of
> reading the engine. The engine catalogue below is read from source.

Everything in Parts 1–2 is read from live config and code. Nothing is a runtime
measurement except numbers explicitly attributed to the lane. Two items are
flagged OWED.

---

## Part 1 — Assessment

### 1.1 The headline: this system has almost no clock

Nine scheduling mechanisms drive sim work. **Seven are interval- or
staleness-driven with no notion of time of day.** The complete list of real
wall-clock gates in the entire pipeline:

| gate | value | scope |
|---|---|---|
| `SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_START_HOUR` | 18 CT | MLB next-day sim only |
| `EVALUATION_SETTLEMENT_TARGET_HOUR_CENTRAL` | daily, post-slate | settlement only |

That is it. The 60s live tick, the 2h/8h pregame sweeps, the 4h soccer autoruns,
the 6h weekly-sports autorun, the 24h season projections, the 600s MLB sim check
— all fire on an elapsed-time counter that started when the worker last booted.
**Work therefore lands uniformly across all 24 hours, for every sport,
regardless of when that sport's games are.**

That is the root cause of the collision identified today. Soccer is not
"scheduled into" MLB's peak; nothing schedules anything, so soccer lands in every
hour, MLB's peak included. The lane measured it: **43 of 71 soccer invocations
during 18–22Z (61%) were fetching kickoffs 2+ days away, and 19Z — the hour with
the most overlap — was 100% future-dated.**

### 1.2 Are all sports Monte Carlo? Nearly.

| sport | pregame | live |
|---|---|---|
| MLB | **MC** — pitch-level, 1000 sims | **MC** — resumes from live state, 120 sims |
| NBA / WNBA | **MC** — possession-level, 100 sims in prod | ✗ logistic blend, not a sim |
| soccer | **MC** — possession/event-level, 400 sims | **MC** — 4 passes/match, 80 sims |
| NFL / NCAAF | **MC** — play/drive-level, 300 seeds | ✗ state overlay on the pregame snapshot |
| NHL | **MC** — dual path, ~20k fast + boxscore engine | ✗ none |
| NCAAB | ✗ **no engine exists** | ✗ none |

**7 of 8 sports have a real Monte Carlo pregame engine.** The gaps are NCAAB
(nothing at all) and the live side (2 of 8).

The second, subtler gap: **production sim counts are far below engine defaults.**
Basketball runs at 100 against an engine default of 2000; soccer's live tick at
80 against a script default of 300; MLB live at 120 against a function default of
300. Only MLB pregame (1000) is generous. A `p_home_win` estimated from 100 draws
carries roughly ±5 points of pure sampling noise — comparable to the edges being
bet on.

---

## Part 2 — Engine catalogue

Four of the five engines share a deliberate common skeleton: frozen
`contracts.py` dataclasses at the ingestion↔engine boundary, a
`calibration_profile.py` parameterization seam, a one-function `runtime.py`
entry point, and a `calibration/` package (`benchmark_contracts`,
`evaluation_metrics`, `simulator_evaluator`, `calibration_report_generator`).
SoccerSim, SmartSim2 and HockeySim are the same architecture with different
nouns. **That skeleton is the template for NCAAB.**

### 2.1 MLB — `vendor/mlb_bettingv2/sim_engine/`

The most granular engine in the system: **pitch by pitch**.

| | |
|---|---|
| granularity | individual pitch → plate appearance → half-inning → game |
| core | `simulate.py` (3,035 lines) |
| entry | `simulate_game()` pregame; `live_mc.estimate_live()` live |
| prod counts | pregame **1000** (`SYNDICATE_MLB_SIM_COUNT`), workers 2 (refresh-worker) / 1 (live-odds-worker); live **120** (`MLB_LIVE_GAME_MC_SIMS`, floor 20) |

**Pitch model** (`pitch_model.py`, 616 lines). Canonical pitch-type set
(FF/SI/FC/…), sampled from a weighted CDF per pitcher. Batter and pitcher rates
are combined by **log5** against a league baseline (`_combined_log5`), with
separate combination functions for strikeouts and in-play hits. Batted-ball type
is drawn from a matchup-specific GB/FB/LD/PU distribution, then hit type from an
extra-base share.

**Player and environment models** (`models.py`, 502 lines). `BatterProfile`,
`PitcherProfile`, `ManagerProfile` (bullpen behaviour), `Lineup`, `TeamRoster`;
plus three environment layers with their own multiplier objects —
`WeatherFactors`, `ParkFactors`, `UmpireFactors`. **No other engine here models
park, weather or officiating.**

**Feature conditioning.** `features.py` blends recent form into baselines
(14 games, weight 0.25). `data/statcast_bvp.py` and `data/statcast_pitch_splits.py`
supply Statcast batter-vs-pitcher history and pitch-type splits;
`_statcast_shape_rate_mults` converts those into rate multipliers.

**Calibration.** `prob_calibration.py` applies affine-in-logit calibration to
probabilities, per-prop calibration configs, and margin-distribution widening —
i.e. the sim's raw margin distribution is deliberately fattened before win
probabilities are derived. `forward_tuning.py` carries date-scoped overrides for
the pitch model and manager pitching behaviour.

**Live path** (`live_mc.py`, 393 lines). `estimate_live(away, home, situation,
sims=300)` rebuilds a `GameState` from the **actual** current situation —
inning, half, outs, base occupancy *by runner id*, balls/strikes, per-pitcher
pitch counts, batters faced this inning, next batter index, whether the current
pitcher entered mid-inning — and simulates only the remainder. With
`track_player_stats=True` (the default) it retains each sim's per-player box
score as remaining-stat histograms, which is what makes **live player props** a
real conditional probability rather than a rescaled pregame number.

**This is the reference implementation the other sports should converge toward.**

### 2.2 Basketball (NBA + WNBA) — `vendor/{nba,wnba}_betting_repo/src/*/sim/`

Two vendored copies of one engine, one per league, driven through a single
Syndicate bridge.

| | |
|---|---|
| granularity | possession → quarter → game, with rotation modelling |
| core | `smart_sim.py` (4,930) + `events.py` (1,902) + `quarters.py` (925) + `connected_game.py` (4,284) |
| entry | `simulate_smart_game()` |
| prod count | **100** (`REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS` on live-odds-worker) — script default 500, engine default **2000** |

**Config.** `SmartSimConfig(n_sims=2000, use_pbp=True, priors_days_back=21,
roster_mode="historical"|"pregame")`. `use_pbp=True` runs a unified
possession-level stream producing quarter scores *and* player stats from one
coherent event sequence, rather than sampling quarter targets and reconciling
players to them afterwards. Production sets `REFRESH_PREDICT_PROPS_SMART_SIM_PBP=true`
on both workers, so the possession engine is the live path.

**Possession engine** (`events.py`). `EventSimConfig` exposes: pace
(`LEAGUE.baseline_pace`) with 6% per-quarter jitter; turnovers 0.125/poss;
shooting fouls 0.095/FGA; non-shooting fouls 0.05/poss; offensive rebound rate
0.24; steal share of turnovers 0.55; block rate on 2PA 0.05; blowout thresholds
(18 overall, 15 in Q4) driving garbage-time pace ×0.94 and efficiency ×0.96 with
a 1.35 bench-minutes boost; and a points-reconciliation pass capped at 12 changes
per quarter.

**Rotation modelling** (`connected_game.py`, the largest single file of any
engine). Dirichlet-weighted minutes allocation, lineup teammate effects applied
to player priors, rotation first-substitution priors, pregame expected-minutes
merge, and per-team minutes normalisation. This is the part MLB has no analogue
for — basketball's edge lives in who is on the floor.

**Market anchoring.** `simulate_smart_game` accepts `market_total` and
`market_home_spread` and records their provenance
(`market_total_source` / `market_home_spread_source`). Quarter-level totals
calibration and per-team quarter splits load from calibration artifacts.

**Output**, persisted to `smart_sim_{date}_{home}_{away}.json`:

    score: home_mean, away_mean, margin_mean, total_mean,
           home_q, away_q, margin_q, total_q (quantiles),
           p_home_win, p_away_win, p_home_cover, p_total_over
    intervals, intervals_1m, periods
    players: per-player simulated boxscore, home and away
    rotation_minutes, minutes_summary, lineup_effects, context, market

**A real risk in the Syndicate bridge.** `basketball_props_smart_sim.py` (~5,000
lines) imports the genuine vendor module when the checkout is present,
monkeypatching Render-data-root-aware ports of its internal helpers
(`simulate_pbp_game_boxscore`, `_rotation_sim_minutes_from_history`,
`_apply_player_priors`, …). **If that import fails it silently falls back to
`_simulate_smart_game_local`, which does no sampling at all** — it sums player
means and returns `home_team_total_pts_mean` / `away_team_total_pts_mean` with no
`score` block and no probabilities. The fallback is caught by a bare `except` and
cached. Nothing distinguishes "ran the real MC" from "ran the stub" in the
artifact except the absence of the `score` key. **OWED: assert which branch runs
in production** — this is precisely the "confirm the code ran" failure mode.

### 2.3 Soccer — `syndicate/features/soccer/sim_engine/soccersim/`

Syndicate-owned, and the only engine with a live path besides MLB.

| | |
|---|---|
| granularity | event → possession → half → match |
| core | `event_simulator.py` (538) + `possession_simulator.py` (159) + `match_simulator.py` (234) |
| entry | `runtime.run_soccersim_simulation()`; `distribution.simulate_match_distribution()` for the MC sweep |
| prod counts | pregame **400** (`_DEFAULT_SIMULATIONS`); live tick **80** (env unset, so the code default holds); standalone script default 300 |

**Spatial model.** Pitch position runs 1–99 from the possession owner's own goal.
Final third begins at 67, the penalty box at 84, and realistic shooting range
starts at 62 (~25–30 m) — attempts from deeper are not modelled at all.

**Event resolution.** `simulate_event` picks from a weighted `PossessionOutcome`
enum: ADVANCE, FAST_BREAK, RETAIN, FOUL_WON, GOAL, PENALTY_GOAL, PENALTY_MISSED,
SHOT_SAVED, SHOT_OFF_TARGET, SHOT_BLOCKED, TURNOVER, OFFSIDE and more, with
separate resolvers for shots and penalties, phase awareness (open play, set
piece, corner, kickoff), and clock consumption per event.

**Situation model.** Urgency states: `neutral_possession`, `trailing_push`,
`desperation_push`, `protect_lead`, `closing_half` — classified from half,
seconds remaining and score differential.

**Match structure.** Two halves with sampled stoppage time, extra time as two
900-second halves, and a penalty shootout at a 0.76 conversion rate.

**Distribution output** (`MatchDistributionSummary`): home/draw/away
probabilities, mean home/away/total/margin goals, over-2.5, both-teams-scored,
full scoreline probability grid, and per-team volume aggregates (shots, shots on
target, penalties) that serve as the allocation base for props.

**Player props** (`player_props.py`). Team-level simulated volume is allocated to
players by minutes-adjusted usage share (shares sum to ~1.0 across the squad, so
rotation risk is priced in), then each player's count is priced as Poisson around
the allocated mean: anytime/2+ scorer, shots and SOT at 0.5/1.5/2.5/3.5, assists,
goalkeeper saves. `expected_minutes_share` rescales goalkeeper saves only.

**League calibration** (`league_profiles.py`). Ten per-league profiles, all built
on the shared `CalibrationProfile` seam — **one engine, ten parameter sets, zero
forked control flow**. The file labels itself explicitly: *"These are v0 /
Provisional profiles… starting points for each league's historical-truth
calibration loop… Treat every number as replaceable by measurement."* Only NCAAF
has been through that loop.

**Live path.** `poll_soccer_live_state.poll_league` runs four separate MC passes
per in-progress match: `project_live_match`, `goal_in_window_probability` twice
(two window lengths), and `project_live_player_props`.

### 2.4 Football (NFL + NCAAF) — `syndicate/features/football/sim_engine/smartsim2/`

Syndicate-owned. **The best-calibrated engine in the system**, and the only one
with a working truth harness.

| | |
|---|---|
| granularity | play → drive → quarter → game |
| core | `play_simulator.py` (471) + `drive_simulator.py` (473) + `game_simulator.py` (175) |
| entry | `runtime.run_smartsim2_simulation()` |
| prod count | **300** seeds/game (`SEEDS_PER_GAME`, identical for NFL, NCAAF and NFL preseason) |

**Real football decision logic**, not just outcome sampling: punt-vs-go
decisions, field-goal attempt decisions against a *true* range gate
(`TRUE_FIELD_GOAL_RANGE_YARDLINE = 65`, i.e. kick distance = 17 + (100 −
yardline), so ≥65 keeps attempts at ≤52 yards), distance-dependent make
probability, missed-FG spot placement, change-of-possession spotting, and
quarter-carryover drive merging so a drive spanning a quarter break is one drive.

**Situation model.** Six urgency states — `neutral_offense`, `two_minute_drill`,
`four_minute_offense`, `trailing_urgency`, `halftime_preservation`,
`end_game_preservation` — classified from quarter, seconds remaining, score
differential *and* yardline, and fed into play-outcome weights.

**Calibration.** `NFL_CALIBRATION_PROFILE` reproduces the previously-hardcoded
constants exactly (multipliers 1.0), so NFL behaviour is frozen byte-for-byte
while the core became profile-aware. NCAAF has its own
`ncaaf_calibration_profile.py` (`ncaaf_v2`) produced by the loop this engine
uniquely has: `historical_truth/` (NFL and NCAAF loaders + snapshot builder and
contract) feeding `calibration/truth_audit.py` → `baseline_audit.py` →
`simulator_evaluator.py` → `calibration_report_generator.py`.

**Ratings inputs.** NFL ratings are computed locally from nflverse play-by-play:
offense = mean EPA/play on the team's own pass/run plays in weeks strictly before
the target week; defense = −mean EPA allowed, same filter, sign-flipped. Week 1
(or any team with no qualifying plays) falls back to the same computation over
the entire prior season. NCAAF uses CFBD PPA on the same convention.

**Injury adjustment exists and is deliberately OFF.** `--injury-adjustment` is
opt-in because it was backtested to *hurt* full-season win accuracy: **60.98% →
56.44%** on real 2025 games with a modelled injury.

**No live variant.** The live lens overlays observed game state onto the pregame
snapshot; it does not re-run the drive model.

### 2.5 NHL — `syndicate/features/nhl/sim_engine/hockeysim/`

Syndicate-owned, absorbed from the user's `nhl_betting` repo. **Uniquely, it runs
two different simulators for two different jobs.**

| path | module | granularity | sims | feeds |
|---|---|---|---|---|
| fast game-market | `game_market_sim.simulate_from_period_lambdas` | per-period Poisson with overdispersion, shared pace, empty-net | ~20k | `predictions_*` (win / total / puckline) |
| detailed boxscore | `engine.GameSimulator.simulate_with_lineups` (1,449 lines) | possession/segment, line-rotation aware, PP/PK, faceoffs, empty net, score state | per-game `n_sims` | `props_*` |

The two carry **separately-named `SimConfig` classes** — the game-market one is
Monte Carlo controls, the engine one is the calibration profile. The file comment
warns to import them qualified.

**Projection layer** (`projection.py`). A Syndicate-native **xG / Poisson / Elo**
hybrid replacing the vendor's trained neural net, producing per-team expected
goals split into per-period lambdas. Grounded on documented vendor baselines:
league base 3.05 goals/team/60, home/away attack split 1.05/0.95, Elo via the
logistic 400-point curve with a home-ice bump. Every constant lives in a frozen
`ProjectionProfile` so future calibration is an auditable field override, never
new control flow.

**Market anchoring** (`market_anchoring.py`) — **the most sophisticated anchoring
in the codebase**, ported from soccer (where it was validated at −40–51% MAE on
EPL) and reduced to a 2-way problem since hockey moneylines resolve in OT/SO. It
devigs the book's home-win probability, blends the model toward it, then solves
by bisection for the goal-differential shift that hits the target — **preserving
the total**, so the calibrated pace/totals market is untouched while only the
moneyline and puckline anchor to the book. Period lambdas rescale
proportionally. It is opt-in, never automatic, so the pure model stays available
for shadow comparison.

**Props** (`player_props.py` + `props_boxscore.py`, 496 lines). Runs the boxscore
engine `n_sims` times, aggregates each run's event stream into per-player
per-period boxscores, and converts the resulting sample distributions into
`proj_lambda` plus empirical `p_over`/`p_under` against the book line for
SOG / goals / assists / points / blocks / saves.

**Production status.** Runs inside `refresh_nhl_oddsapi.py` whenever
`mode == "full"` — and `SYNDICATE_LIVE_ODDS_REFRESH_MODE=full` on all three
services, so it fires automatically the moment NHL re-enters
`_active_sports_for_date()` in October. **No live variant.**

### 2.6 NCAAB — nothing

`syndicate/features/ncaab/` contains `cards.py`, `game_detail.py`,
`intelligence_analysis.py`, `live_lens.py`, `mirror_export.py`,
`results_archive.py`, `season.py`, `sources.py`. There is **no `sim_engine`, no
projection module, and no generator script.** The only pipeline step is
`refresh_ncaab_odds_history.py`, an odds snapshot. The board shows market data
with no model behind it.

### 2.7 Cross-cutting observations

- **Market anchoring is inconsistent.** Hockey has a principled bisection anchor;
  basketball passes market total/spread as sim targets; MLB and football do not
  anchor at all. Three different philosophies, no stated rationale for the split.
- **Only football has a working truth-calibration loop.** Soccer's ten league
  profiles are self-declared v0. Hockey's truth layer is scaffolded but the
  profile is still the absorbed vendor baseline. MLB has forward tuning and
  probability calibration but no equivalent historical-truth harness in-repo.
- **Only MLB models the environment** (park, weather, umpire).
- **Only basketball models rotation** at depth.
- **Production sim counts are thin** — see §1.2. The cheapest possible
  improvement to model quality in this entire system is raising basketball's 100.

---

## Part 3 — Plan

### The principle

**Replace elapsed-time cadence with time-to-fixture cadence.** Do not hardcode
"soccer runs in the morning." Encode "a sport sweeps in proportion to how close
its next kickoff is," and the morning/evening separation falls out of the fixture
clocks by itself — and stays correct when a fixture moves, a league adds a
midweek round, or a season shifts.

A clock-based rule would break MLS on day one: MLS is the single most-refreshed
soccer league (20 of 111 invocations) and its kickoffs genuinely are in the US
evening. The rule has to be fixture-relative, not league-blind and not
clock-blind.

### Phase 0 — measure first (no behaviour change)

1. **Kickoff-hour census.** For every sport and soccer league, histogram
   `commence_time` in America/Chicago over the last 30 days and the next 14.
   This produces the real band table instead of a believed one.
2. **Confirm the double live-lens tick** (see §4 below) with a log reading on
   both workers, not a config inference.
3. **Assert which basketball SmartSim branch runs in production** (§2.2) — real
   vendor engine or the silent no-sampling stub. Check for the `score` key in a
   live `smart_sim_*.json`.
4. Re-take the hour-by-hour both-branches-live table from the lane as the
   baseline any later claim is judged against. A handed-down baseline expires.

### Phase 0 — RESULTS (measured 2026-08-15 evening CDT / 08-16 UTC)

Lane `sim-engine-phase0-census`. Read-only; no deploy. **H2 and H3 are settled by
measurement. H1 and the baseline re-take are NOT yet run.**

#### H3 — SETTLED, and the answer is the reassuring one. The real engine runs.

The §2.2 worry — that `basketball_props_smart_sim` might be silently falling back
to `_simulate_smart_game_local`, the no-sampling stub — **is not happening in
production.** Three WNBA artifacts pulled off the live web disk via
`/api/ops/artifacts/stream`, `2026-08-15`:

    smart_sim_2026-08-15_LVA_MIN.json   (579.7 KB)
    smart_sim_2026-08-15_WSH_LAS.json
    smart_sim_2026-08-15_CON_NYL.json

All three carry the real engine's signature and none carry the stub's:

    score / intervals / intervals_1m / periods          present  3/3
    rotation_minutes / minutes_summary / lineup_effects  present  3/3
    home_team_total_pts_mean (STUB-ONLY key)             absent   3/3

**So the OWED item from §2.2 closes: the vendor import is succeeding and the
possession-level Monte Carlo is what produces production basketball numbers.**
The bare-`except` fallback remains a latent risk worth a loud log line, but it is
not currently firing.

Path note for whoever repeats this: the artifacts are at
`wnba_source/data/processed/`, **not** `wnba_source/source_artifacts/data/processed/`
— the latter 404s. Both are listed as candidate roots by
`/api/ops/wnba/artifact-counts`, and only one has the files.

#### H3b — the thin-sim concern is now MEASURED, not inferred

`n_sims = 100` on all three artifacts, confirming the env reading. The
consequence is directly visible in the served probabilities — every one is an
exact multiple of 0.01, because each is a count out of 100 draws:

    LVA_MIN   p_home_win 0.25   p_home_cover 0.29   p_total_over 0.59
    WSH_LAS   p_home_win 0.66   p_home_cover 0.55   p_total_over 0.73
    CON_NYL   p_home_win 0.14   p_home_cover 0.25   p_total_over 0.46

9 of 9 quantized to 1%. At p≈0.25 the binomial standard error on 100 draws is
**±4.3 points** — the same order as the edges being priced. This upgrades the
sim-count item from an env observation to a defect visible in the output, and
it is the cheapest quality win in the system (Phase 9, or sooner).

#### H2 — CONFIRMED BY LOG. Both workers tick, and three sports are built twice.

Previously config-only and flagged unproven. `[live_lens_loop] TICK_COMPLETE`
over 2026-08-16 02:21Z–03:13Z:

    refresh-worker     31 ticks / 51.6 min   {mlb, wnba, soccer, nfl}  skipped [nba]
    live-odds-worker   38 ticks / 51.4 min   {mlb, wnba, soccer}       skipped [nba, nfl]

**mlb, wnba and soccer are built on BOTH services** — 69 MLB live-lens builds per
hour across two containers where a single owner needs ~35. Each MLB build carries
a 120-sim resim and each soccer build up to 4 Monte Carlo passes per live match.

Note the cycles run slower than their 60s interval (~100s on refresh-worker, ~81s
on live-odds-worker), so the tick itself is taking ~20–40s.

**This makes Phase 4.1 a prerequisite, not a nicety** — against a 124 MB margin,
the duplicate is real work being done twice, and it must be removed before any
new sport joins the tick.

#### H1 — CONFIRMED, and the falsification test did not fire. 0 of 200.

`scripts/census_kickoff_hours.py --json reports/kickoff_census/latest.json`,
window 2026-07-16..2026-08-29, America/Chicago. Kickoffs, not refresh runs —
this measures the FIXTURES the cadence should be following.

    series                    n    median CT   hours with fixtures   % in US evening
    ---------------------------------------------------------------------------------
    soccer: 9 EU leagues     200      9-14        5..14                   0.0
    soccer: mls              111        19       15..21                  94.6
    mlb                      605        18       11..21                  53.6
    wnba                     117        19       11..21                  84.6
    nfl_preseason             49        18       11..21                  71.4

**The falsification test was "H1 fails if European kickoffs sit in the US
evening." Zero of 200 do.** European soccer stops dead at 14:00 CT — the
combined histogram runs 5,6,7,8,9,10,11,12,13,14 and is empty at every hour
after. MLS is the named exception at 94.6%, confirming the lane's warning from
an independent source (the lane inferred it from 111 process cmdlines; this is
111 fixtures).

**So the owner's premise is measured, not merely plausible: soccer's European
leagues have NO fixture reason to be refreshing during the US evening peak.**

**BUT IT CORRECTS THIS PLAN'S OWN BAND TABLE, which was believed and wrong.**
Phase 2 guessed European soccer at 01:00–09:00 CT. Measured, it is **05:00–14:00
CT** — several hours later — and US sports start at **11:00**, so there is a real
**11:00–14:00 overlap** the guessed table denied. The separation is clean at the
evening peak and is NOT clean at midday. Any Phase 1 tiering must be
fixture-relative rather than band-relative for exactly this reason; a hardcoded
"soccer in the morning" rule would have been built on the wrong hours.

#### Still owed in Phase 0

- **The baseline re-take** (hour-by-hour both-branches-live memory). NOT DONE and
  not doable in one pass — it needs a multi-hour observation window, so it should
  run as a scheduled watcher rather than a single command. Phase 1 must not be
  judged against the lane's 2026-08-16 table without re-taking it.

### Phase 1 — fixture-aware pregame cadence

This is the change that delivers the ask. Roughly 90% of the machinery exists.

**1a. Extend the commence-time providers.** `_T_WINDOW_COMMENCE_PROVIDERS` has
two entries (`mlb`, `wnba`). Add `soccer` (per league), `nfl`, `ncaaf`, `nhl`,
`nba`, `ncaab`, each reading the schedule artifact that sport already writes.
This single addition makes the existing T-75 / T-10 ramp work for every sport.

**1b. Make the sweep interval a function of time-to-next-fixture.** Today
`_pregame_sweep_interval_seconds(sport)` returns a constant (soccer 8h, else 2h):

    next fixture > 48h    ->  24h    (heartbeat only)
    12h .. 48h            ->   8h
     3h .. 12h            ->   2h
    < 3h                  ->  hand off to the T-window ramp (75 / 10 min)
    unknown / unreadable  ->   2h, and LOG the reason

The unknown branch is deliberately the middle tier — not the fastest, not the
slowest — and must emit a reason. A guard that silently maps "absent" onto either
extreme is the failure mode this repo keeps re-shipping.

**1c. Scope soccer per league, not per sport.** The ten leagues have different
kickoff clocks; a sport-level marker cannot express "la_liga is 9 hours out and
MLS is 2." Per-league job scoping (`--soccer-leagues`) already exists from `#282`.

**What this produces, derived rather than decreed:** European leagues fall to the
24h heartbeat during the US evening (their kickoffs are 15–40 hours away then)
while MLS keeps its fast cadence into its own evening window. That removes most
of the 202.6 MB overlap at **no freshness cost**, because 61% of what those runs
fetch is days away.

**Do not shelve `9ec20a06`.** The per-sport pregame cooldown is a *freshness* fix
(MLB quote capture was every 121.6 min, serving two-hour-stale prices). It pushes
overlap *up*, and should still ship: independent clocks plus fixture-awareness
serves both goals. They are only in tension while cadence is fixture-blind.

**Cost check:** cadence changes change OddsAPI volume against a 5M cap. The tier
table should reduce calls; measure, don't assume.

**Verification:** re-run the hour table. `BOTH` must fall in MLB's peak hours and
worst-combined must drop from 3,972 MB — a **worst-combined across all
processes** measurement, since a per-process figure is what made the margin read
as 578 MB when it was 124 MB.

### Phase 2 — the band, as a safety net

Phase 1 should produce this shape on its own. Write it down anyway, as the thing
to reason about and alert on when the gate misfires (America/Chicago).

**REPLACED 2026-08-15 WITH MEASURED HOURS — the guessed version had European
soccer at 01:00–09:00 and it is actually 05:00–14:00.** See Phase 0/H1.

| band | owner | what runs |
|---|---|---|
| 01:00–05:00 | genuinely quiet | maintenance, settlement, evaluation |
| 05:00–11:00 | soccer (Europe) only | European kickoffs begin; their pregame + live. **No US fixture starts before 11:00** |
| 11:00–14:00 | **CONTESTED — both** | European soccer still kicking off *and* the earliest MLB/WNBA/NFL games. The one band where a fixture-relative gate has real work to do |
| 14:00–18:00 | US pregame only | European soccer is done (0 kickoffs after 14:00). **MLB daily sim** and **NFL/NCAAF SmartSim2** belong here |
| 18:00–01:00 | US live + MLS | MLB/WNBA/NFL live ticks, MLS pregame + live. Europe has nothing scheduled — this is the band Phase 1 clears |

Two moves that belong here regardless of Phase 1:

- **Move the MLB daily sim build into 09:00–13:00.** It is the largest memory
  consumer and currently fires whenever the 600s staleness gate opens.
  `scripts/pick_mlb_build_hour.py` already exists for this decision.
- **Pin NFL/NCAAF season projections to the same band.** 45-minute jobs on a
  staleness gate with no clock; no reason for them to land at 20:00 on a Sunday.

### Phase 3 — live sims for every sport

Ordered so the work lands before the season does. Every addition inherits the
engine that already exists — none of this is greenfield except NCAAB.

**3a. NFL + NCAAF — build now.** SmartSim2 already simulates play-by-play from an
arbitrary `PossessionState`. A live variant is a new entry point that builds that
state from observed game state (quarter, clock, down, distance, yardline,
possession, score) and runs the existing drive model forward — structurally the
same move `estimate_live` is for MLB. NFL's `build_live_lens_snapshot` becomes
the carrier; NCAAF needs the builder/validator/snapshot-path trio plus a registry
entry. Cheapest big win: ≤16 concurrent games, one clock, long possessions.

**3b. WNBA now, NBA by October.** The possession engine already exists and
already produces `intervals_1m`. A live variant re-seeds it from the current
score, clock and available lineup. **Raise the sim count at the same time** —
100 is too thin to price a live edge. WNBA first: in season, and its builder is
already measured (mean +91 MB, worst +153 MB per tick).

**3c. NHL — October.** Both simulator paths exist. The fast period-lambda path is
the natural live carrier: re-derive remaining-period lambdas from the current
score and time, and it already runs at ~20k sims cheaply. Needs live-state
ingestion, the builder/validator/snapshot-path trio, and a registry entry.

**3d. NCAAB — November, the only greenfield build.** Copy the SoccerSim/SmartSim2
skeleton (§2). It is also the largest slate (300+ games/night), so it cannot go
on a 60s tick unconditionally: it needs a **shortlist gate** — only sim games
carrying a live edge candidate — before the first line of engine code is worth
writing.

**Contract every addition must satisfy** (enforced by
`tests/test_live_lens_active_sports.py`): builder + validator + snapshot path,
all three registered, plus a per-sport memory gate **calibrated from a real
measurement of that specific builder** — never copied. A 1,200 MB WNBA threshold
calibrated against a builder deleted eight minutes later is the precedent; the
900 MB MLB floor guarding an 1,873 MB stage is the other.

### Phase 4 — placement and capacity

**This gates Phase 3 and must be settled first.**

The live-lens loop currently runs on **both** workers. Live values:

    refresh-worker      SYNDICATE_ACTIVE_SPORTS = mlb,wnba,soccer,nfl   LOOP=true
    live-odds-worker    SYNDICATE_ACTIVE_SPORTS = mlb,wnba,soccer       LOOP=true

MLB, WNBA and soccer are therefore ticked twice per minute across two
containers — including MLB's 120-sim resim and soccer's 4-pass MC. The process
lock is a file lock on each service's own disk and cannot deduplicate across
services. Against refresh-worker's measured **124 MB margin** (3,972 of
4,096 MB worst-combined, 6,199 samples), adding three more sports to a
duplicated tick is not affordable.

1. **Stop the duplication.** Partition the registry by service via
   `SYNDICATE_ACTIVE_SPORTS` so exactly one worker owns each sport's live tick.
   Proposed: refresh-worker owns MLB (it already owns the daily sim and the heavy
   path) + football; live-odds-worker owns soccer + basketball. Measure
   before/after — this alone may buy the headroom Phase 3 needs.
2. **Then** decide whether 7 concurrent sports in October fit the current
   2 + 4 GiB split. The "keep refresh-worker on `pro`, reduce rather than spend"
   decision was taken on the old 578 MB figure; re-take it against 124 MB and
   against October.

### Seasonality — size for October, not August

Concurrent sports per month, from `_active_sports_for_date()`:

    Jan 6   Feb 5   Mar 5   Apr 5   May 5   Jun 5
    Jul 3   Aug 5   Sep 5   Oct 7   Nov 6   Dec 6

**October is the peak at 7** — MLB postseason, WNBA finals, NBA + NHL openers,
NFL, NCAAF, soccer. ~6 weeks out. July (3) is the only comfortable window for
capacity work; it has passed.

### Sequencing

Two tracks. **Operational** (Parts 1–3) is deadline-driven: a 124 MB margin and
seven concurrent sports in October. **Convergence** (Part 4) is quality-driven
and gated by nothing but attention. They touch disjoint files — the operational
track is `live_refresh_loop.py` / `live_lens_loop.py` / worker entrypoints, the
convergence track is the engine packages and `shared/` scoring modules — so they
can run in parallel by different lanes.

**Operational track**

    Phase 0   measure                     — 1 session, no deploy
    Phase 1   fixture-aware cadence       — the ask; delivers the memory win too
    Phase 4.1 de-duplicate the live tick  — must precede any new live sim
    Phase 2   band pinning for the big jobs
    Phase 3a  NFL/NCAAF live sim          — before the season peaks
    Phase 3b  WNBA live resim + raise sim counts
    Phase 4.2 capacity decision for October
    Phase 3c  NHL   (by Oct)
    Phase 3d  NCAAB (by Nov, greenfield, needs a shortlist gate)

**Convergence track** — Part 4 as phases. The order is a dependency chain, not a
priority ranking: each phase exists to make the next one *attributable*.

    Phase 5   wire the versioned-profile seam
    Phase 6   stamp model_version on every prediction
    Phase 7   score projections with CRPS
    Phase 8   ship the deltas already computed
    Phase 9   decide sim counts and anchoring by measurement

**Phase 5 — wire the versioned-profile seam.** Call `load_versioned_profile` in
the three engines that already have it (football, soccer, hockey). Artifact
absent → the in-source constant, byte-for-byte, so this is a **no-op deploy**
that turns every later calibration into a file swap and every rollback into a
file revert. Smallest possible first step; nothing else in this track works
without it. Verification is that behaviour does *not* change — assert the loaded
profile equals the in-source default when no artifact exists, and that the
engines actually reach the loader (presence is not reachability; that is exactly
how this module got built and stayed inert).

**Phase 6 — stamp `model_version` on every prediction.** Engine + profile version
+ code SHA, carried into the ledger (learning-loop Stage 5.1). **Deliberately
before Phase 8**, not after: Phase 8 changes profiles, and without a stamp there
is no way to attribute the resulting accuracy change to that change rather than
to a roster shift, a market move, or an unrelated deploy. Shipping the deltas
first would burn the one clean measurement opportunity.

**Phase 7 — score projections with CRPS.** Use `model_scoring`'s already-written
`crps_normal` / `mean_crps` / `reliability_curve` / `bias_dispersion_decomposition`.
Needs no settlement and no bet, so it works today on all seven sports that
produce a mean and a spread — 10–100× more observations per night than the
win/loss loop. This is the instrument Phases 8 and 9 are read with, so it must
exist before either. Backfill it over a trailing window first to establish the
incumbent baseline; a handed-down baseline expires.

**Phase 8 — ship the deltas already computed and never applied.** hockeysim
Phase 3b (`docs/reports/hockeysim_phase3b_calibration_report.md`) and NFL's first
real calibration — its profile is literally all 1.0 multipliers today. The
numbers were measured and discarded; this phase is cheap because the analysis is
done. Shadow-then-promote, never auto-apply: a candidate profile is promoted only
if it beats the incumbent on hold-out CRPS *and* does not regress calibration,
with a minimum sample gate. Same gate shape for every sport — that gate is the
thing that actually makes the sims "work the same way".

**Phase 9 — decide sim counts and anchoring by measurement.** Two open policy
questions that are currently settled by argument because there is no instrument:
the sim-count spread (100 / 120 / 300 / 400 / 1000 / 20k with no principle) and
the three incompatible market-anchoring philosophies (§4.1). With Phase 7 in
place both become measurable: re-score the same slate at several sim counts and
read where CRPS stops improving; score anchored vs pure projections on hold-out
and let the answer decide whether anchoring generalises beyond hockey. Expect
raising basketball's 100 to be the single cheapest model-quality win in the
system, but **measure it rather than assuming** — that is the whole point of
sequencing it last.

**Where the tracks touch.** Phase 3b raises basketball's sim count and Phase 9
decides what it should be. If Phase 9 has not run by then, raise it to the
script default of 500 as an interim and record it as unmeasured, rather than
blocking the live-sim work on a calibration answer.

### Coordination

`odds-cadence-off-the-mlb-peak` is SCOPED and unstarted — Phase 1 is that lane's
implementation and should be opened under it, not beside it.
`soccer-odds-coverage` owns per-league cadence files; coordinate rather than
taking them.

---

## Part 4 — Engine convergence ("all sims working the same way")

**This plan does NOT cover it.** Parts 1–3 are about *when and where* sims run
and *which sports have a live one*. Making the engines work the same way is a
separate, larger workstream — and **a plan for it already exists**:
`docs/reports/syndicate_learning_loop_plan_2026_08_03.md`, Stages 0–5. Stage 3
is precisely this question.

### 4.1 What should and should not converge

The physics should not. A pitch model, a drive model and a possession model are
legitimately different, and forcing MLB's plate-appearance loop into soccer's
event enum would destroy information for no gain. What should be uniform is the
**scaffolding around the physics**:

| dimension | uniform today? | state |
|---|---|---|
| package skeleton (`contracts` / `calibration_profile` / `runtime` / `calibration`) | 3 of 5 | soccer, football, hockey share it exactly. MLB and basketball are the outliers — **both are vendored**, which is the real reason |
| profiles as versioned artifacts, not source constants | **0 of 5** | infrastructure BUILT AND INERT — see §4.2 |
| a truth-calibration loop that actually re-fits | 1 of 5 | only football (`ncaaf_v2`). Soccer's 10 profiles are self-declared v0; hockey's Phase 3b deltas were computed and never written back |
| proper scoring rule on projections (CRPS/Brier) | ~0 | module built, mostly unwired — see §4.2 |
| market anchoring policy | **no** | hockey does bisection anchoring preserving the total; basketball passes market total/spread as sim targets; MLB and football do not anchor. Three philosophies, no stated rationale |
| sim-count policy | **no** | 100 (basketball) / 120 (MLB live) / 300 (football, MLB live default) / 400 (soccer) / 1000 (MLB pregame) / ~20k (NHL game-market). No principle connects them |
| a live entry point | 2 of 5 | only MLB (`estimate_live`) and soccer (`poll_league`) |
| `model_version` on every prediction | **no** | Stage 5.1, nothing stamps it. Without it an accuracy change cannot be attributed to a code change |

### 4.2 The convergence foundation is built and largely inert

Checked by call-site trace, not by presence:

- **`calibration_profile_store.py`** — generic versioned-profile load/save,
  works identically over football's `CalibrationProfile`, soccer's, and
  hockeysim's `SimConfig`. **`load_versioned_profile` and
  `save_versioned_profile` are called by NOTHING except `tests/test_calibration_profile_store.py`.**
  Every engine still reads its hardcoded in-source constant. This is Stage 3's
  entire foundation, complete and unreachable.
- **`model_scoring.py`** — CRPS, pinball loss, Brier, log-loss, reliability
  curves, bias/dispersion decomposition. Only `binary_calibration_metrics` is
  imported anywhere in production (`intelligence_evaluation.py`).
  **`crps_normal`, `mean_crps`, `pinball_loss`, `reliability_curve` and
  `bias_dispersion_decomposition` appear in no non-test caller.** The whole
  argument for this module was that scoring projections needs no settlement and
  yields 10–100× more observations than the win/loss loop — that argument is
  still unrealised.
- **`sim_run_ledger.py`** — **this one landed.** `record_sim_run` is wired at
  three real choke points: `refresh_odds_sources._run_command` (soccer / NBA /
  WNBA / NHL), `run_refresh_worker`'s season-projection autoruns (NFL / NCAAF),
  and `live_refresh_loop` (MLB). One reader answers "what sims ran" for all
  sports.

So the honest position is: **the convergence work is roughly one-third wired.**
The measurement plumbing exists; the recalibration seam exists; nothing connects
a graded outcome back to a profile.

### 4.3 Ordering

This work is sequenced as **Phases 5–9** in the Sequencing section above, on a
convergence track that runs parallel to the operational one. The dependency
chain is: seam (5) → attribution (6) → instrument (7) → change (8) → policy (9).
Each phase exists to make the next one measurable; running them out of order
produces changes nobody can attribute.

**One interleaving constraint.** Phase 1 carries a memory deadline and a
falsification test, and Phase 8 changes model output. Do not run Phase 8 inside
Phase 1's measurement window — a cadence change and a profile change landing
together means neither result is clean. That is a scheduling constraint between
two specific phases, not a reason to keep Part 4 out of the plan.

### Believed, not verified

- That a time-to-kickoff gate actually removes the 202.6 MB overlap. The
  reasoning is sound and the falsification test supports it; nobody has built or
  measured it.
- That both workers' live-lens loops actually tick (config says yes; no runtime
  reading taken).
- Which basketball SmartSim branch runs in production (§2.2) — real engine or
  silent stub.
- The kickoff-hour bands in Phase 2 — Phase 0 exists to replace them with data.

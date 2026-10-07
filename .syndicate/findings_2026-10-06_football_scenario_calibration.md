# Football scenario calibration (smartsim2, NFL + NCAAF) — lane `football-scenario-calibration`

Opened 2026-10-06, session 20aa7f5b. User decisions (2026-10-06, in chat): run the MLB
`mlb-combined-calibration` scenario loop on the shared smartsim2 engine; **game + live lines
first, player attribution (props) in a follow-on lane**; **NFL and NCAAF together**.

## Method (ported from `mlb-combined-calibration`)

1. Pre-register the scenario here BEFORE measuring: population, formula, CI, decision rule.
2. Measure the REAL rate from play-by-play on FIT seasons only.
3. Measure the SIM rate from production's own `build_projection` (300 seeds, shipped profile,
   production env) on the SAME FIT games, via the `segment_accumulator` seam — every seed's
   full `SmartSim2SimulationOutput` (drive_log + possession_log). No engine code is modified
   to measure.
4. Reachability before correctness: any lever is shown `off != on` on one game before use.
5. Mechanism default-off, byte-identical (seeded sha256 of the outputs) + tests.
6. Measured rates FIXED in every arm; jointly re-fit the rates that were absorbing them
   (`model_engine_standard.md` §4.4).
7. VALIDATION read ONCE. Ship only if every gate clears its own SE (learnings 2026-09-23).

## Splits (fixed now, before any reading)

| | FIT | VALIDATION (read once) | prior-only |
|---|---|---|---|
| NFL | 2023, 2024 REG | 2025 REG | 2022 (as-of prior season) |
| NCAAF | 2023, 2024 FBS-vs-FBS REG | 2025 | — |

Amends the lane's Verification line (which said NFL FIT 2022-24): 2022 has no prior season in
the local pbp, so its as-of ratings differ from production's construction.

## Phase 1 — PRE-REGISTERED 2026-10-06 (before any measurement): real-vs-sim scenario table

No engine change in Phase 1. Output: one row per (sport, scenario, bucket) with real rate,
sim rate, n (real drives/plays/games), 95% CI by GAME-clustered bootstrap (1000 reps) on the
real side, sim SE from seed-clustered bootstrap, and gap.

Drive = a possession in the pbp drive table (NFL: nflverse `fixed_drive`; NCAAF: CFBD drives),
excluding drives that start with < 0:00 remaining and kneel-only end-of-half drives are KEPT
(the sim has them). Points per drive counts the offense's TD as 7 in the SIM (engine fixed)
and as 6 + actual PAT/2pt in REAL; the 7-vs-actual difference is reported as its own row (S7).

| id | scenario | metric (both sides) | buckets |
|---|---|---|---|
| S1 | drive scoring vs team quality | P(drive ends TD), P(FG), P(punt), P(turnover), P(TOD), points/drive | overall; by rating-gap tercile of the offense vs the defense (gap computed from the SAME as-of ratings the sim received) |
| S1b | dispersion | SD across team-games of the per-team-game points/drive | overall |
| S2 | garbage time | points/drive and sec/play for drives starting in Q4 with |score diff| >= 17 (NFL) / >= 21 (NCAAF) | leading vs trailing offense |
| S3 | pace | seconds of game clock per offensive play | score state (lead 9+, within 8, trail 9+) × half |
| S4 | red zone | P(TD | drive reaches opp 20), P(FG att | reaches opp 20) | — |
| S4b | FG make | make rate by kick distance | <30, 30-39, 40-49, 50+ |
| S5 | 4th down | P(go), P(punt), P(FG att) on 4th down | field position (own half / opp 40-30 / opp 29-) × to-go (1-2, 3-5, 6+) |
| S6 | drives per game | possessions per team per game; plays per drive | — |
| S7 | TD value | points per TD incl. PAT/2pt | — |
| S8 | overtime | P(game reaches OT); P(tie after OT) (NFL) | — |
| S9 | half split | share of game points in H1 | — |
| S10 | game-level spread | SD of total, SD of margin conditional on the projected line (residual vs close) | — |

**Decision rule (fixed):** a scenario-bucket is FLAGGED when the sim rate lies outside the real
95% CI AND the implied points-per-team-game effect of the gap exceeds 0.25 (NFL) / 0.40 (NCAAF).
Flagged rows are ranked by that effect and become Phase 2 candidates, each pre-registered
separately. A row inside the CI is recorded EXONERATED for this engine version — it is not
re-opened without a new reason.

**Falsification of the lane hypothesis at Phase 1:** if no row is flagged in either sport, the
loss to the close is not a scenario-rate problem and the lane closes with that result.

**Coverage rule (CLAUDE.md):** the script prints per-family season/week coverage (pbp, drives,
ratings, closing lines) and the intersection, and the result states the game count it rests on.
Source: LOCAL files only (Render suspended since 2026-09-30); `data/` untracked mirror, vintage
printed per file (mtime + row count).

### Amendment 1 — 2026-10-06, written before any SIM-vs-REAL comparison was read

- **S11 non-offensive points/game** (defensive + return TDs, safeties). Read from the engine: a
  sim TURNOVER scores 0 (`possession_outcomes.classify_outcome`), there is no safety and no return
  TD, so the sim's value is 0 by construction. **Disclosure:** the REAL value was seen while
  reconciling the parsers (NFL 2023-24: 1.90/game, n=544) before this amendment was written; the
  sim side is structurally 0, so no choice here depends on that reading.
- **S12 drive-start field position** by how the possession began (half / after a score / after a
  punt / after a turnover). Read from the engine: every post-score possession starts at the 25
  (`drive_simulator.py:161`).
- **NCAAF points rule (parser, not a scenario):** CFBD per-drive start/end scores LAG (a TD drive
  reads 14 -> 14; 16 of 873 games went negative on the residual), so NCAAF drive points are taken
  from the result (TD = 7, FG = 3), and S11 is counted directly (7 per defensive/return TD, 2 per
  safety). **S7 (PAT/2pt value) is NOT MEASURABLE for NCAAF from this source** and is NFL-only.
- **NCAAF FIT narrowed to 2024 weeks 3-15** (prior SP+ 2023 + 2024 in-season PPA, 14 CFBD calls,
  654 FBS-vs-FBS games). 2023 would need 2022 SP+, which no local copy holds. The blend beta
  44.66 was fit on 2024, so the NCAAF FIT ratings are in-sample for beta -- irrelevant to a
  scenario-rate comparison, stated anyway.
- **Seeds:** 300 (production's), measured ~17 s/game warm on this machine.

## Engine structure read from CODE (not from the sample) — Phase 2 candidates

- **No halftime kickoff.** `possession_state.advance_quarter` (`:59`) only increments the
  quarter and resets the clock. At the half, the team holding the ball KEEPS it at the SAME field
  position; in football the other team receives a kickoff. Surfaced by S12 "start fp after half"
  (an interim 41-game read: sim 34.6 vs real 25.8), confirmed in code.
- **Fourth-down go-for-it is reachable only in Q4, <= 300 s, trailing, outside FG range**
  (`drive_simulator.py:~250`). Everywhere else 4th down is punt/FG by the ladder. Interim read:
  4th-and-1-2 inside the opp 30, real P(go) 0.667 vs sim 0.018.
- **Turnover probability does not move with team quality** -- interim S1 by rating-gap tercile:
  sim 0.108/0.114/0.113 (weak/mid/strong offense) vs real 0.145/0.087/0.079. The turnover weight
  (`play_simulator.py:130`) reads `priors.turnover_probability` and situation, not the
  offense-vs-defense gap -- to be traced before any claim.
- **No non-offensive scoring** (S11) and **no kickoff variance** (S12 after-score = 25 always).

These are stated for ranking only; no number from the 41-game interim is a result.

## H1 halftime kickoff — PRE-REGISTERED 2026-10-06 (user: "fix the halftime kickoff bug now")

- **Mechanism:** `CalibrationProfile.halftime_kickoff: bool = False`. When ON, at the Q2 -> Q3
  transition possession goes to the team that did NOT receive the opening kickoff, at the engine's
  kickoff spot (own 25, the same convention as after a score), 1st and 10. Pregame: opening
  receiver = `initial_possession_owner`, so the 2H receiver is the other team. A resume that
  starts in Q1/Q2 does not know the opening receiver -> a fair coin from the game rng (consumed
  ONLY when the switch is on). A resume at Q3+ never crosses the half and is unaffected.
- **No new input field** (an unfed one would trip `football_sim_input_checklist.py`).
- **Byte-identity (OFF):** sha256 over 2 default profiles x 40 seeds x 3 start states
  (pregame, Q2 resume, Q3 resume) = `defba53b...f99238b` before the change; must be equal after.
- **Reachability:** ON != OFF on the same seeds; S12 "start fp after half" sim == 25.0 with ON.
- **Predictions (FIT, production ratings, same seeds):** S12 after-half 34.6 -> 25.0 (NFL);
  no direction predicted for mean total or margin, |delta mean total| < 1.0 pt per game.
- **Not shipped ON by this change.** Both production profiles were calibrated with the bug in
  place (`model_engine_standard.md` §4.4), and pushing a default-ON engine change reaches the
  local fleet on its next fast-forward. Turning it on is a separate decision, made on the on-vs-off
  measurement over the FIT games.

## H2 fourth-down decision model — PRE-REGISTERED 2026-10-06 (user: "fix the 4th down go-for-it logic too")

**What the code does today** (`drive_simulator.py`): at 4th down, (1) go only if Q4 <= 300 s,
trailing, outside FG range; else (2) `_field_goal_decision` -- in range it kicks with p 0.58..0.97
by field position ONLY, never reading yards-to-go; else (3) `_punt_decision` ladder; else (4) an
implicit go at a guessed conversion `0.52 - 0.06*(d-2)` (the late branch: `0.62 - 0.05*(d-2)`),
both times `fourth_down_conversion_multiplier` (NCAAF 0.55, fit to its turnover-on-downs rate).
Go is the RESIDUAL of two kick ladders, so inside the 30 it is ~never chosen.

- **Mechanism:** `CalibrationProfile.fourth_down_decision_model: bool = False`. When ON, steps (2)-(4)
  are replaced by one draw of go / fg / punt from a MEASURED table P(decision | field-position
  bucket, to-go bucket) for the profile's sport, and a go converts with a MEASURED P(convert |
  to-go bucket) -- the multiplier is NOT applied on top (it was absorbing the guessed formula).
  Steps (1) and the urgency-FG rule run first, unchanged. Gain on a conversion, FG make, and punt
  result: unchanged code.
- **Buckets:** field position (yards from own goal) <40, 40-49, 50-59, 60-69, 70-79, 80-89, 90+;
  to-go 1, 2, 3-4, 5-7, 8-10, 11+.
- **Population (FIT only):** NFL 2023-24 REG, `down == 4`, play_type pass/run/punt/field_goal,
  `aborted_play` excluded; NCAAF 2024 FBS-vs-FBS REG, CFBD 4th-down scrimmage plays. EXCLUDED: the
  states the engine already handles -- Q4 <= 300 s with the offense trailing (step 1), and Q2/Q4
  <= 90 s, field position >= 65, score diff -9..+2 (urgency FG).
- **Decision:** go = pass/run (fakes count as go), fg = field goal attempt, punt = punt.
- **Conversion:** go attempts; NFL `fourth_down_converted == 1`; NCAAF yardsGained >= distance or an
  offensive TD.
- **Smoothing:** each cell's counts + 10 x its field-position bucket's pooled proportions; every
  cell's n is written next to it in the code.
- **Tables live in** `situation_model.py` (claimed), with n and provenance.
- **Byte-identity OFF**, same 3-start-state sha as H1 (with H1 OFF). **Reachability:** ON != OFF,
  and with ON the sim's S5 rates sit inside the real 95% CI on the FIT games (a construction
  check, not evidence of skill).
- **Predictions (FIT, paired seeds):** more go-for-its inside the 40 -> fewer FG attempts, more
  TDs and more turnovers on downs. NFL mean total change in [-0.5, +1.5] points/game; S4
  P(FGA|RZ) falls toward the real 0.34. No prediction on accuracy vs results or the close.
- **Not shipped ON** for the same reason as H1.

## H3 non-offensive scoring — PRE-REGISTERED 2026-10-06 (user: "fix the no non-offensive scoring gap too")

**Code today:** a sim TURNOVER scores 0 (`possession_outcomes.classify_outcome`, `play_simulator`
turnover branch), punts and the implicit kickoff after a score (own 25) never return for a TD,
and no snap can end in a safety. S11 real (parser check): NFL 1.90 pts/game, NCAAF 2.40.

- **Mechanism:** `CalibrationProfile.non_offensive_scoring: bool = False`. When ON, in
  `simulate_drive` (no change to `play_simulator`):
  - drive ends in TURNOVER -> with p_def_td the defense scores 7, then kicks off to the team that
    turned it over (own 25);
  - drive ends in PUNT -> with p_punt_ret_td the receiving team scores 7, then kicks off;
  - drive ends in TD or FG with clock remaining -> with p_ko_ret_td the receiving team scores 7 on
    the kickoff, then kicks off back (own 25);
  - before an ordinary snap (not a 4th-down decision) from field position <= 10 -> with
    p_safety[bucket] the defense scores 2 and receives the free kick at the measured start spot.
    New `PossessionOutcome.SAFETY` terminal outcome (an added enum member; no existing value changes).
  - TD = 7 (the engine's convention). Every rng draw happens only when ON.
- **Rates (FIT only; NFL 2023-24 REG nflverse, NCAAF 2024 FBS-vs-FBS REG CFBD):**
  - p_def_td = defensive return TDs / turnovers (NFL: interception or fumble_lost on pass/run,
    `return_touchdown` and `td_team == defteam`; NCAAF: Interception/Fumble playTypes, the
    *Return Touchdown* ones in the numerator);
  - p_punt_ret_td = punt return + blocked punt TDs by the receiving team / punts;
  - p_ko_ret_td = kickoff return TDs / kickoffs;
  - p_safety by field position 1-5 and 6-10 = safeties / scrimmage snaps from there;
  - free-kick start = mean start field position of the drive after a real safety.
- **Byte-identity OFF:** the same sha (`defba53b...`). **Reachability:** ON != OFF; with ON the sim's
  S11 non-offensive points/game is within the real 95% CI on the FIT games.
- **Predictions (FIT, paired seeds):** mean total +1.5..+2.3 (NFL) / +1.8..+2.9 (NCAAF) per game
  with no re-fit (the sim's turnover and punt counts are close to real, S1); margin change
  |delta| < 0.3; total SD up. As for H1/H2: **not shipped ON** -- the scoring level was fitted
  without these points, so ON alone will over-project totals until the joint re-fit.

## H4 possession-aware drive priors — PRE-REGISTERED 2026-10-06 (user: "Fix it as H4, include in re-fit")

**Found while setting up the re-fit.** `drive_priors.build_drive_priors:339-340` seeds the drive
priors (drive success, turnover, explosive, ...) from `0.5 + home_offense_rating` and
`0.5 + home_defense_rating` for EVERY drive. Measured, not inferred: an away possession's
drive_success is 0.327 neutral, 0.327 with away offense +0.3 (unchanged), and 0.369 with HOME
offense +0.3. The away team's drives use the home offense, and the home team's drives face the
home team's OWN defense. Only per-play yardage (`play_simulator.py:383`) picks the right team.
Same sign convention on both sides (defense rating = -EPA allowed; higher = better).

- **Mechanism:** `CalibrationProfile.possession_aware_priors: bool = False`. ON: the possessing
  team's offense rating and the OPPONENT's defense rating seed the priors.
- **Lever added for the re-fit:** `CalibrationProfile.home_field_bonus: float = 0.0`, added to the
  possessing team's offense rating when the home team has the ball, in both the play and the
  drive-prior paths. There is no home-field term in the engine today -- the sim's home edge came
  from structure (home receives the opening kick; under the halftime bug it often kept the ball),
  measured as +1.1 -> +0.26 pts when H1 is switched on.
- Byte-identity OFF/0.0 on the same sha; reachability `off != on`; a test that the away drive
  moves with the away offense when ON.

## JOINT RE-FIT — PRE-REGISTERED 2026-10-06 (user: "set up the joint re-fit with all three switches on"; H4 added by user decision)

**Arm under test:** production's profile with `halftime_kickoff`, `fourth_down_decision_model`,
`non_offensive_scoring`, `possession_aware_priors` ALL ON, plus re-fitted levers. **Baseline:**
production as shipped (all OFF). Per sport; NFL and NCAAF fitted separately.

**FIT set:** every 4th FIT game (NFL 2023-24: 136 games; NCAAF 2024 wk3-15: ~164), through
production's own `build_projection` and env, **60 seeds** per game in the descent (300 for the
final reads). The SAME games and seeds in every arm.

**Moments (targets from the REAL FIT games, same harness counters):** game level -- mean total,
mean home margin, SD(actual total - sim mean) vs mean sim total SD, same for margin; drive level --
P(TD), P(FG), P(punt), P(TO), plays/drive, drives/team-game, P(TD|RZ); rating sensitivity --
pts/drive in the weak and strong rating-gap terciles. Standardised error z = (sim - real) / SE_real
(game-clustered bootstrap). **Objective = sum of z^2.**

**Levers (coordinate descent, 2 passes, a move is kept only if the objective drops):**
`home_field_bonus` {0, 0.03, 0.06, 0.09, 0.12}; `drive_yardage_multiplier`,
`touchdown_weight_multiplier`, `red_zone_touchdown_weight_bonus`,
`field_goal_attempt_base_probability` (grids around the shipped value, +-~25%);
`drive_success_offense_sensitivity`, `drive_success_defense_sensitivity` {0.6, 0.8, 1.0, 1.2}.
Any lever not shown reachable (`off != on` on one game) is dropped and the drop recorded.
Measured rates from H2/H3 are FIXED, never levers.

**VALIDATION (2025, read ONCE, 300 seeds, re-fit arm vs production), all must pass:**
- (a) the objective on 2025 is >= 20% lower than production's;
- (b) no moment's |z| grows by more than 1.0;
- (c) margin MAE vs actual: paired delta upper 95% CI < +0.15 pts;
- (d) total MAE vs actual: paired delta upper 95% CI < +0.15 pts;
- (e) home-win Brier vs actual: paired delta upper 95% CI < +0.003;
- (f) |sim - close| for total and margin (NFL nflverse close; NCAAF CFBD close): upper CI < +0.15.
If any fails, nothing ships and the failure is recorded. If all pass, the result is a CANDIDATE
profile artifact (`save_versioned_profile`) and a recommendation -- promotion to the fleet is a
separate user decision, and the lane's mid-drive LIVE replay gate is still owed before it.

### Re-fit amendment 2 — 2026-10-06, after a 6-game/10-seed SMOKE run, BEFORE the full descent

The smoke run (plumbing only; `refit_smoke/`, nothing from it is a result) showed:
- `field_goal_attempt_base_probability` is UNREACHABLE with `fourth_down_decision_model` ON (the
  measured table replaces the FG ladder) -- dropped by the reachability check, as designed. FG
  frequency is the most-missed moment (Phase 1: 0.137 vs 0.155), so the FG lever becomes
  `field_goal_weight_multiplier` (`play_simulator.py:137`), same grid rule.
- two kept values sat on a grid edge -> a kept edge value gets ONE further step after pass 2
  (x0.875 / x1.125, or one grid step for absolute levers), kept only if the objective drops.
Nothing else changes.

### Re-fit amendment 3 — 2026-10-07 00:1xZ, NFL validation STOPPED before any result was read

User: "validate NFL now, don't wait for NCAAF". The first NFL 2025 run (marker 00:08:33Z) reused the
descent's every-4th-game subset, which would have graded on ~68 of 2025's games -- the pre-registration
says nothing about subsampling VALIDATION, and 68 games cannot resolve gates (c)-(f). Stopped within
minutes; `validation_s300.jsonl` held ~10 KB of production-arm game sims (deterministic, cached,
NOT read -- no moment, gate or score was computed). Fixed: `validate` scores EVERY 2025 game
(`Evaluator(..., every=1)`), resumed with `--resume`. Nothing else changes; NCAAF's validation uses
the same rule.

## LIVE mid-drive replay gate — PRE-REGISTERED 2026-10-07 (user: "start the mid-drive live replay harness while that runs")

The lane's Verification names a mid-drive live replay; the existing live backtests resume only at
quarter ends with the clock at 0:00. `scripts/football_scenario_replay.py`:

- **Engine path = production's own live functions**, called with a `profile` argument:
  `nfl/live_resim.resim_live_game` and `ncaaf/live_resim.resim_live_game`. Ratings as the live tick
  feeds them: NFL raw `team_rating` as-of the week (the ratings artifact, no level shrink); NCAAF the
  raw as-of SP+/PPA blend with the function's OWN live level shrink (`level_shrink=None`).
- **Two deliberate departures, both identical across arms:** the publish-time output guard
  (`UNINFORMATIVE_BAND`) is disabled, because it refuses close states and would drop them from the
  grade (this grades the ENGINE, not the publication gate); `rating_sd = 0`. Sims 300 per state (the
  tick uses 120), seeds 1..300 in both arms.
- **States:** every VALIDATION game (2025 REG; NCAAF FBS-vs-FBS weeks 3-15); per game ONE scrimmage
  snap drawn per regulation quarter (4 states), seeded by (game id, quarter), clock > 0. Down,
  distance, field position in the possessor's frame, possession owner, and the score AT THE START
  of the snap (NFL `posteam_score`/`defteam_score`; CFBD `offenseScore`/`defenseScore`).
- **Arms:** production profile vs the descent's candidate overrides (`descent_result.json`).
- **Metrics per state:** Brier of P(home win) (raw share, ties = 1/2) vs the final result; abs error
  of the projected final margin and total. Paired candidate - production, game-clustered bootstrap.
- **Live gates (all must pass, same tolerances as pregame):** (L1) Brier delta upper 95% CI < +0.003;
  (L2) margin abs-error delta upper CI < +0.15; (L3) total abs-error delta upper CI < +0.15. By-quarter
  rows are reported for information only.
- **2025 read ONCE per sport** (its own marker); development runs use FIT seasons only.

## RE-FIT v2 — PRE-REGISTERED 2026-10-07 (user: "Hold it, fix the objective first")

**NCAAF 2025 status:** the v1 NCAAF validation started automatically at 01:35:52Z when the NCAAF
descent finished, and was PAUSED ~17 min later (processes killed, no orphans) after the NFL v1
failure: game sims only, `validation_report.json` never written, no moment, gate or score
computed. NCAAF 2025 is UNREAD. The v1 NCAAF candidate (offense sensitivity 0.6, TD weight 0.48,
home bonus 0.03) is NOT validated and is superseded by v2.

**What changes from v1 (everything else as pre-registered for v1):**
1. **Discrimination moments added** -- the v1 objective was satisfiable by compressing team
   quality. `margin_slope`: OLS slope of the ACTUAL home margin on the projected margin across the
   FIT games (target 1.0; compression drives it above 1). `total_slope`: same for totals. SE by a
   game-clustered bootstrap of the slope with production's projections held fixed. z = (slope - 1)/SE.
   Outcome-based on purpose -- the close is a gate, never a fit target.
2. **FG lever:** both FG levers are unreachable with the 4th-down model ON, and the gap is drive
   progress (P(reach RZ) 0.253 vs 0.298), not the 4th-down choice. Add `red_zone_gain_stiffening`
   (multiplicative grid as the others) -- drives that stall in the red zone kick.
3. Output to `refit_v2/`; v1 files kept as the record.

**Validation sets:**
- **NCAAF: 2025**, unread; gates (a)-(f) and L1-L3 as pre-registered.
- **NFL: 2026 REG games completed at read time**, fetched fresh from nflverse into a PRIVATE root
  (the shared `data/nfl_source` mirror is not written). NFL 2025 is spent (v1 read). **Read only once
  >= 128 completed 2026 games exist** (about week 8, late October); below that the paired CIs cannot
  resolve the 0.15-pt tolerances and the read would waste the set. Same gates (a)-(f), L1-L3.

### v2 amendment 1 — 2026-10-07, BEFORE any v2 run: the v1 diagnosis was backwards

Measured on the CACHED v1 FIT descent sims (136 NFL 2023-24 games, 60 seeds; no new sims, no 2025):

| arm | SD(projected margin) | corr(projected, actual) | corr(projected, close) | margin slope (actual on projected) |
|---|---|---|---|---|
| close line | 5.81 | 0.492 | -- | -- |
| production | 6.10 | 0.396 | 0.850 | 0.88 |
| v1 candidate | **7.92** | 0.406 | 0.855 | **0.70** |

The v1 candidate's projected margins are ~30% MORE spread than production's for the same information
-> OVER-dispersion, which is what moved per-game margins away from the outcome and the close. The
sensitivity cut to 0.6 was the descent partly FIGHTING that spread, with nothing in the objective to
see it. Source, as a HYPOTHESIS only: H4 -- with both rating paths reading the right teams, team
differences now count in full, where the defect partly cancelled them. v2's slope moment is still the
right instrument (slope < 1 = over-dispersion). **Amendment:** the two `drive_success_*_sensitivity`
grids widen to {0.3, 0.45, 0.6, 0.8, 1.0, 1.2} so the descent can reach the dispersion the slope asks
for. Nothing else changes.

## Results

### Phase 1, NFL (2023-24 REG, all 544 games, 300 seeds; real-vs-sim, flag rule as pre-registered)

Coverage: sim 544, real 544, intersection 544. Flagged (outside real 95% CI AND >= 0.25 pts/team-game):
- P(TD)/drive real 0.214 [0.206, 0.222] vs sim 0.231 (+1.32 pts/tg); P(FG)/drive 0.155 vs 0.137 (-0.57);
  pts/drive 1.952 vs 2.030 (+0.85). Worst for the WEAK rating-gap tercile: pts/drive 1.631 vs 1.752 (+1.32).
- Game level: real home margin +2.28 vs sim +1.08; total SD of residuals 13.37 vs the sim's own 11.80
  (over-confident on totals); H1 points 22.57 vs 20.99; P(OT) 0.053 vs 0.036; non-offensive pts 1.90 vs 0.
- 4th down inside the opp 30 on 1-2 to go: real P(go) 0.66 vs sim 0.02 (H2). Start after the half 26.4 vs 34.8 (H1).

### H1 / H2 paired, NFL (136 FIT games = every 4th, 300 seeds, same seeds; ON - OFF, game-clustered 95% CI)

| | mean total | home margin | MAE total / margin vs actual | Brier | abs(sim - close) total / margin |
|---|---|---|---|---|---|
| H1 halftime | -1.12 [-1.22, -1.03] | -0.85 [-0.97, -0.72] | +0.11 [-0.09, +0.31] / +0.10 [-0.09, +0.28] | 0.000 | -0.06 [-0.26, +0.14] / **+0.23 [+0.05, +0.40]** |
| H2 4th down | +0.67 [+0.53, +0.80] | +0.26 [+0.11, +0.40] | +0.08 [-0.08, +0.23] / -0.07 [-0.22, +0.07] | +0.001 | **+0.28 [+0.12, +0.43]** / +0.01 |

H3 (same 136 games): mean total +1.63 [+1.51, +1.76] (prediction +1.5..+2.3 HELD), home margin
+0.41 [+0.23, +0.58] (prediction |delta| < 0.3 FAILED), sim total SD +0.47 [+0.37, +0.59] (toward the
realised 13.4), MAE margin -0.15 [-0.34, +0.03], Brier -0.004 [-0.011, +0.002],
abs(sim - close) total **+0.45 [+0.16, +0.72]**.

### Joint re-fit descent, NFL (136 FIT games, 60 seeds; objective = sum z^2 over 13 moments)

Production 56.98 -> switches ON at shipped levers 124.82 -> **fitted 40.22 (-29% vs production)**.
Fitted: all four switches ON, `drive_yardage_multiplier` 0.875, `touchdown_weight_multiplier` 1.25,
`drive_success_offense_sensitivity` 0.6, `drive_success_defense_sensitivity` 0.6, `home_field_bonus`
0.12. DROPPED as unreachable with the 4th-down model ON: `field_goal_attempt_base_probability` (smoke)
AND `field_goal_weight_multiplier` (full run) -- FG attempts now arise only from the measured 4th-down
table, so no FG-frequency lever exists. Residual misses at the fit: P(FG)/drive z -4.9, plays/drive
z +2.5. Home-field bonus HURT in pass 1 and was kept at 0.12 in pass 2, after yardage/TD weight
moved -- the coupling a one-lever-at-a-time read would have missed. Edge steps tried, none kept.

### NFL VALIDATION 2025 — NOT SHIPPABLE (read 2026-10-07, 272 games, 300 seeds, candidate vs production)

| gate | result | detail |
|---|---|---|
| (a) objective >= 20% lower | FAIL | production 122.48, candidate 239.63 |
| (b) no moment's abs z grows > 1 | FAIL | worst +6.38 (P(FG)/drive z -5.11 -> -11.49) |
| (c) margin MAE | **FAIL** | +0.366 [+0.057, +0.691] |
| (d) total MAE | FAIL (tol) | -0.186 [-0.540, +0.174] |
| (e) home-win Brier | FAIL (tol) | +0.0072 [-0.0002, +0.0148] |
| (f) abs(sim - close) margin | **FAIL** | +0.848 [+0.575, +1.117] |
| (f) abs(sim - close) total | PASS | **-0.691 [-0.991, -0.400]** |

z (production -> candidate): mean_total -2.68 -> -1.22, mean_margin -1.32 -> +0.10, total_sd_gap
-3.55 -> -1.13, p_fg -5.11 -> -11.49, p_punt +2.88 -> +6.44, plays/drive +6.04 -> +2.75,
drives/team-game +3.65 -> +6.06, ppd_weak -0.55 -> -2.95.

**Diagnosis (stated as findings, not as excuses -- nothing ships):**
1. **[RETRACTED 2026-10-07 -- see "v2 amendment 1"; the candidate is OVER-dispersed, not compressed]**
   ~~The objective could be satisfied by COMPRESSING team quality.~~ Both drive-success
   sensitivities went to 0.6; every moment is an aggregate MEAN, so nothing in the objective saw
   per-game discrimination. Mean margin was fixed (z +0.10) while per-game margins got worse and moved
   0.85 pts further from the close. A next design must carry a discrimination moment (e.g. SD of the
   projected margins vs SD of the close spreads, or slope of actual on projected margin).
2. **No FG-frequency lever exists with the 4th-down model ON** (both FG levers unreachable), and 2025's
   FG share sits further from the sim than 2023-24's did; drives/game and punts overshoot with it.
3. **The scenario fixes DO move the total the right way:** abs(sim - close) total -0.69 with a CI
   excluding 0, total MAE leaning better, total SD gap -3.55 -> -1.13.
4. **2025 is now READ for NFL pregame.** Any next NFL candidate needs a different held-out set (2026
   weeks to date, or a fresh pre-registered split); 2025 cannot be re-used as a clean gate.

### NFL LIVE replay, v1 candidate, 2025 (INFORMATIONAL -- NFL 2025 already spent by the v1 pregame read)

260 games, 1,040 mid-drive states (4/game), 300 sims/state/arm; refused 48 states (`degenerate_ratings`,
identical in both arms). Candidate - production, game-clustered: L1 Brier -0.0010 [-0.0057, +0.0037]
FAIL (tol), L2 margin abs err +0.018 [-0.139, +0.194] FAIL (tol), L3 total abs err -0.078
[-0.239, +0.101] PASS. Production live: Brier 0.163, margin err 7.16, total err 7.54. In-game the v1
candidate is neutral-to-slightly-better; the pregame over-dispersion matters less once the score is known.

v2 runs launched 2026-10-07 ~02:2xZ (both descents, `refit_v2/`). NCAAF v2 validation + live replay
queued behind its descent. 142 production-arm NCAAF 2025 game sims from the paused v1 read were carried
into the v2 cache (deterministic, never analysed). NFL v2 validation waits for >= 128 completed 2026
games (pre-registered).

### Re-fit v2 descent, NFL — DONE 2026-10-07 (136 FIT games, 60 seeds; objective incl. the slope moments)

Production 61.28 -> **fitted 29.17 (-52%)** (v1 reached -29% on its own, slope-free objective). Fitted: all
four switches ON, `drive_yardage_multiplier` 0.875, `touchdown_weight_multiplier` 1.125,
`red_zone_touchdown_weight_bonus` 0.2475, `red_zone_gain_stiffening` 0.6, `home_field_bonus` 0.09,
`drive_success_offense_sensitivity` 0.6, `drive_success_defense_sensitivity` 0.6. Fitted z: P(FG) -3.73
(v1 -4.9; still the worst moment), plays/drive +2.24, mean margin -1.50, margin slope -1.33 (slope still a
little under 1 -- mild over-dispersion, far less than v1's 0.70), total slope +0.33, mean total -0.54.
**VALIDATION waits for >= 128 completed 2026 NFL games (pre-registered; ~late October).** NCAAF v2 descent
still running (30 evals, nothing below production 227.5 yet); its 2025 validation is queued behind it.

**v2 amendment 2 (2026-10-07, user: "Validate only if FIT beats production"), before NCAAF 2025 is read:** after 42
NCAAF evals nothing had beaten production (227.5) on the FIT games, and the queued watcher would have spent the
one-time NCAAF 2025 read whatever the descent found. The watcher was replaced (old one stopped, no orphans,
`VALIDATION_READ_2025` absent): the 2025 read (pregame gates + live replay) now runs ONLY if the fitted objective
is <= 0.8 x production's on FIT -- gate (a)'s own bar. Otherwise NCAAF 2025 stays UNREAD and the result is reported.

### Re-fit v2 descent, NCAAF — DONE 2026-10-07 23:58Z: GATE HELD, NCAAF 2025 UNREAD

Production 227.55 -> switches ON at shipped levers ~381 -> **best fitted 262.50 (15% WORSE than production)**.
Fitted: four switches ON, `drive_yardage_multiplier` 0.8312, `touchdown_weight_multiplier` 0.6875,
`red_zone_touchdown_weight_bonus` 0.435, `red_zone_gain_stiffening` 0.525, `home_field_bonus` 0.12,
`drive_success_offense_sensitivity` 0.3, `drive_success_defense_sensitivity` 0.45. The FIT gate (<= 0.8 x
production) returned HOLD: the 2025 read did not run and no 2025 marker exists (the only 2025 file holds the
unanalysed production-arm sims carried over from the paused v1 read). **Reading:** with the scenario switches ON,
no combination of the available levers brings the NCAAF engine back to production's fit on 2024 -- the switches
cost NCAAF more than the levers can recover. NCAAF keeps production as shipped; any NCAAF re-fit needs a
different lever set or a per-switch selection (e.g. NCAAF without H4 / H3), pre-registered as a new step.

H1 prediction (|delta total| < 1.0) FAILED (-1.12). H2 prediction (total in [-0.5, +1.5]) held. Both
fixes work mechanically (S12 after-half 25.0; S5 4th-down rows inside the real CI) and neither moves
accuracy alone -- each moves the level or home edge away from the close, as the re-fit design expects.

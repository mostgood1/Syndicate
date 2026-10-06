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

## Results

(none yet -- NFL 544-game run in progress, then NCAAF 654)

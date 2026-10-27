# Basketball player distribution — lane `basketball-player-distribution`

Opened 2026-10-26 at the user's request ("as we tune game stats, we should do potential team/player modeling based on
pbp and rotations"). Engine: the NBA native engine, round-2b + #5b candidate config (fit_5bA_config.json in
findings_2026-10-06_basketball_scenario_calibration.md).

## Prior facts (measured elsewhere)

- **The served NBA prop sd is too narrow:** IQR(z)/1.349 is pts 1.52, reb 1.44, ast 1.39, pra 1.85 (2026-10-03,
  state `[nba-model-skill-2025-26]`). That is AFTER the calibration layer; the raw engine was never read.
- **The engine reports a player's INPUT minutes in the box** (`finalize`: `"min": _sim_min`), constant across draws.
  Simulated playing time varies only through the lineup sampler / pool, and is not reported.

## PHASE 1 — PRE-REGISTRATION 2026-10-26 13:20Z

**Instrument** (research only, never on main):
- The research engine copy counts, per draw, each player's on-floor possessions (both lineups at every possession
  iteration) and the iteration count.
- Simulated minutes = game minutes (48 + 5·OT) × on_i / n.

**Recorder:** the harness flag `--record-player-draws` (on main; default off, so output is unchanged) writes per draw,
per player (game-fixed order), [pts, reb, ast, threes, sim_min].

**Run:** the fit_5bA config on the full 2025-26 FIT window (109 dates), 200 draws, 3 workers at nice 19.

**Truth:** ESPN summary player boxes (C:/tmp/bball_sc/cache/nba/summary_<event>.json.gz; MIN > 0 = played), joined
by normalised name.

**Population:**
- player-games where the player is in the sim AND played;
- separately counted: sim-only (DNP in reality) and real-only (not simulated).

**Per stat** (min, pts, reb, ast, threes), from the 200 draws:
- the randomised PIT u = P(X < y) + U·P(X = y);
- tail coverage, P(u < .1) and P(u > .9) (nominal .10 each);
- the central-80% miss = their sum (nominal .20);
- the width ratio = sd(y − sim mean) / rms(sim sd);
- the bias = mean(y − sim mean).
- CIs from a game-clustered bootstrap (2,000).

**Splits:**
- starters (top-5 by input minutes) / bench;
- close (final abs margin ≤ 10) / blowout (≥ 20).

**Decomposition:**
- (a) MINUTES: the sim minute coverage vs actual, and the input-minutes bias;
- (b) a MINUTES-ORACLE arm: each draw's stat × (actual min / that draw's sim min), stats only. If the central-80% miss
  falls to within ±.05 of .20, the width deficit is minutes; otherwise the residual is the per-minute rate / width.

**FLAG rule:** a stat × role cell is FLAGGED when its central-80% miss lies outside [.15, .25] with the CI excluding
.20.

**Lane falsification:** every stat's overall miss is within ±.05 of .20 → the engine is EXONERATED and the narrowness
is downstream.

Phase 2 (mechanisms from pbp / rotation stints) is pre-registered only after this read. Minutes mechanisms are
coordinated with the nba-sim-minutes lanes.

## PHASE 1 — RESULT 2026-10-27 12:47Z

**Run:** fit_pd, the fit_5bA config + `--record-player-draws` + the research on-floor counter. 109/109 dates, 0
errors, finished 2026-10-26 15:27Z. Readout 4466540a; JSON at C:/tmp/bball_sc/r2s/phase1_read.json.

**Population:**
- 802 games; **14,291 player-games** simulated AND played;
- excluded: **3,513 sim-only** (simulated, did not play), **2,980 real-only** (played, not simulated), and 4 games
  with no real record.
- The two exclusions are about 20% each. Some of that may be name-join misses; not yet separated.

**Central-80% miss** (nominal .20; FLAG = outside [.15, .25] with the CI excluding .20):

| stat | all | starters | bench | close | blowout | width ratio (all / bench) | **minutes-oracle miss** (width) |
|---|---|---|---|---|---|---|---|
| **min** | **.430** F | .322 F | **.543** F | .446 F | .412 F | **1.57 / 2.03** | — |
| pts | .319 F | .293 F | .347 F | .333 F | .297 F | 1.25 / 1.38 | .255 F (1.01) |
| reb | .300 F | .268 F | .333 F | .300 F | .306 F | 1.27 / 1.45 | .263 F (1.05) |
| ast | .274 F | .272 F | .277 F | .277 F | .266 F | 1.23 / 1.32 | **.244** (1.03) |
| threes | .243 | .243 | .243 | .243 | .254 F | 1.13 / 1.21 | **.220** (0.96) |

95% CIs are about ±.007–.012 overall.

**Biases** (y − sim mean):
- minutes +0.29 overall: starters −0.86, bench +1.49;
- input minutes vs actual +0.20;
- pts / reb / ast / threes within ±0.06 overall; bench pts +0.43, starters pts −0.38.

**Verdict:**
- **The engine is NOT exonerated.** The lane falsification fails: no stat except threes is within ±.05 of .20.
- **Minutes are the dominant defect.** The sim's minute distribution is far too narrow (width 1.57; bench 2.03,
  bench miss .54).
- **Under oracle minutes,** every stat's width ratio falls to about 1.0 (0.96–1.05), and the miss falls:
  - pts .319 → .255; reb .300 → .263;
  - ast .274 → .244 (passes); threes .243 → .220 (passes).
- So most of the excess width is minutes. The residual for pts and reb (.255 / .263, width about 1.0) is
  shape/asymmetry, not width. Under the oracle, pts lo .149 vs hi .106, bias −0.19: the sim's per-minute scoring
  runs slightly high for low outcomes.

**Phase 2 direction (to be pre-registered; not started):**
- (1) **Minutes variance** from play-by-play / rotation stints. A per-player per-game minutes draw (empirical
  stint-based variability: rotation depth, foul trouble, blowouts, DNP risk) feeds the engine's lineup weights.
  Coordinate with the nba-sim-minutes lanes, which own the pool / allocation.
- (2) **The 3,513 / 2,980 population gaps:** first separate join misses from real DNP / unsimulated players.
- (3) **The pts / reb residual shape:** after (1).

## PHASE 2 STEP 1 — POPULATION GAPS — PRE-REGISTRATION 2026-10-27 12:50Z (user: "start on step 1")

**Question:** what are the 3,513 sim-only and 2,980 real-only player-games? Descriptive, no gate. Same fit_pd draws
and ESPN cache; the classification is per team, per game.

**Sim-only** (simulated, no MIN > 0 in the box), first matching class wins:
- **JOIN:** a real-only player on the same team whose normalised name matches, by difflib ratio ≥ 0.80 OR same last
  name + same first initial.
- **DNP_LISTED:** on the box with didNotPlay. Reason split: COACH'S DECISION vs other.
- **ABSENT:** not on the box at all (inactive / injured / not with the team).

**Real-only** (played, not simulated), excluding JOIN.

**Reported:**
- counts and shares;
- the sim minutes held by each sim-only class per team-game (mean sim minutes, on-floor counter);
- the actual minutes held by real-only players per team-game, with a ≥ 10 min share;
- per-month counts (a season drift check).

**Use:** JOIN is a readout defect, so fix the join and re-read Phase 1. DNP_LISTED / ABSENT are minutes-allocation
inputs (pool / injury feed), so hand them to the nba-sim-minutes lanes with the numbers. Real-only are pool omissions.

## PHASE 2 STEP 1 — RESULT 2026-10-27 12:59Z

Data: fit_pd, 1,604 team-games; `--gaps` mode of the readout; JSON at C:/tmp/bball_sc/r2s/phase2_gaps.json.

| class | player-games | sim min per team-game | mean sim min per player | note |
|---|---|---|---|---|
| JOIN | 5 | 0.1 | 31.6 | **all 5 false positives** (Giannis~Thanasis, Stephen~Seth Curry, LeBron~Bronny): real join misses ≈ 0 |
| DNP_LISTED (coach's decision) | 1,243 | 7.1 | 9.1 | rotation / depth: the sim plays them |
| DNP_LISTED (other: injury / rest / suspension) | 295 | 4.5 | **24.3** | injury feed: listed injured, sim gives starter-like minutes |
| ABSENT (not on the box) | 1,978 | **19.8** | 16.1 | inactive / injured / not with the team |
| REAL_ONLY (played, not simulated) | 2,983 | **29.6 actual min** per team-game | 15.9 actual | 67% played ≥ 10 min |

**Reading:**
- **The Phase-1 join is sound.** The readout is not the source of the 3,513 / 2,980.
- **About 31 sim minutes per team-game go to players who do not play, and about 30 real minutes go to players the
  sim never had.** That is about 12–13% of a team's 240 minutes on the wrong people, before any distribution
  question.
  - This matches the production finding of the nba-sim-minutes-allocation lane (10-21: 37.7 DNP sim min/side).
- The ABSENT examples show two patterns:
  - (a) **equal water-filled minutes:** IND 2025-11-01 had 8 absent players at ≈ 12.5 sim min each;
  - (b) **players the sim placed on a team whose box does not list them at all.** IND 2025-11-01 lists Ivica Zubac
    (12.6 sim min).
  - REAL_ONLY includes high-minute players: SAC 2025-11-01 Dennis Schröder, 37 min, not simulated.
  - Both point to the backtest's as-of ROSTER / pool inputs: stale or leaked rosters, the injury feed, the
    equal-split fill. **Believed, not verified:** whether (b) is a leak from a later roster or a real early-season
    transaction. Owed: a per-example roster check.
- **Phase-1 consequence:** the 14,291 matched player-games are the players BOTH sides had. The minutes-distribution
  defect (miss .43) is measured on them alone; the misallocation above is on top of it.

**Hand-off:** the misallocation is input (pool / roster / injury) territory, owned by the nba-sim-minutes-allocation /
-history-path lanes. Numbers above; examples in the JSON.

**Next for this lane:**
- (i) the roster check on the ABSENT / REAL_ONLY examples (leak vs transaction);
- (ii) the minutes-variance mechanism (Phase 2 step 2), measured on the matched population so it is separable from
  the pool fix.

## CROSS-CHECK WITH E4 (decision-engine brief ac91362d) — 2026-10-27 13:03Z

**E4 (production served P/R/A):** within-player Var(PRA) / [Var(P) + Var(R) + Var(A)] median **0.997** (846
player-games), against **1.196** in real boxes. Its attribution: minutes held fixed across draws.

**The raw engine** (fit_pd draws, the same statistic, 13,317 player-games with ≥ 15 sim min):
- median **1.142**;
- the per-minute version **0.959**;
- corr(sim minutes, pts) median **0.410**.

**Reading:**
- The raw engine's simulated playing time already varies by draw (the on-floor counter) and induces most of the real
  P/R/A covariance: 1.142 vs real 1.196.
- So E4's near-independence (0.997) is introduced DOWNSTREAM of the engine, or by a production path whose minutes do
  not vary. **Not yet checked which:**
  - candidates are per-stat calibration / ladder construction from marginals;
  - or production calls whose lineup / minutes inputs are fixed.
- This narrows E4's fix: a minutes-variance mechanism in the engine helps the WIDTH (Phase 1); the covariance loss is
  to be located in the serving path.

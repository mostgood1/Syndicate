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

## E4 LOCATION CHECK — PRE-REGISTERED 2026-10-27 14:15Z (09:15 CDT), before any draw exists

**Question.** Code reading already rules out the calibration layer (decision-engine a136e7f6). E4 read `pra_sd` with
`sd_scale` divided out, and production builds PRA per draw (`smart_sim.py:2026-2043`). Does the production ENGINE
CONFIG, as opposed to the candidate (fit_pd) config, produce E4's near-independence?

**Arm PDPROD:**
- the production config as P3 defined it for valid_prod: no levers, no engine flags, total-inputs
  {skip_def_subtraction} only, no calibration files, no quarters calibration;
- plus `diag_foul_outs=1`, a research-only counter with no RNG draws (needed for the on-floor counts);
- shared with fit_pd: the same availability and prop-calibration files, `code_pd`, 200 draws, the 12 sweep dates,
  SYNDICATE_NBA_TEAM_INPUTS=1, nice 19 in WSL.

**Statistic.** The fit_pd / E4 statistic: per player-game with ≥ 15 mean sim min, Var(P+R+A) / [Var P + Var R +
Var A] over draws, taken as the median. The CONTROL is fit_pd's median restricted to the same 12 dates. That is the
paired comparison; the FIT-wide 1.142 is context only.

**Decision rule (fixed now):**
- PDPROD ≤ 1.05 → **CONFIG.** The production config drops the covariance, and the candidate config restores it.
  E4 rides with the forward test. Next: which field.
- PDPROD within 0.05 of the 12-date control → **NOT CONFIG.** The loss is in the production serving path or inputs
  (for example E4's population or the minutes inputs live), not the engine config.
- Anything else → **AMBIGUOUS.** Report it as such, with no attribution.
- Also reported: the corr(sim min, pts) median, and the per-minute ratio. In each arm, a draw count
  (on_n ≥ 0 share) proves the counter ran.

**E4 LOCATION CHECK — RESULT 2026-10-27 15:06Z (10:06 CDT). VERDICT: CONFIG** (the rule pre-registered b497373a).
Both arms ran on 87 games / 17,400 draws over the 12 sweep dates, with 0 errors and on-floor counts present in
100% of draws:

| arm | player-games | Var(PRA)/sum median | per-minute | corr(sim min, pts) |
|---|---|---|---|---|
| PDPROD (production config) | 1,342 | **1.002** | 0.968 | **0.178** |
| fit_pd candidate, same 12 dates | 1,415 | 1.138 | 0.956 | 0.412 |
| E4, production served | 846 | 0.997 | — | — |
| real | — | 1.196 | — | — |

**Reading:**
- The production ENGINE CONFIG alone reproduces E4's near-independence (1.002 vs 0.997). The serving path needs no
  separate explanation. The candidate config restores most of the real covariance.
- Per minute, the two arms match (0.968 vs 0.956). The difference is how much the draw's playing time co-moves with
  production: corr 0.18 vs 0.41.
- **Believed, not tested:** the candidate's playing-time levers produce that co-movement (bench_weight_boost=3,
  blowout_bench_rest, foul trouble / foul-out in sim, score_effect_k). Which field is owed if anyone needs it; it is
  not needed for the decision.
- **Consequence:** E4's covariance rides with the forward test (3020b556) via nba_engine_config.json. No separate
  serving fix exists to make.
- **Owed once production draws carry the covariance:** k_combo for pr/pa/ra (`nba_prop_calibration.py:19-21`) and
  the SGP pool's PR/PA/RA Normal assume independence. Both must be re-read when the config goes live.
- Artifacts: `C:/tmp/bball_sc/r2s/pra_paired.{py,json}`, `run_pdprod.sh`, draws `C:/tmp/bball_sc/sweep/PD_prod`.

## PHASE 2 STEP 1b — ROSTER CHECK, PRE-REGISTERED 2026-10-27 23:18Z (18:18 CDT), before any classification is computed

**Question.** Step 1's ABSENT (1,978) and REAL_ONLY (2,983) player-games: are they backtest-input artifacts (a
roster leaked from LATER in the season, or one left STALE from earlier) or real-world absence (injury, inactive)?
Example from step 1: Zubac on IND, 2025-11-01.

**Evidence.**
- Every cached ESPN NBA summary (1,042 games; regular season only, `season.type == 2`). Each box lists the team's
  active list, DNPs included, so it is a per-game record of which team a player belonged to. Game date = header UTC
  minus 6 h.
- The fit_pd sim records (`pnames` per team-game) give the sim's roster.
- Population: exactly step 1's (fit_pd, the same gaps() keying and the same `names_match` join).

**ABSENT** (the sim put player X on team T on date d; T's box on d does not list X). The class is decided by X's
real box appearances:
- **LEAK_FUTURE**: X appears for T only AFTER d, and for another team on or before d.
- **STALE_PAST**: X appears for T only BEFORE d, and for another team after d.
- **T_AROUND**: X appears for T both before and after d, but not on d. Real absence (an injured or inactive player
  left off the active list).
- **T_ONLY_AFTER_NO_OTHER / T_ONLY_BEFORE_NO_OTHER**: one side only, with no other team. A late arrival or departure
  with no observed box elsewhere: signing, waiver, G-League, season-ending injury.
- **NEVER_T**: X never appears for T. Split by whether X appears for any team at all.
- **NO_BOX**: X appears on no box.

**REAL_ONLY** (X played for T on d; the sim's T roster on d lacks X):
- **SIM_NEVER_T**: the sim never lists X for T on any date. A pool hole: two-way, rookie, or signing never
  ingested.
- **SIM_LATER_ONLY**: the sim lists X for T only after d. Roster lag.
- **SIM_EARLIER_ONLY**: the sim lists X for T only before d. The sim dropped him.
- **SIM_AROUND**: the sim lists X for T before and after d. An availability call: the injury feed had him out and
  he played.

**What it decides (no thresholds; this is a census):**
- LEAK_FUTURE > 0 is a backtest look-ahead defect. The minutes lanes own the fix. Count it, with its sim
  min/team-game.
- STALE_PAST and SIM_LATER_ONLY measure as-of roster lag.
- T_AROUND and SIM_AROUND are availability (injury-feed) errors, not roster errors.
- **Reported per class:** player-games, sim (or real) min per team-game, and month. Twelve examples per class.

**STEP 1b ROSTER CHECK — RESULT 2026-10-27 23:28Z (18:28 CDT).**
- Population: step 1's own (fit_pd, 1,604 team-games). Step-1 output is byte-identical after the refactor (md5
  da9499…).
- Code: `basketball_player_distribution_read.py --rosters`; output `C:/tmp/bball_sc/r2s/phase2_rosters_final.json`;
  post-hoc check `r2s/mirror_check.py`.

**Two disclosed deviations from the pre-registration** (both found by spot checks before reading the census):
- **(1) The All-Star game is excluded from the timeline.** ESPN files 2026-02-15 WORLD / STRIPES as season type 2;
  that produced 4 false STALE_PAST rows (Giannis, Curry). It moved 4 rows, STALE_PAST → T_ONLY_BEFORE_NO_OTHER.
- **(2) The cache covers only 2025-11-01..03-01**, so the window edges truncate "before" and "after". The edge
  classes (T_ONLY_AFTER / T_ONLY_BEFORE_NO_OTHER) partly hold T_AROUND and leak cases. Measured window-start leak
  inside T_ONLY_AFTER: 4 of 150.

**ABSENT** (1,978 player-games; 19.8 sim min per team-game):

| class | player-games | sim min / team-game | reading |
|---|---|---|---|
| T_AROUND | 1,128 | 13.94 | real absence: on the team before and after, not on the active list that day (LaMelo, Luka, Reaves, Zion) |
| LEAK_FUTURE | 411 | 2.74 | listed on a team he joined LATER (CHI 11-02: Sexton, Simons, Yabusele, Richards, Dillingham, McClung, L. Miller) |
| NEVER_T_OTHER_TEAM | 29 | 0.16 | also leak: Zubac on IND in Nov (LAC through 02-02); Garland on LAC; AD / Russell / Trae on WAS |
| T_ONLY_AFTER_NO_OTHER | 150 | 1.03 | mostly early-season injury returns (Monk, McConnell) at the window start |
| T_ONLY_BEFORE_NO_OTHER | 123 | 1.11 | mostly season-ending injuries (Beal, Prince, Lively); 93 in Feb = window end |
| NO_BOX | 137 | 0.87 | never on an active list (Haliburton, out for the season; CHI two-ways) |
| STALE_PAST | 0 | — | — |

**REAL_ONLY** (2,983 player-games; 29.6 real min per team-game):

| class | player-games | real min / team-game | reading |
|---|---|---|---|
| SIM_NEVER_T | 2,277 | 24.97 | the sim never lists him for the team he played for |
| SIM_AROUND | 581 | 3.88 | availability: the sim had him out that day and he played |
| SIM_LATER_ONLY | 106 | 0.73 | roster lag |
| SIM_EARLIER_ONLY | 19 | 0.06 | — |

**SIM_NEVER_T decomposed** (post-hoc, disclosed):
- 1,712 player-games (20.1 real min / team-game) belong to players whose LAST real listing is another team.
- 1,544 of them (18.2 min / team-game): the sim lists the player on that final team.
- **614: the sim lists him there on or before this date**, while he was still playing for his original team. These
  are certain look-ahead.
- Examples: CHA → CHI, UTA → MEM, BOS / NYK / PHX / MIN / IND → CHI, all on 2025-11-02/03. The real first box on the
  new team is 2026-02-05..07 (the trade deadline).
- 565 player-games (last listed on the team, never in the sim) are pool holes: signings, two-ways.
- Each team's sim roster is not one fixed snapshot: first-vs-last-date Jaccard median 0.61 (min 0.42) over 30 teams.

**VERDICT:**
- **(a) The step-1 misallocation is mainly a LOOK-AHEAD LEAK in the backtest's player→team assignment.** Players are
  placed on their END-of-window (post-trade-deadline) team for the whole window. Two faces of it:
  - wrong players simulated: LEAK_FUTURE + NEVER_T_OTHER, 440 pg, 2.9 sim min / team-game;
  - real players missing: SIM_NEVER_T, traded away, about 18–20 real min / team-game.
- **(b) The second component is AVAILABILITY:** players simulated on days they were out. T_AROUND is 13.9 sim
  min / team-game, plus the SIM_AROUND mirror at 3.9.
- **Not located:** which backtest input carries the team map or availability (pristine resim inputs / player pool).
- **Believed, NOT verified:** production is unaffected because live dates use current rosters. The leak is
  historical-resim-only, so it contaminates the FIT/VALID research sims, not served picks.
- **Consequence for the calibration lane:** team totals are calibrated to targets, so the team-level effect is
  muted, but rotation and player-level reads on FIT carry it. The Phase-1 matched population excludes these
  player-games by construction.
- **Hand-off:** the nba-sim-minutes-allocation / -history-path lanes own the pool fix. Nothing is changed here.

**STEP 1b — LEAK LOCATED 2026-10-28 16:14Z (11:14 CDT)** (verified by reading the code and the resim inputs):
- **The input:** `~/nba_resim/pristine/nba_source/data/processed/rosters_2025-26.csv`, the ONLY roster file in the
  research resim tree (written 10-05). It is an END-of-season snapshot. `HOW_ACQUIRED` reads "Traded from LAC on
  02/05/26" (Zubac, Kobe Brown → IND), "Traded from CHA on 02/04/26" (Sexton → CHI), "Signed on 03/04/26".
- **The path:**
  - `basketball_props_smart_sim._team_players_from_processed_rosters_local` (`:1981`) builds each team's pool as
    the file's rows with `TEAM_ABBREVIATION == team`. The season is picked from the date, and every 2025-26 date
    reads the same file.
  - `_filter_team_players_against_processed_roster_local` (`:2060`) then drops anyone the file does not put on
    the team.
  - The only per-date override is `league_status_<date>.csv` (it adds allowed names). The resim tree has 1 such
    file, for no FIT date.
- **Both faces of the step-1b leak follow:**
  - deadline acquisitions are simulated for their new team all season (LEAK_FUTURE / NEVER_T_OTHER);
  - traded-away players are filtered off their original team (SIM_NEVER_T, last listed elsewhere).
- **Production is not affected on live dates:** lane nba-current-rosters (CLOSED 10-21, state
  [nba-current-rosters]) writes ESPN's current rosters to `rosters_<season>.csv` every 90 min. The same code path
  therefore reads a current file live.
- **Not yet observed:** a mid-season trade under that fix (the 2026-27 deadline is in February).
- **So the leak is HISTORICAL-RESIM ONLY.** It sits in the research harness owned by basketball-scenario-calibration;
  no sim-minutes lane is open (history-path CLOSED 10-28). Every FIT / VALID sim of either lane carries it.
- **Consequence for this lane's order:** Phase 1's minutes miss (.43) is read on the matched population, but the
  leaked pool (wrong players water-filled, real rotation players removed) also distorts the matched players' minutes.
  A minutes-variance mechanism tuned now would be fit against a contaminated baseline. **Proposed (owed a user
  decision):** an AS-OF roster in the harness first (team of each player's last `player_logs` game before the date;
  same-day signings via HOW_ACQUIRED); then re-run Phase 1; then pre-register the minutes mechanism.

## STEP 1c — AS-OF ROSTER RE-RUN, PRE-REGISTERED 2026-10-28 16:25Z (11:25 CDT), before any as-of draw exists

**User decision 10-28:** "As-of roster first", then re-run Phase 1, then pre-register the minutes mechanism.

**Code:**
- Harness `--asof-roster` (54ed87dc, default off, so OFF is the old path untouched). It rewrites the scratch season
  roster per slate date from the truncated player_logs plus dated HOW_ACQUIRED. Rules in the docstring; 3 unit
  tests.
- Dry run on the real resim inputs:
  - 11-02: 59 moved, 3 trades reverted, 35 future adds dropped, 25 departed added.
  - 02-25: 6 moved.
  - Zubac / Sexton / K. Brown / Simons are on the old team before the deadline and the new team after it.
- Research copy `~/bball_sc/code_ar` = `code_pd` + `asof_roster` only (diff verified: 66 added lines, 0 removed).

**SMOKE AR_smoke:**
- Config: the fit_pd config (round-2b + assists) + `--asof-roster`, the 12 sweep dates, 200 draws, nice 19,
  `--track-oncourt --record-player-draws`.
- Control: the fit_pd files for the same 12 dates.
- PASS iff ALL of:
  - (a) ASOF_ROSTER is printed on 12/12 dates;
  - (b) LEAK_FUTURE + NEVER_T_OTHER_TEAM ≤ 10% of the control's count;
  - (c) SIM_NEVER_T whose last real listing is another team ≤ 25% of the control's count.
- Reported, no gate:
  - every census class;
  - the sim game-total mean and the per-team points mean, vs control (calibration impact);
  - the Phase-1 minutes miss on the 12 dates (small n).

**If the smoke PASSES:** the full FIT `fit_ar` (the same config + `--asof-roster`, 3 workers), then:
- the step-1 census and the 1b census on fit_ar;
- the Phase-1 read on fit_ar, against fit_pd's minutes miss .430 (bench .543), pts .319, reb .300, ast .274,
  threes .243. Descriptive: this is the new BASELINE for the minutes mechanism, not a pass/fail.

**If the smoke FAILS:** report which criterion failed; no FIT.

**Known residuals, out of scope:**
- the AVAILABILITY component (T_AROUND); the harness deletes `raw/injuries.csv` for as-of hygiene;
- the 565 pool-hole player-games (never in the season file).

**STEP 1c SMOKE — RESULT 2026-10-28 17:05Z (12:05 CDT). VERDICT: PASS** (a, b, c all true).
- Run dir `C:/tmp/bball_sc/sweep/ClarkAndAddison`, log `~/bball_sc/sweep_ClarkAndAddison.log`. Not "AR_smoke":
  WSL's login shell exports NAME = the machine name, which the runner's `${NAME:-...}` default picked up.
- Config verified: code_ar, calfiles_sw_all (as fit_pd), the fit_pd levers / flags, `--asof-roster`. 12/12 dates,
  0 errors.
- Control: the fit_pd files for the same 12 dates (`C:/tmp/bball_sc/ctl12`). 87 games, 174 team-games in each arm.
- Grader `r2s/grade_ar.py` → `r2s/grade_ar.json`.

| | as-of roster | control |
|---|---|---|
| leak (LEAK_FUTURE + NEVER_T_OTHER) | **0** | 50 |
| SIM_NEVER_T, last listed elsewhere | **0** | 212 |
| REAL_ONLY player-games | 98 | 356 |
| REAL_ONLY real min / team-game | **5.27** | 34.07 |
| ABSENT sim min / team-game | 15.97 | 20.38 |
| DNP_LISTED_COACH sim min / team-game | 7.68 | 7.22 |
| matched player-games (Phase 1) | 1,772 | 1,514 |
| sim game total mean | 230.77 | 230.63 |

**Phase 1 on the 12 dates** (descriptive; miss nominal .20):

| cell | as-of | control |
|---|---|---|
| minutes (all) | miss .496, width 1.69, bias **+2.28** | miss .415, width 1.58, bias −0.18 |
| minutes (bench) | miss .598 | miss .519 |
| input-minutes bias | **+2.22** | −0.27 |
| pts / reb / ast / threes | .327 / .309 / .283 / .246 | .310 / .299 / .292 / .234 |

**Reading:**
- The leak is removed (b, c). Team totals are unchanged (+0.14 per game), as expected for a sim calibrated to
  targets.
- The matched population grows by 258 player-games (players the leak had removed).
- **The minutes read gets WORSE, not better.** With the right players in each pool, the INPUT minutes now
  UNDER-allocate the players who play by 2.2 min on average. About 28 sim min per team-game still go to players who
  do not play: ABSENT 16.0 (injured / inactive; the resim has no injury feed) + coach DNP 7.7 + other DNP 4.3.
- The leak had masked this by replacing those minutes with wrong-team players' minutes.
- **The minutes defect is now an ALLOCATION / AVAILABILITY bias first and a variance defect second.** This is the
  baseline the minutes mechanism must be built against.
- The full FIT `fit_ar` was launched 17:07Z (12:07 CDT): `r2s/launch_fit_ar.sh`, 3 workers, nice 19.

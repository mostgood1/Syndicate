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

**STEP 1c FULL FIT `fit_ar` — RESULT 2026-10-28 19:48Z (14:48 CDT).** This is the descriptive baseline that
pre-registration f76bea61 calls for; there is no pass/fail.
- Run: the fit_pd config + `--asof-roster`, code_ar, 3 workers, nice 19. Finished about 19:40Z.
- `ASOF_ROSTER` was printed on 109/109 dates.
- 2 SIM_FAIL (2025-12-09 and 12-16, "SmartSim produced no player rows"). fit_pd failed on the SAME 2 dates
  (fit_pd_w1.log), so the failures predate this change.
- Both arms cover 806 games and 1,604 team-games.
- Grader: `r2s/grade_fit_ar.py` (grade_ar.py pointed at fit_ar vs fit_pd) → `r2s/grade_fit_ar.json`.
- The smoke gates also hold on the full run: leak 4 vs 440, never-T last-elsewhere 0 vs 1,712.

| census | fit_ar | fit_pd |
|---|---|---|
| LEAK_FUTURE + NEVER_T_OTHER | **4** | 440 |
| SIM_NEVER_T (all) | **2** | 2,277 |
| REAL_ONLY player-games / real min per team-game | 948 / **6.15** | 2,983 / 29.64 |
| ABSENT sim min / team-game (T_AROUND n) | 15.70 (1,309) | 19.84 (1,128) |
| DNP_LISTED_COACH sim min / team-game | 8.07 | 7.06 |
| DNP_LISTED_OTHER sim min / team-game | 4.86 | 4.47 |
| sim game total mean | 230.55 | 230.50 |

**Phase 1 (matched player-games; nominal miss .20; bias = real − sim):**

| cell | fit_ar (n 16,318) | fit_pd (n 14,291) |
|---|---|---|
| minutes all | miss **.498**, width 1.71, bias +2.29 | .430, 1.57, +0.29 |
| minutes bench | miss **.604**, width 2.30, bias +2.95 | .543, 2.03, +1.49 |
| minutes starter | miss .367, width 1.24, bias +1.47 | .322, 1.25, −0.86 |
| input-minutes bias | **+2.24** | +0.20 |
| pts | .327, bias +1.06 | .319, +0.02 |
| reb | .308, +0.52 | .300, +0.06 |
| ast | .274, +0.26 | .274, −0.01 |
| threes | .243, +0.07 | .243, −0.04 |

**Reading:**
- **The full run reproduces the smoke's direction and size.** Minutes miss .496 → .498; input bias +2.22 → +2.24.
  The 12-date result was not a small-n artefact.
- **The accounting closes.**
  - Sim minutes that go to non-players: 15.70 + 8.07 + 4.86 = 28.63 per team-game.
  - Minus the 6.15 real minutes the sim's pool lacks gives 22.5.
  - The matched shortfall is 2.24 min × 10.17 matched players per team-game = 22.8.
  - So the under-allocation of real players is the minutes the sim gives to players who sit, to within 0.3 min.
- **pts / reb now show the same sign** (+1.06 / +0.52 per player-game). The stat miss rates moved ≤ .008 because
  each player's stat band follows the minutes it rides on.
- **The new baseline for the minutes mechanism (Phase 2 step 2):**
  - miss .498 (bench .604, starter .367);
  - input bias +2.24;
  - about 28.6 sim min per team-game to non-players, of which 15.7 are injured/inactive (T_AROUND; the resim has no
    injury feed), 8.1 coach DNP and 4.9 other DNP.
- **The order this implies:**
  - (1) availability: who is eligible to play at all;
  - (2) rotation depth: coach DNPs, 8.1 min;
  - (3) only then minutes variance (width).
  - A width mechanism tuned first would widen bands to cover a level error.
- **Residual pool holes:** REAL_ONLY is 948 player-games / 6.15 min. Of these, SIM_AROUND is 725: players the sim
  has on the team on nearby dates but not this one. Not decomposed yet.

## STEP 1d — HISTORICAL INJURY FEED, PRE-REGISTERED 2026-10-28 23:20Z (18:20 CDT), before any feed row is built

**User decision 10-28:** "build the historical injury feed first". It fills the T_AROUND hole: 15.7 sim min per
team-game go to players who were injured or inactive.

**Source, verified by probe 23:00Z:**
- The official NBA injury-report PDFs at ak-static.cms.nba.com. The season index page lists only TODAY's reports
  now, but the host still serves 2025-26.
- Format change: the filename is hourly `_HHPM` through about 2025-12-21 and every 15 minutes `_HH_MMPM` from about
  12-26.
- Probe dates: 11-01, 11-15 and 12-20 served at 01/05/06PM; 12-28, 01-02, 01-15 and 02-25 at the 15-min times.
- The production parser (`NBAOfficialInjuryReportScraper._parse_pdf_rows` + `_clean_injury_player_names`, unchanged)
  reads both layouts: 4 sample reports gave 87-132 rows from 19-28 teams.
- Known name glitch: "Dorian Finney- Smith". The build counts names that are on no roster.

**Feed (`scripts/nba_injury_history_build.py`, NEW, this lane):**
- Each regular-season game in the ESPN summary cache gets ONE report: the latest one stamped at or before
  tip − 30 min, in ET.
- Only that game's two teams' rows are kept, and every row is stamped with the game's US date. One date's rows =
  the union over its games.
- No look-ahead: a report published after tip − 30 is never read. Teams are the report's own; there is no roster
  team correction, so the end-of-season roster cannot bring the leak back through this path.
- The output CSV has columns date / team / player / status / injury / source=`nba_official` / report. That is the
  shape `basketball_props_smart_sim` reads from `raw/injuries.csv`: the latest snapshot on or before the date, with
  OUT / DOUBTFUL / SUSPENDED / INACTIVE / REST excluded — the production rule, unchanged.
- The PDFs are downloaded into their own data dir, `C:/tmp/bball_sc/inj_pdf`.

**Harness:** `--injury-history CSV` in `scripts/basketball_scenario_rates.py`. It is default off, so OFF is
byte-identical. It writes date d's rows as the scratch `raw/injuries.csv` after the copy loop deletes that file, and
prints `INJURY_HISTORY {d} {rows, teams, excluded}`. Edited under the calibration lane's marker, as with 54ed87dc.

**Build gates (before any sim):**
- (B1) every FIT game has a report at or before tip − 30;
- (B2) for ≥ 95% of team-games the report lists the team; "not yet submitted" counts as unlisted;
- (B3) report rows whose name is on no roster ≤ 5%.
- Reported: per-format counts, the report-age distribution (tip − report time).

**SMOKE INJ_smoke:**
- Config: the fit_ar config + `--injury-history`, the same 12 sweep dates, 200 draws, nice 19.
- Control: fit_ar's files for those 12 dates.
- PASS iff ALL of:
  - (a) INJURY_HISTORY is printed with rows > 0 on 12/12 dates;
  - (b) T_AROUND count AND ABSENT sim min per team-game are both ≤ 50% of the control's;
  - (c) FALSE EXCLUSIONS ≤ 3% of excluded player-game slots. A false exclusion is a player whom the feed excludes
    for a date and who plays in that game's box. This is the feed's accuracy measured against the truth, with no
    look-ahead in the feed itself.
- Reported, no gate: every census class, the game-total and team-points means vs control, the Phase-1 minutes and
  stat rows.

**If PASS:**
- the full FIT `fit_inj` (3 workers);
- the step-1 / 1b census and the Phase-1 read against fit_ar's baseline: minutes miss .498 (bench .604, starter
  .367), input bias +2.24, pts .327 / reb .308 / ast .274 / threes .243, ABSENT 15.70 + coach DNP 8.07 + other DNP
  4.86 sim min per team-game.
- Descriptive: this is the new baseline for the minutes mechanism.

**If FAIL:** report which criterion failed; no FIT.

**Out of scope:**
- QUESTIONABLE / PROBABLE players stay in the pool, as in production; their minutes are the mechanism's job;
- the coach DNP of healthy players (8.07);
- production: the feed only fills a research hole, and production already reads the live report.

**STEP 1d — BUILD + SMOKE RESULT 2026-10-29 00:18Z (19:18 CDT 10-28). SMOKE VERDICT: PASS** (a, b, c).

**Build** (`scripts/nba_injury_history_build.py`, bad527bf + 4d237be4) → `C:/tmp/bball_sc/r2s/injury_history_nba_2025-26.csv`:
- 820 games (11-01..03-01), 0 without a report (B1). 1,627 of 1,640 team-games listed (B2, 99.2%).
- 492 reports used: 343 games hourly, 477 every-15-min.
- Report age before tip: p5 / p50 / p95 = 30 / 30 / 60 min.
- 7,204 rows, 7,174 of them OUT. Only 18 QUESTIONABLE: by tip − 30, game-time decisions are mostly resolved.
- **B3 FAILED on the first build: 704 of 6,875 rows off-roster (10.2%).**
  - Cause: the production name repair (#725, 36eb357b) accepts a word-dropped name only when it is exactly ONE
    roster player on the report's team. The build had given it the END-of-season roster, so traded players
    stayed garbled ("Anthony Way Davis", "Collin Way Sexton", "Kristaps Assignment Porzingis").
  - FIX (4d237be4): repair against the as-of roster of each report's date (the harness's `asof_roster`).
- **DISCLOSED: B3's metric was changed after the result was seen.**
  - It now counts with the SIM's own name key (`basketball_props_smart_sim._norm_name_key`) over roster file +
    player_logs, instead of the parser's key over the roster file.
  - Why: 183 of the 704 rows were hyphen splits ("Shai Gilgeous- Alexander"). The parser's key misses those, but
    the sim's key matches them, so the sim excluded those players anyway.
  - Rebuilt: 267 of 7,204 off (3.7%), so B3 PASS. All 267 are players with NO game all season (Highsmith,
    Rozier, Niang, Exum, two-way players), so they cannot be in any pool.
- **Production is not implicated:** live reads the current roster, and #725 read 0 off-roster on the fleet.

**Consumption verified (not inferred):** on 2025-11-07, the 86 OUT-listed players are in the control pool
24 times and in the INJ pool 0 times. Pool 282 → 258. The sim log prints no exclusion telemetry, so the pools
were compared directly.

**SMOKE INJ_smoke:**
- code_inj = code_ar + the a6e56868 patch (22 added lines, 0 removed). The fit_ar config + `--injury-history`.
- 12/12 dates, 0 errors. Control: fit_ar's files for the 12 dates (`C:/tmp/bball_sc/ctl12_ar`). 87 games, 174
  team-games.
- Grader `r2s/grade_inj.py` → `grade_inj.json`.

| | INJ | control (fit_ar) |
|---|---|---|
| (a) INJURY_HISTORY rows > 0 | 12/12 | — |
| (b) T_AROUND | **14** | 151 |
| (b) ABSENT sim min / team-game | **0.46** | 16.00 |
| DNP_LISTED_OTHER sim min / team-game | 0.02 | 4.34 |
| DNP_LISTED_COACH sim min / team-game | 8.35 | 7.68 |
| REAL_ONLY real min / team-game | 5.27 | 5.27 |
| (c) false exclusions / excluded slots | **0 / 769** | — |
| sim game total mean | 230.53 | 230.35 |

**Phase 1 on the 12 dates** (miss nominal .20; bias = real − sim):

| cell | INJ | control |
|---|---|---|
| minutes all | miss **.424**, width 1.47, bias +0.40 | .501, 1.70, +2.29 |
| minutes bench | .530, width 1.92, bias +1.09 | .605, 2.30, +3.21 |
| minutes starter | .314, width 1.15, bias −0.31 | .373, 1.23, +1.17 |
| input-minutes bias | **+0.35** | +2.22 |
| pts / reb / ast / threes | .302 / .298 / .260 / .236 | .327 / .309 / .279 / .248 |
| pts / reb / ast bias | +0.17 / +0.13 / +0.10 | +1.13 / +0.55 / +0.32 |

**Reading:**
- The feed removes the availability hole. About 20 of the 28 non-player sim minutes per team-game go
  (ABSENT 16.0 → 0.5, other DNP 4.3 → 0.0), with 0 false exclusions in 769 slots.
- The input-minutes under-allocation falls from +2.22 to +0.35. Every stat's miss and bias improve.
- Team totals do not move: 230.5 vs 230.4.
- **Bench split shift:** starter / bench is the top-5 by input minutes, so the bench n changed (973 → 902).
- **What is left for the minutes mechanism:** coach DNP 8.35 sim min per team-game (healthy scratches), then
  variance. Width 1.47 overall and 1.92 on the bench: the bench bands are still about twice too wide.
- The full FIT `fit_inj` was launched 00:17Z (19:17 CDT): `r2s/launch_fit_inj.sh`, 3 workers, nice 19.

**STEP 1d — FULL FIT `fit_inj` RESULT 2026-10-29 02:48Z (21:48 CDT 10-28). Descriptive; this is the NEW BASELINE
for the minutes mechanism.** The smoke gates were re-run over the whole FIT as a check: all three hold.

**Run:** code_inj, the fit_ar config + `--asof-roster --injury-history`, 3 workers, nice 19, 19:17 → 21:47 CDT.
- 109/109 dates printed INJURY_HISTORY with rows > 0. 0 tracebacks.
- 2 SIM_FAIL: 2025-12-09 and 2025-12-16, the SAME two dates that failed in fit_pd and fit_ar (not the feed).
- 806 games, 1,604 team-games, matching fit_ar. Grader `r2s/grade_fit_inj.py` → `grade_fit_inj.json`.

| | fit_inj | fit_ar (control) |
|---|---|---|
| T_AROUND | **148** | 1,309 |
| ABSENT sim min / team-game | **1.19** | 15.70 |
| DNP_LISTED_OTHER sim min / team-game | **0.15** | 4.86 |
| DNP_LISTED_COACH sim min / team-game | 8.87 | 8.07 |
| REAL_ONLY real min / team-game | 6.19 | 6.15 |
| false exclusions / excluded slots | **3 / 6,995** (0.04%) | — |
| sim game total mean | 230.53 | 230.55 |

- The 3 false exclusions are one team-game: 2026-01-28 CHI (Giddey, Huerter, J. Smith all listed out and played).

**Phase 1, all FIT dates** (miss nominal .20; bias = real − sim):

| cell | fit_inj | fit_ar |
|---|---|---|
| minutes all | miss **.432**, width 1.52, bias +0.47 | .498, 1.71, +2.29 |
| minutes bench | .547, width 1.98, bias +1.00 | .604, 2.30, +2.95 |
| minutes starter | .312, width 1.21, bias −0.09 | .367, 1.24, +1.47 |
| input-minutes bias | **+0.38** | +2.24 |
| pts / reb / ast / threes miss | .303 / .286 / .267 / .234 | .327 / .308 / .274 / .243 |
| pts / reb / ast / threes bias | +0.15 / +0.11 / +0.04 / −0.03 | +1.06 / +0.52 / +0.26 / +0.07 |

**Reading:**
- The full FIT reproduces the smoke. Of fit_ar's 28.6 non-player sim min per team-game, 19.2 go (ABSENT 15.70 →
  1.19, other DNP 4.86 → 0.15). Every stat's miss and bias improve; game totals do not move.
- Starter minutes are now unbiased (−0.09). The input under-allocation is +0.38.
- Bench n is 8,330 vs 9,003: starter / bench is the top-5 by input minutes, so the split moved with the pools.
- **The minutes mechanism starts from here:** coach DNP 8.87 sim min per team-game (healthy players the coach
  does not play), REAL_ONLY 6.19 real min the sim never gave, then variance — bench width 1.98, about twice too
  wide; starter width 1.21.

## STEP 2a — COACH DNP (PER-DRAW PARTICIPATION), PRE-REGISTERED 2026-10-29 20:16Z (15:16 CDT), before any as-of feature is read against the outcome

**User decision 10-29:** "pre-register the coach DNP mechanism". Baseline is fit_inj (d674e150): healthy players the
coach does not play take **8.87 sim min per team-game** (1,674 player-games over 1,604 team-games, about 8.5 sim min
each).

**What is already in the sim, so what this is NOT:**
- NBA availability K=2 (`nba_sim_availability.json`, enabled in every run: 109/109 dates print NBA_SIM_AVAILABILITY)
  already DROPS a player who missed the team's last 2 games. Every coach-DNP slot is therefore a player who played in
  one of the last 2 games.
- A deterministic tighter rule was measured and rejected: K=1 cost 14.09 / 17.13 real-player min wrongly removed per
  team-game (train / test, findings_2026-10-02 "NBA availability (K=2)"). That was before the injury feed, so K=1 is
  re-read below as a zero-code COMPARATOR, not as the mechanism.
- So the mechanism is probabilistic: each pool player plays in a draw with as-of probability p; a non-participant's
  minutes go to the participants.

### Stage A — offline feasibility (no sim run). Decides whether stage B is built.

**Population:** fit_inj's pool slots (the sim's `pnames` per team-game) with outcome PLAYED (box min > 0) or
DNP_COACH (in the box, reason contains COACH). ABSENT, DNP_LISTED_OTHER and JOIN slots are left out. Input minutes
`m` = the slot's mean sim minutes in fit_inj (the quantity that would be moved).

**As-of features** (this season's regular-season player_logs rows strictly before the date; the team is the as-of
roster's):
- f1 `played_last`: MIN > 0 in the team's last game (0 or 1; K=2 guarantees the other of the last two);
- f2 `share10`: games with MIN > 0 for this team among the team's last 10 games;
- f3 `m`, the sim's own input minutes.

**Model, fixed now:** a binned table P(play | cell). Cells = played_last {0, 1} × share10 {< .5, .5–.8, .8–< 1, 1}
× m {< 6, 6–12, 12–20, ≥ 20}. A cell with < 30 train slots is pooled to its (played_last × m) margin, then to m alone.
- **TRAIN** = 2025-11-01..12-31 fits the table. **TEST** = 2026-01-01..02-28 grades it. Nothing is re-fit after TEST
  is read.

**Gate A, on TEST (all must hold):**
- (A1) Σ p·m over DNP_COACH slots ≤ 60% of Σ m over them, i.e. at least 40% of the 8.87 expected to go;
- (A2) Σ (1 − p)·m over PLAYED slots ≤ Σ (1 − p)·m over DNP_COACH slots: the mechanism moves at least as many
  minutes off the right players as off players who played;
- (A3) calibration: in every p-decile with ≥ 100 slots, |mean p − played rate| ≤ .05.
- Reported, no gate: AUC; per-cell n and rates; the K=1 comparator's minutes removed off DNP vs PLAYED on the same
  population; the train numbers.

**If A FAILS:** stop. Report which criterion failed. The reading would be that coach DNP is not predictable as-of from
box history alone, and needs news (starting lineups, beat reports); no engine work.

### Stage B — engine (only if A PASSES)

**Mechanism:**
- NEW `syndicate/features/shared/nba_sim_participation.py`, switch file `nba_sim_participation.json` carrying the
  frozen stage-A table. Absent file = off; `SYNDICATE_NBA_SIM_PARTICIPATION=0` kills it.
- Hook: the per-draw loop `syndicate/features/basketball_engine/orchestrator/smart_sim.py` ~:1719. Before each
  `simulate_pbp_game_boxscore` call, draw u ~ U(0,1) per pool player:
  - a non-participant's `_sim_min` is 0 for that draw, and minutes are re-water-filled over the participants with
    the existing caps;
  - rotation lineups (`home_lineups` / `away_lineups`) holding a non-participant are dropped and the weights
    renormalized; if none are left, the minutes-weighted sampler is used.
- One print line per game: `NBA_SIM_PARTICIPATION {applied, players, mean_p, mean_out_per_draw}`.
- **Lane / files:** the hook section of orchestrator/smart_sim.py is claimed by no lane today (the calibration lane
  holds only the pace injury-drag line there). It is added to this lane's `Files:` after a collision check at that
  time, not now.

**Engine standard (docs/ai_context/model_engine_standard.md):**
- a checklist entry, CONSUMED × POPULATED;
- a pipeline trace with file:line;
- player_logs is already disk-backed (the K=2 rule reads it); verified again at build time;
- a reachability test (off != on) before any correctness test.

**Runs:** a 12-date smoke, then the full FIT `fit_part` = fit_inj's config + the switch file, vs fit_inj.

**Gate B, on TEST dates only (all must hold):**
- (B1) DNP_LISTED_COACH sim min per team-game ≤ 60% of fit_inj's on the same dates;
- (B2) minutes miss (all) and bench miss are each not worse than fit_inj by more than .005;
- (B3) pts / reb / ast / threes miss: none worse by more than .005;
- (B4) game total mean within ±1.0 of fit_inj. If it moves more, the totals solver must be re-fit before any stat
  read: this is the mechanism-vs-estimator rule.
- Reported, no gate: width ratios, input bias, every census class, TRAIN dates separately.

**Predictions, written now:**
- B1 holds if A1 does.
- Input-minutes bias moves from +0.38 into [−0.4, +0.2]. The moved minutes go to players who played, and REAL_ONLY's
  6.19 real min per team-game is not addressed.
- **Known risk:** bench width (1.98, already about twice too wide) GROWS, because a participant with p < 1 carries
  mass at 0 minutes. B2 may fail on width-driven misplacement even if B1 passes. That is a result, not a reason to
  change the gate.

**Out of scope:** REAL_ONLY (6.19); variance (step 3); production. Production gets fields only via
`nba_engine_config.json` after the forward test from 11-01.

**STEP 2a STAGE A — RESULT 2026-10-30 17:47Z (12:47 CDT). VERDICT: FAIL (A1, A2). Stage B is NOT built.**

`r2s/stage_a.py` → `stage_a.json`, `stage_a_pop.csv`; run at nice 19.
- Population: TRAIN 9,183 slots (859 coach DNP, 814 team-games); TEST 8,808 slots (815 coach DNP, 790 team-games).
- 0 slots without history. On TEST, 8,769 slots used a full cell and 39 were pooled to the played_last × m margin.

| TEST (Jan–Feb) | value | gate |
|---|---|---|
| coach-DNP sim min / team-game, before | 9.30 | — |
| expected after (Σ p·m) | 7.25 | — |
| (A1) Σ p·m / Σ m over DNP | **.779** | ≤ .60: **FAIL** |
| (A2) minutes moved off DNP / off PLAYED, per team-game | **2.05 / 6.89** | off PLAYED ≤ off DNP: **FAIL** |
| (A3) max calibration gap, deciles n ≥ 100 | .044 | ≤ .05: PASS |
| AUC | .889 (train .906) | — |
| K=1 comparator: min off DNP / off PLAYED per team-game | 2.75 / 16.04 | — |

TRAIN reads the same way: A1 .745, off 2.15 vs 6.87, calibration gap .009.

**Why it fails** (a descriptive breakdown of TEST, `r2s/stage_a_why.py`, read AFTER the verdict):

| p band | DNP | PLAYED | DNP sim min / team-game | DNP mean m | PLAYED mean m |
|---|---|---|---|---|---|
| < .6 | 366 | 383 | 2.02 | 4.4 | 4.7 |
| .6–.8 | 206 | 489 | 2.49 | 9.6 | 10.2 |
| .8–.9 | 65 | 273 | 0.87 | 10.6 | 12.1 |
| .9–.97 | 139 | 1,743 | 2.75 | 15.6 | 16.7 |
| ≥ .97 | 39 | 5,105 | 1.18 | 23.8 | 27.8 |

- **The table is accurate; the outcome is not predictable from box history.** 68.5% of coach DNPs played the team's
  last game.
- 3.9 of the 9.3 minutes sit with players the table gives p ≥ .9: rotation players sitting unexpectedly, averaging
  16–24 sim min. No box-history feature flags them.
- The low-p group is close to a coin flip. At p < .6, 366 sat and 383 played, with the same minutes (4.4 vs 4.7).
  Thinning them moves as many minutes off players who played as off those who sat.
- **K=1 is worse still on the new population:** it moves 16.0 min per team-game off players who played, to remove
  2.75 from those who sat.

**Reading (as pre-registered):** coach DNP is NOT predictable as-of from box history alone. The 8.87 needs NEWS: a
pre-tip signal of who dresses and who sits. Healthy scratches are not on the injury report (the injury feed's
DNP_LISTED_OTHER is already 0.15). Candidates, none built: pre-tip starting lineups and the inactive list (the
NBA posts the active / inactive list about 30 min before tip), beat reports. That is a data-collection decision,
not a mechanism.
- Not done: no engine code, no switch file, no sim run.
- **Next on the pre-registered order:** REAL_ONLY (6.19 real min per team-game the sim never gave) or variance
  (bench width 1.98). Neither has been pre-registered.

## STEP 3 — MINUTES DISPERSION (BENCH VARIANCE), PRE-REGISTERED 2026-10-31 20:27Z (15:27 CDT), before any residual is read by cell

**User decision 10-31:** "pre-register the bench minutes variance fix". Baseline is fit_inj (d674e150).

**CORRECTION to this file, lines 617 and 740 ("about twice too wide"): the direction was wrong.** The grader's
width ratio is sd(real − sim mean) / rms(sim sd) (`scripts/basketball_player_distribution_read.py:74`). Bench 1.98
means real bench minutes scatter about TWICE as far from the sim mean as the sim's own draws do: **the bench bands
are about HALF as wide as they should be (too narrow)**, which is also what miss .547 > .20 says. Consequence for
step 2a's "known risk" (line 740): a p < 1 participant would have WIDENED the sim's spread, i.e. moved bench width
toward 1, not away. Stage A failed before that mattered; no number changes.

**What is already in the sim** (fit_inj levers, `r2s/launch_fit_inj.sh`): blowout_bench_rest=1, bench_weight_boost=3.0,
foul_out_in_sim=1 with foul-trouble thresholds, OT. Those are the only per-draw sources of minutes spread today; the
per-player target `_sim_min` is fixed per game. Starter width 1.21, bench 1.98: the deficit is mostly bench.

### Stage A — offline feasibility (no sim run). Decides whether stage B is built.

**Population:** the Phase-1 population of fit_inj (in the sim AND played, real MIN > 0), with its recorded per-draw
realised minutes (`pl[s][j][4]`) and stats. Starter / bench = top-5 by input minutes, as in Phase 1. Coach-DNP,
ABSENT and REAL_ONLY slots are out (props on a DNP void; those are steps 2a / REAL_ONLY).

**Mechanism, emulated on the recorded draws:**
- per draw d, per pool player i with realised minutes x_id > 0: x'_id = x_id · exp(σ_c·z_id − σ_c²/2), z ~ N(0, 1)
  iid, seed 0 (mean-preserving lognormal);
- then, per team and draw, rescale the pool so the team total equals that draw's pre-shock total (keeps OT and the
  team's 240), and cap each player at game length (48 + 5·OT), water-filling any excess proportionally;
- x_id = 0 stays 0;
- stats in the emulation: stat'_id = stat_id × x'_id / x_id (the Phase-1 minutes-oracle scaling).

**Cells c, fixed now:** the slot's input minutes m (fit_inj sim mean) binned {< 6, 6–12, 12–20, 20–28, ≥ 28}. A bin
with < 300 TRAIN player-games is pooled into its neighbour toward the middle.

**Fit:** TRAIN = 2025-11-01..12-31. Per cell, σ_c from the grid {0, .05, …, 1.50} minimising |minutes miss − .20| on
TRAIN for that cell. **TEST** = 2026-01-01..02-28 grades it. Nothing is re-fit after TEST is read.

**Gate A, on TEST (all must hold):**
- (V1) minutes miss: bench and starter each within [.15, .25] (from .547 / .312);
- (V2) minutes width ratio: bench and starter each within [.85, 1.15] (from 1.98 / 1.21);
- (V3) tail balance: for bench and starter, |p_lo − p_hi| ≤ .05 (a spread fix must not buy coverage on one side);
- (V4) pts / reb / ast / threes miss (scaled stats): none worse than fit_inj's TEST value by more than .005.
- Reported, no gate: σ per cell; per-cell miss / width / tails before and after; minutes bias (the shock is
  mean-preserving before the renormalisation, so bias should barely move); the TRAIN numbers; the share of the real
  residual variance per cell that the sim already carries (1 / width²).

**If A FAILS:** stop and report which criterion. Readings fixed now: V1 fails with V2 passing → the miss is driven
by bias / shape, not spread (the next target is the bench bias +1.00 or the REAL_ONLY minutes); V3 fails → the
residual is skewed and a symmetric-in-logs shock is the wrong family (an empirical-ratio bootstrap would be the next
pre-registration); V4 fails → stats do not follow minutes 1:1 and the engine must carry the spread differently.

### Stage B — engine (only if A PASSES)

**Mechanism:**
- NEW `syndicate/features/shared/nba_sim_minutes_dispersion.py`, switch file `nba_sim_minutes_dispersion.json`
  carrying the frozen σ table. Absent file = off; `SYNDICATE_NBA_SIM_MINUTES_DISPERSION=0` kills it.
- Hook: the per-draw loop in `orchestrator/smart_sim.py` (~:1719). Before each `simulate_pbp_game_boxscore` call,
  shock each pool player's `_sim_min` by the same lognormal, renormalise to the team total and re-cap with the
  existing water-fill (`_derive_sim_minutes_local` caps). The draw's RNG is the draw's own (no shared-state seed
  drift between off and on beyond the shock draws themselves).
- One print line per game: `NBA_SIM_MINUTES_DISPERSION {applied, players, sigma_by_cell, mean_abs_shift}`.
- **Lane / files:** the hook section of orchestrator/smart_sim.py is added to this lane's `Files:` after a collision
  check at build time, not now.

**Reachability and pass-through, before any correctness read:**
- a unit test that on != off for `_sim_min` and for realised minutes;
- **pass-through**, on the smoke: regress each draw's realised minutes on its shocked target; slope ≥ .70. Known
  risk named now: when contextual rotation lineups (`home_lineups` / `away_lineup_w`) drive the possession sampler,
  per-possession selection may ignore `_sim_min` and the shock would be inert. If the slope is < .70, stop: the
  lineup weights must carry the shock, and that is a new pre-registration.

**Engine standard (docs/ai_context/model_engine_standard.md):** checklist entry CONSUMED × POPULATED; pipeline trace
with file:line; the switch file disk-backed and allowlisted in HOT_ARTIFACT_PATTERNS at build time; reachability
test first.

**Runs:** a 12-date smoke (the INJ smoke dates), then the full FIT `fit_disp` = fit_inj's config + the switch file.

**Gate B, on TEST dates only (all must hold):**
- (B1) bench and starter minutes miss each within .03 of stage A's emulated TEST value, and within [.15, .25];
- (B2) pts / reb / ast / threes miss: none worse than fit_inj by more than .005;
- (B3) game total mean within ±1.0 of fit_inj (mechanism-vs-estimator rule: moving minutes between players of
  different rates can move team scoring; if it moves more, the totals solver is re-fit before any stat read);
- (B4) team pts / reb / ast co-movement and the E4 combo widths reported (they consume per-player draws), no gate.

**Predictions, written now:**
- σ is larger for small m (bench) than for ≥ 28 (starters); bench σ ≥ .4.
- Stats miss improves in every stat in stage A (each sits at .23–.30 with minutes as the first-order driver), by
  less than minutes does.
- Minutes bias moves by < 0.2 in either role.

**Out of scope:** coach DNP (needs pre-tip news, step 2a); REAL_ONLY (6.19 real min per team-game); the bench bias
+1.00; production. Production gets fields only via `nba_engine_config.json` after the forward test from 11-01.

**STEP 3 STAGE A — RESULT 2026-10-31 20:42Z (15:42 CDT). VERDICT: FAIL (V3, starters only). Stage B is NOT built.**

`r2s/stage3a.py` → `stage3a.json`, `stage3a.out`; nice 19, about 13 min. 1,604 team-games; Phase-1 population TRAIN
8,324 / TEST 7,993 rows. No bin was pooled (smallest TRAIN bin < 6 min: 367). The cell m is the slot's fit_inj sim
mean minutes, as written.

**σ fitted on TRAIN** (2 rounds of coordinate descent, round 2 final): < 6: 1.05 · 6–12: 0.90 · 12–20: 0.50 ·
20–28: 0.20 · ≥ 28: 0.00.

| TEST (Jan–Feb) | before (fit_inj) | after | gate |
|---|---|---|---|
| bench min miss / width | .551 / 2.00 | **.239 / 0.97** | V1, V2 PASS |
| starter min miss / width | .324 / 1.22 | **.198 / 1.00** | V1, V2 PASS |
| bench tails p_lo / p_hi | .237 / .314 | .097 / .142 (gap .045) | V3 PASS |
| starter tails p_lo / p_hi | .163 / .161 | .133 / .065 (gap **.068**) | V3 **FAIL** (≤ .05) |
| pts / reb / ast / threes miss | .304 / .287 / .260 / .230 | .268 / .257 / .246 / .225 | V4 PASS |
| min bias bench / starter | +1.20 / −0.27 | +1.36 / −0.49 | — |

TRAIN reads the same: bench .239 / 0.97, starter .184 / 0.99 with tails .108 / .076.

**Predictions:** bench σ ≥ .4 — held. Every stat improves, by less than minutes — held. Minutes bias moves < 0.2 in
either role — FAILED for starters (−0.27 → −0.49, 0.22); bench moved 0.16. The renormalisation is not exactly
mean-preserving: bench draws pushed up take the team's minutes from everyone, starters included.

**Per-cell, TEST, descriptive (read after the verdict):**
- ≥ 28 (σ 0): miss .280 → .226, but tails .166 / .059 and bias −1.13 → −1.41. The sim gives its heaviest-minute
  players too many minutes; once the band is the right width, that bias shows up as a one-sided low tail. The
  starter V3 failure is this cell.
- < 6: miss .681 → .419, ALL of it high side (p_lo .000, p_hi .419), bias +4.7. These are players the sim barely
  plays who got real minutes: a mean error that spread alone cannot fix.
- 6–12 bias +3.0; 12–20 +1.4; 20–28 +0.3. The bias runs monotonically from bench (sim too low) to heavy starters
  (sim too high): the sim's minutes distribution is too CONCENTRATED on the top of the rotation.

**Reading (as pre-registered: "V3 fails → the residual is skewed and a symmetric-in-logs shock is the wrong family;
an empirical-ratio bootstrap would be the next pre-registration").** Disclosed alongside it, from the cell read above:
the starter imbalance coincides with a MEAN error (≥ 28 bias −1.41), not only with shape. The two are not separated
by this run. A spread fix with the right widths exposes the concentration bias rather than hiding it inside a too-
narrow band. Candidates for the next pre-registration, none chosen: (a) the empirical-ratio bootstrap (shape);
(b) a de-concentration of the input minutes by cell (mean: ≥ 28 down ~1.1, < 12 up ~3), then this same σ table
re-fit; (c) both, mean first per the mechanism-vs-estimator rule.
- Not done: no engine code, no switch file, no sim run.

## STEP 3b — MINUTES DE-CONCENTRATION (MEAN FIRST), PRE-REGISTERED 2026-10-31 21:03Z (16:03 CDT), before any de-concentrated draw exists

**User decision 10-31:** "pre-register the minutes de-concentration fix first". Order: fix the mean, then re-fit the
step-3 σ table on top (mechanism-vs-estimator rule). Baseline is fit_inj (d674e150); step-3 stage A (ed83c86ca)
measured the bias by input-minutes cell, TEST: < 6 +4.7 · 6–12 +3.0 · 12–20 +1.4 · 20–28 +0.3 · ≥ 28 −1.4.

**A caveat named now (selection):** the Phase-1 population is conditioned on PLAYED. Coach-DNP slots (real 0) are
out of it, and they sit mostly in the low cells. Part of the low-cell bias is therefore selection: given he played, a
fringe player plays more than the sim's average over draws. Raising low-m minutes to fit the played population also
raises the sim minutes of the players who then do not play. That cost is gated below (D3), not ignored. The ≥ 28 bias
has no such excuse: starters almost never sit.

### Stage A — offline (no sim run). Decides whether stage B is built.

**Mechanism, one parameter, emulated on fit_inj's recorded draws:** per team-game, each pool player's per-draw
realised minutes x_id are scaled by w_i = max(m_i, 1)^(β − 1), m_i = the slot's fit_inj sim mean minutes; then, per
draw, the pool is rescaled to the pre-shift team total and capped at game length (48 + 5·OT) with proportional
water-fill (step 3's code). β < 1 flattens the minutes distribution; β = 1 is fit_inj exactly. Stats scale by x'/x.
In the engine this is target'_i ∝ target_i^β, renormalised to the team total.

**Fit:**
- β on the grid {1.00, 0.97, …, 0.40} minimising Σ_c n_c·bias_c² over the five cells, on TRAIN (11-01..12-31).
- Then, on top of the fitted β, the step-3 σ table is RE-FIT on TRAIN with step 3's exact procedure (same cells,
  grid, 2-round coordinate descent, seed 0, |minutes miss − .20|).
- TEST (01-01..02-28) is graded once. Nothing is re-fit after TEST is read.

**Gate D, on TEST (all must hold):**
- (D1) minutes bias, de-concentration alone (σ = 0): |bench| ≤ 0.5 and |starter| ≤ 0.5 (from +1.20 / −0.27), and
  |≥ 28| ≤ 0.5 (from −1.41);
- (D2) the step-3 gates V1–V4 on the combined arm (β + re-fit σ): bench and starter minutes miss in [.15, .25],
  width in [.85, 1.15], |p_lo − p_hi| ≤ .05; pts / reb / ast / threes miss none worse than fit_inj by > .005;
- (D3) selection cost: coach-DNP slots' sim minutes per team-game (fit_inj TEST population, step 2a's
  classification) rise by no more than 1.0 over fit_inj.
- Reported, no gate: β; σ table; per-cell bias / miss / width / tails for β alone and combined; stats miss for β
  alone; REAL_ONLY untouched (no new players are added); the TRAIN numbers.

**Predictions, written now:** β in [0.6, 0.9]. The < 6 cell keeps a positive bias (selection plus REAL_ONLY-like
fringe minutes). Starter tails balance once ≥ 28 is unbiased, so V3 passes in the combined arm. The re-fit σ for the
low cells comes out smaller than step 3's (1.05 / 0.90), because part of their miss was mean.

**If D FAILS:** stop, report which. Readings fixed now: D1 fails → one power parameter cannot carry the shape; the
next candidate is a per-cell shift (5 parameters, more overfit risk). D1 passes but D2's V3 fails → the residual is
shape, and the empirical-ratio bootstrap is next. D3 fails → the low-cell bias is mostly selection, so it needs the
participation signal (pre-tip news, step 2a), not more minutes.

### Stage B — engine (only if D PASSES)

- One switch file `nba_sim_minutes_shape.json` carrying β and the σ table; absent = off;
  `SYNDICATE_NBA_SIM_MINUTES_SHAPE=0` kills it. NEW `syndicate/features/shared/nba_sim_minutes_shape.py`.
- β hook: where the per-player target minutes are final, after `_derive_sim_minutes_local` / the rotation-minutes
  path and before the per-draw loop (orchestrator/smart_sim.py, near `_sim_minutes_by_name` ~:2205 and the
  rotation minutes ~:1525). σ hook: the per-draw loop (~:1719), as in step 3.
- **Collision check at build time:** lane nba-lineup-pools (OPEN, session eb2ba139) feeds `home_lineups` /
  `away_lineups` into the same call; its `Files:` today is only todo.md #696, but the lineup weights decide who is on
  the floor. Pass-through (realised vs target slope ≥ .70, step 3's rule) is measured both with and without
  contextual lineups. The hook sections go into this lane's `Files:` after that check, not now.
- Engine standard: checklist CONSUMED × POPULATED, pipeline trace file:line, switch file disk-backed and in
  HOT_ARTIFACT_PATTERNS, reachability test (off != on) before any correctness read.
- Runs: 12-date smoke, then full FIT `fit_shape` = fit_inj's config + the switch file.
- Gate B, TEST dates: minutes bias and miss within .03 / 0.3 min of stage A's emulated values; stats miss none
  worse than fit_inj by > .005; game total mean within ±1.0 of fit_inj (if more, the totals solver is re-fit before
  any stat read); E4 combo widths and team co-movement reported.

**Out of scope:** coach DNP participation (needs news); REAL_ONLY (6.19); production. Production gets fields only via
`nba_engine_config.json` after the forward test from 11-01.

**STEP 3b STAGE A — RESULT 2026-10-31 22:08Z (17:08 CDT). VERDICT: FAIL (D1; D3 by 0.03). Stage B is NOT built.**

`r2s/stage3b.py` → `stage3b.json`, `stage3b.out`; nice 19, about 20 min. 1,604 team-games, TRAIN 8,324 / TEST 7,993
rows, 1,674 coach-DNP slots (matching step 2a). No bin pooled.

**Fit (TRAIN):** β = **0.85** (loss minimum; 0.82 and 0.88 either side). Re-fit σ: < 6 1.10 · 6–12 0.75 · 12–20 0.45
· 20–28 0.20 · ≥ 28 0.10 (step 3: 1.05 / 0.90 / 0.50 / 0.20 / 0.00).

| TEST (Jan–Feb) | fit_inj | β only | β + σ | gate |
|---|---|---|---|---|
| min bias bench / starter | +1.20 / −0.27 | **+0.53 / +0.66** | +0.66 / +0.48 | D1 ≤ 0.5 both: **FAIL** |
| min bias ≥ 28 | −1.13 | +0.07 | −0.14 | D1 ≤ 0.5: pass |
| bench miss / width | .551 / 2.00 | .543 / 1.92 | **.241 / 0.98** | V1, V2 pass |
| starter miss / width | .324 / 1.22 | .362 / 1.25 | **.180 / 0.97** | V1, V2 pass |
| starter tails lo / hi | .163 / .161 | .140 / .222 | **.101 / .079** | V3 pass (step 3: .133 / .065) |
| bench tails lo / hi | .237 / .314 | .263 / .280 | .117 / .124 | V3 pass |
| pts / reb / ast / threes miss | .303 / .287 / .262 / .231 | .300 / .279 / .253 / .233 | .264 / .246 / .239 / .222 | V4 pass |
| coach-DNP sim min / team-game | 9.30 | **10.33 (+1.03)** | 10.11 (+0.81) | D3 ≤ +1.0 on the larger: **FAIL** |

**Predictions:** β in [0.6, 0.9] — held (0.85). < 6 keeps a positive bias — held (+3.5 β only, +3.7 combined).
Starter tails balance in the combined arm — held (.101 / .079). Low-cell σ comes out smaller than step 3's — held
for 6–12 (0.75 vs 0.90) and 12–20; NOT for < 6 (1.10 vs 1.05).

**Why D1 cannot pass with any redistribution (descriptive, read after the verdict).** Minutes are conserved per team:
the sim hands out the team's minutes over the WHOLE pool, coach-DNP slots included, while the graded population is
only players who played. So the played population's summed bias is fixed by how many sim minutes go to players who
then sit (about 9.3 per team-game, plus ABSENT 1.2, minus REAL_ONLY 6.2), whatever the shape. A redistribution moves
the bias BETWEEN roles but cannot remove it; worse, flattening gives the low-m players more, and those are the ones
who sit, so the played population's total bias goes UP (+1.03 DNP min per team-game ≈ the observed rise). β fixed the
≥ 28 overallocation (−1.13 → +0.07) and moved the starter role's bias from −0.27 to +0.66 (top-5-by-input includes
20–28 starters, who lose minutes). This is a constraint of the target, not a failure of the power form, so the
pre-registered D1 reading ("next: per-cell shift") is disclosed as NOT applicable — a per-cell shift is bound by the
same sum. The D3 reading applies: the low-cell bias is selection and needs the participation signal (step 2a, news).

**What the run does show (not a verdict):** the combined arm (β 0.85 + re-fit σ) passes all of step 3's V1–V4 on TEST,
including the starter tail balance that failed step 3. Adopting it would mean changing the gates after reading TEST,
so it is not adopted here. The honest route is a NEW pre-registration of exactly that arm (β 0.85, this σ table,
frozen now) graded on data no fit has seen: the 2026-27 forward window from 11-01.
- Not done: no engine code, no switch file, no sim run.

## STEP 3c — MINUTES SHAPE (β + σ) FORWARD TEST, PRE-REGISTERED 2026-11-01 15:41Z (09:41 CST), before any 2026-27 game is simulated or scored

**User decision 11-01:** "pre-register the combined arm for the forward test". The arm was chosen after reading the
2025-26 TEST (step 3b, 9b093f716), so 2025-26 cannot grade it. The grade is forward only.

**FROZEN NOW (nothing below is re-fit, on any window):**
- Cells by m = the BASE arm's per-slot sim mean minutes over its own draws: {< 6, 6–12, 12–20, 20–28, ≥ 28}.
- Shift: x_id · max(m_i, 1)^(β − 1) with **β = 0.85**; per team-draw, rescale the pool to the pre-shift total, cap at
  game length (48 + 5·OT) with proportional water-fill.
- Then the shock x · exp(σ_c·z − σ_c²/2), z ~ N(0, 1) seed 0, rescale and cap again, with
  **σ = < 6 1.10 · 6–12 0.75 · 12–20 0.45 · 20–28 0.20 · ≥ 28 0.10**.
- Stats scale by x'/x. Code: `r2s/stage3b.py`'s `transform` with those constants (copied verbatim into the read
  script; the copy is diffed against stage3b.py before the read).

**Window and read timing:** the round-2 forward window (3020b556): 2026-27 REGULAR season from 2026-11-01. Read ONCE,
on the same date as the round-2 read (≥ 250 finals with pre-tip period lines AND ≥ 400 with full-game lines;
expected mid-to-late December). Before it: refresh the pristine mirror and as-of inputs through the read date, and
build the 2026-27 injury feed with `scripts/nba_injury_history_build.py --start 2026-11-01` (the same tip − 30 rule;
its B1–B3 gates must pass, or the read waits and says so). Nothing is scored before the read.

**Arms (same harness, same replay inputs, 200 draws, paired by game):**
- **BASE** = fit_inj's run exactly: code_inj, the fit_inj levers / engine flags / switch files
  (`r2s/launch_fit_inj.sh`), `--asof-roster --injury-history`, `--record-player-draws --track-oncourt`. Frozen as of
  now so the comparison isolates the minutes shape, not round 2's other changes.
- **SHAPE** = BASE's recorded draws transformed offline by the frozen rule above. No second sim run.

**Population:** Phase 1's (in the sim AND played; ESPN boxes); starter / bench = top-5 by input minutes.

**Gates, forward read (all must hold; game-clustered bootstrap, 2,000):**
- (F1) minutes miss, SHAPE − BASE, 95% CI upper < 0 for bench AND starter;
- (F2) SHAPE minutes, bench and starter: miss in [.15, .25], width in [.85, 1.15], |p_lo − p_hi| ≤ .05;
- (F3) pts / reb / ast / threes miss, SHAPE − BASE, CI upper < +.005 for each;
- (F4) coach-DNP sim min per team-game, SHAPE − BASE ≤ +1.0 (step 2a's classification).
- Reported, no gate: minutes bias by role and cell; per-cell miss / width / tails; widths of the stats; PRA and
  E4 combo widths; game totals (unchanged by construction offline — the engine is where they could move).

**Predictions** (from 2025-26 TEST; written now so the read can be compared): bench miss ≈ .24, starter ≈ .18;
pts / reb / ast / threes ≈ .26 / .25 / .24 / .22; coach-DNP +0.8. Early-season inputs are thinner than Jan–Feb, so
BASE's miss is expected WORSE than 2025-26's TEST and SHAPE's improvement larger, not smaller.

**On a PASS:** stage B (engine) is built: `nba_sim_minutes_shape.json` + `syndicate/features/shared/
nba_sim_minutes_shape.py`, β on the final target minutes, σ in the per-draw loop, all as step 3b's stage B (incl.
the collision check with nba-lineup-pools and pass-through ≥ .70 with and without contextual lineups). Its
equivalence check (engine within .03 miss / 0.3 min bias of the offline SHAPE) MAY use the forward games, because it
fits nothing; the game total must stay within ±1.0 of BASE or the totals solver is re-fit first. Production only via
`nba_engine_config.json`, and only on a user decision.

**On a FAIL:** nothing is built; report which gate. F1/F2 failing forward while they passed on 2025-26 would mean the
shape does not transfer across seasons (it was fitted on one); F4 → selection dominates, back to the participation
signal.

**Owner:** lane basketball-player-distribution reads it on the round-2 read date (basketball-scenario-calibration,
same session).

## STEP 4 — REAL_ONLY (PLAYED, NEVER SIMULATED), PRE-REGISTERED 2026-11-01 16:09Z (10:09 CST), before any REAL_ONLY slot is classified by cause

**User decision 11-01:** "pre-register the REAL_ONLY minutes fix". Baseline fit_inj (d674e150): 954 REAL_ONLY
player-games, **6.19 real min per team-game** (1,604 team-games): SIM_AROUND 701 (the sim has the player on that team
before AND after the date, not on it), SIM_LATER_ONLY 210 (roster lag / same-day signings), SIM_EARLIER_ONLY 36,
SIM_NEVER_T 7. By step 3b's conservation identity, every REAL_ONLY minute is a minute the sim gave someone else, so
this is the one lever that lowers the played population's summed bias instead of moving it.

**Interaction with step 3c (218c26dd), fixed now:** step 3c's BASE is frozen as fit_inj's config. Nothing in this
step changes that arm. A mechanism adopted here is tested in its own arm and enters a forward read only by its own
pre-registration.

### Stage A0 — census by cause (descriptive, no gate). Decides which mechanism stage A grades.

Each fit_inj REAL_ONLY slot (date d, team T, player X) gets the FIRST cause that applies:
- **C1 INJ_LISTED:** X is on the step-1d injury feed for d / T with an excluded status (OUT, DOUBTFUL, SUSPENDED,
  INACTIVE, REST). Known small (the 3 CHI 01-28 false exclusions).
- **C2 K2:** the K=2 rule would drop X: X has MIN > 0 for T in this season's regular-season player_logs before d, none
  in T's last 2 games, T has ≥ 2 games, and X has no posted pre-tip prop line in the replay's
  `oddsapi_player_props_<d>.csv` (the rule's re-admit). REPLICATED from `nba_sim_availability.py`'s docstring rule:
  its print line carries counts only, not names. Cross-check: the replicated per-date count of added players against
  the run's `added` where the logs carry it; a mismatch > 10% of slots is reported before any mechanism is graded.
- **C3 ROSTER:** X is not on T's as-of roster for d (`asof_roster`), i.e. SIM_LATER_ONLY / SIM_NEVER_T in practice.
- **C4 POOL:** none of the above: on the roster, eligible, and still not in `pnames` (the pool pruner, max_keep 13,
  or another pool step). Reported with its sub-split where the code path can be named.
- Reported per cause: slots, real min per team-game, share of the 6.19, month, 12 examples.

### Stage A — offline feasibility of the mechanism for the LARGEST cause (no sim run)

Exactly one mechanism is graded: the one matching the cause with the most real min per team-game. Each is fixed now.

- **If C2 (K2) is largest — M-K2, "K=2 defers to the injury report":** when an as-of injury report exists for T's game,
  K=2 does not drop a player who is NOT listed on it (the report is the newer evidence; K=2 was adopted 10-06,
  before any NBA injury history existed). Population = every K=2-dropped (d, T, X) on FIT not listed on the report
  (all of them, played or not, replicated as in C2). Proxy minutes p = X's mean MIN over his last 10 regular-season
  games played for T before d.
- **If C4 (POOL) is largest — M-POOL, pool depth:** max_keep 13 → 15, the two kept by the pruner's own order.
  Population = the players the larger pool would add; same proxy p.
- **If C3 (ROSTER) is largest:** no pre-tip source of same-day signings exists in the replay; stop and report it as a
  data-collection question (like coach DNP). No mechanism.
- **If C1 is largest:** the injury feed's status rule is re-read instead (report, no mechanism).

**Gate A, over all 109 FIT dates (no parameter is fitted, so no train / test split; both halves reported):**
- (A1) recovered: real minutes per team-game of the re-admitted players who PLAYED ≥ 50% of that cause's REAL_ONLY
  real min per team-game;
- (A2) cost: Σ p over re-admitted players who did NOT play ≤ Σ p over those who played — the mechanism puts at least as
  many expected minutes on players who played as on players who sat (step 2a's A2 logic);
- (A3) false re-admits of injured players: re-admitted players whose box reason names an injury or illness ≤ 10% of
  re-admitted slots.
- Reported, no gate: played rate of the re-admitted; real minutes of those who played (mean, distribution); the
  coach-DNP share of the non-players; Nov–Dec vs Jan–Feb.

**If A FAILS:** stop, report which. A1 → the cause is real but the mechanism reaches too little of it; A2 → the cause
cannot be separated from healthy scratches without pre-tip news (same reading as step 2a); A3 → the report misses
injured players and K=2 is carrying them.

### Stage B — engine / harness (only if A PASSES)

- M-K2: one switch key in `nba_sim_availability.json` (`"defer_to_injury_report": true`; absent = today's rule), read
  in `add_nba_recency_exclusions` with a count in its existing print line (`deferred_to_report`). M-POOL: the
  pruner's max_keep through the existing engine config. Lane `Files:` gets the touched section after a collision check
  (nba-sim-availability is NOT this lane's file today; the owner lanes are closed, nba-prop-calibration CLOSED-MET).
- Engine standard: checklist CONSUMED × POPULATED; trace file:line; reachability test (off != on) first; the switch
  file is already disk-backed.
- Runs: 12-date smoke (the INJ smoke dates), then the full FIT `fit_ro` = fit_inj's config + the switch.
- **Gate B (all FIT dates, paired by game vs fit_inj):** (B1) REAL_ONLY real min per team-game ≤ fit_inj's minus 50%
  of the stage-A recovered minutes; (B2) coach-DNP sim min per team-game rises by no more than the REAL_ONLY minutes
  it removes; (B3) minutes miss (bench, starter) and pts / reb / ast / threes miss none worse than fit_inj by > .005;
  (B4) game total within ±1.0 of fit_inj (else the totals solver is re-fit before any stat read).

**Predictions, written now:** C2 (K2) is the largest cause, at ≥ 50% of the 6.19 (SIM_AROUND is 701 of 954 slots,
and "on the team before and after, not on the date" is K=2's signature). M-K2's played rate among the re-admitted
lands in [.4, .7]: K=2's own 10-02 measurement had 539 played vs 2,501 non-players dropped BEFORE the injury feed;
the feed now removes the injured part of the non-players.

**Out of scope:** production (the K=2 rule is LIVE on the fleet; any change to it there is a user decision after a
forward read, and the live injury feed differs from this historical one); step 3c's frozen arms; coach DNP.

**STEP 4 — A0 CENSUS + STAGE A RESULT 2026-11-01 16:35Z (10:35 CST). VERDICT AS REGISTERED: FAIL (A2). Stage B is NOT
built. The replication is NOT faithful enough to trust either way (disclosed below).**

`r2s/stage4.py` → `stage4.json`, `stage4_pop.csv`, `stage4.out`; nice 19. 1,604 team-games, 954 REAL_ONLY slots,
6.19 real min per team-game (matches fit_inj). Every slot had an as-of roster file.

**A0 census** (first cause that applies):

| cause | slots | real min / team-game | share |
|---|---|---|---|
| C1 INJ_LISTED | 3 | 0.05 | 0.7% (the CHI 01-28 trio) |
| **C2 K2** | **779** | **4.73** | **76.4%** |
| C3 ROSTER | 44 | 0.30 | 4.9% |
| C4 POOL | 128 | 1.11 | 18.0% (Nov 44, Feb 58) |

Prediction "C2 is largest, ≥ 50% of the 6.19" — held. Disclosed: the replay holds NO `oddsapi_player_props_<d>.csv`
on FIT dates (9 files, all from 2026-05), so the rule's prop-line re-admit is inert in fit_inj; and the run logs
carry no per-date `added` line, so the pre-registered cross-check could not run.

**Stage A, M-K2 ("K=2 defers to the injury report")**, population = replicated K=2-dropped (d, T, X) not listed out
on the report, 1,582 team-games:

| | value | gate |
|---|---|---|
| re-admitted slots / played | 3,925 / 1,058 (27.0%) | — |
| (A1) recovered real min / team-game | 9.13 vs C2 4.73 | ≥ 50%: PASS |
| (A2) Σ p not played / Σ p played | 29,714 / 15,353 = **1.94** | ≤ 1: **FAIL** |
| (A3) re-admitted with an injury reason | 0.05% | ≤ 10%: PASS |

Halves: Nov–Dec A2 1.02, played rate .37; Jan–Feb A2 2.73, .21. Prediction "played rate in [.4, .7]" — FAILED (.27).

**FIDELITY PROBLEM (found by the numbers, read after the verdict).** The replicated population has 1,058 players who
PLAYED, but only 779 C2 slots exist: the replication drops ~280 players the real rule did not.
- The rule's TEAM KEY skip (a traded player is not excluded) was not replicated; 1,853 of the 2,867 non-players are
  NOT IN T's BOX at all — mostly traded / waived players, who are not in T's pool anyway.
- The rest is unexplained: ~250 players the replication drops who played AND were simulated.
- Post-hoc sensitivity (`r2s/stage4_fidelity.py`, NOT a verdict): restricted to players on T's as-of roster for d,
  2,671 slots, played rate .385, **A2 = 0.95** (Nov–Dec 0.87, Jan–Feb 1.01), recovered 8.91 (still > 4.73, so the
  replication still over-drops). On a closer population A2 sits at the boundary, not clearly on either side.

**Reading:** C2 is the cause (76% of REAL_ONLY). Whether deferring to the report is worth its cost is NOT decided by
this run: the registered verdict is FAIL, and the sensitivity says that FAIL is largely traded players the real rule
never drops. The decisive population is the rule's OWN list of dropped names, which no log carries. A faithful
re-grade needs the rule to print its names in the research harness (or a harness smoke of M-K2 measured directly).
Either is a NEW pre-registration with the same A1–A3; not done.
- Not done: no engine code, no switch key, no sim run.

## STEP 4b — M-K2 RE-GRADE ON THE RULE'S OWN NAMES, PRE-REGISTERED 2026-11-01 17:05Z (11:05 CST), before any name is logged

**User decision 11-01:** "pre-register the re-grade on the rule's actual names". Step 4 (33d07f61) graded M-K2 on a
REPLICATED population that over-drops (1,058 played vs 779 C2 slots; traded players not in T's pool). This re-grade
changes ONLY the population source. M-K2, the proxy p, the gates A1–A3 and their thresholds are step 4's, verbatim.

**Instrument (research tree only, never on main):** `~/bball_sc/code_names` = code_inj + a print-only patch:
- in `nba_sim_availability.add_nba_recency_exclusions`, keep the set of keys the K=2 rule ADDED per team;
- in smart_sim's `_drop_excluded` (orchestrator/smart_sim.py ~:1353), print one line per team-game,
  `K2_EFFECT {date, team, removed: [keys the K=2 set removed from that team's candidate frame], added: [all K=2 keys
  for the team]}`.
- The **effect set** (keys that actually left a candidate frame) is the graded population, not the added set: a key
  added for a player the sim would never have pooled for T (traded, waived) changes nothing and is not re-admitted
  by anything.
- The patch prints only; it must not change any pool. Patch diff is committed to the findings with its line count.

**Run `fit_names`:** fit_inj's exact config and inputs (`r2s/launch_fit_inj.sh`, code_names instead of code_inj),
--n-sims 20 (draw count does not touch pool construction), 3 workers, nice 19, all 109 FIT dates.

**Fidelity gates (checked BEFORE A1–A3 are computed; if either fails, stop and report — no grade):**
- (F1) `pnames` per team-game identical to fit_inj on ≥ 99% of team-games (the patch did not move a pool);
- (F2) ≥ 95% of step 4's 779 C2 REAL_ONLY slots appear in the effect set for their (d, T).

**Population:** every (d, T, key) in the effect set, minus keys listed with an excluded status on the step-1d report
for (d, T) (those stay dropped under M-K2). Outcome from the ESPN box: played (MIN > 0), DNP with reason, or not in
box. p = the player's mean MIN over his last 10 regular-season games for T before d (step 4's proxy).

**Gate A (all 109 dates; halves reported), verbatim from step 4:**
- (A1) real min per team-game of re-admitted players who PLAYED ≥ 50% of C2's 4.73;
- (A2) Σ p over re-admitted who did not play ≤ Σ p over those who played;
- (A3) re-admitted with an injury / illness box reason ≤ 10%.
- Reported: played rate; coach-DNP share of non-players; not-in-box count; how many C2 slots fall outside the effect
  set and why; step 4's replicated numbers beside these.

**Known limit, written now:** A1 is an UPPER bound. A re-admitted player still passes through the pool pruner
(max_keep 13) and may be cut; only stage B's harness run measures what reaches the pool.

**Predictions:** F1 and F2 hold. A2 lands within ±0.15 of step 4's as-of-roster sensitivity (0.95); I do not predict
its side of 1. Played rate in [.35, .50].

**If A PASSES:** stage B exactly as step 4 pre-registered (switch key `defer_to_injury_report`, 12-date smoke, full
FIT `fit_ro`, gates B1–B4). **If A FAILS:** M-K2 is closed; the 4.73 joins coach DNP as needing pre-tip news.

**STEP 4b — M-K2 RE-GRADE ON THE RULE'S OWN NAMES, RESULT 2026-11-01 19:50Z (13:50 CST). VERDICT: FAIL (A2). M-K2 is
CLOSED as pre-registered (3995a90d): the 4.73 real min per team-game joins coach DNP as needing pre-tip news.**

Instrument `~/bball_sc/code_names` = code_inj + print-only patch (`r2s/make_code_names.py`, diff
`r2s/code_names.diff`, 44 lines: a `K2_ADDED` print in `add_nba_recency_exclusions`, a `K2_EFFECT` print in
smart_sim `_drop_excluded` with the filter mask computed once into `_hit`, same predicate). Run `fit_names`
(`r2s/launch_fit_names.sh` = launch_fit_inj.sh with code_names, 20 draws, own out/scratch), 12:57-13:49 CST, nice 19,
109/109 dates. Disclosed: the patch prints two lines (ADDED per team, EFFECT per call) where the pre-registration
described one combined line; the effect set is their intersection per (d, T), as registered. Grader `r2s/stage4b.py`
-> `stage4b.json`, `stage4b_pop.csv`, `stage4b.out`.

**Fidelity (checked first):**
- (F1) pools identical on **1,590 / 1,590** team-games as sets -> PASS. **Disclosed change of reading, made after an
  8-date dry check and BEFORE the grade:** 1,565 / 1,590 are identical in ORDER. `pnames` order is the first draw's
  box order, which moves with the draw count (20 vs 200); membership is what the patch could move, so the gate was
  read on membership. On the ordered reading F1 is 98.4% and would have failed by 0.6 pt.
- (F2) **777 / 779** C2 slots in the effect set (99.7%) -> PASS. Outside: 1 not named by the rule, 1 named but not
  in any candidate frame. The rule's own summary line was identical to fit_inj's on the dates spot-checked
  (11-01..11-03).
- Instrument: 14,407 keys named across 3,204 team-dates; **6,513** actually left a candidate frame (45%). The other
  55% (traded / waived / never pooled for T) is what over-dropped step 4's replication.

**Gate A, verbatim from step 4, population = effect set minus report-listed, 1,582 team-games:**

| | step 4b (rule's own names) | step 4 (replicated) | gate |
|---|---|---|---|
| re-admitted slots / played | 3,057 / 768 (25.1%) | 3,925 / 1,058 (27.0%) | — |
| (A1) recovered real min / team-game | **4.72** vs C2 4.73 | 9.13 | ≥ 50%: PASS |
| (A2) Σ p not played / Σ p played | 20,589 / 7,509 = **2.74** | 1.94 | ≤ 1: **FAIL** |
| (A3) injury / illness reason | 0.07% | 0.05% | ≤ 10%: PASS |

Halves: Nov-Dec A2 2.02, played .31; Jan-Feb A2 3.34, played .21. Coach-DNP share of non-players .44; not in T's box
1,286 (42% of slots).

**Predictions:** F1, F2 held. A2 "within ±0.15 of 0.95" — **FAILED** (2.74). Played rate "[.35, .50]" — **FAILED**
(.25). Step 4's as-of-roster sensitivity (0.95) was NOT a good proxy for the real population: the real effect set
keeps far more players who are in the frame yet absent from the box.

**Post-hoc (`r2s/post4b.py`, NOT a verdict):** restricted to players who appear in T's box, 1,771 slots, played .434,
**A2 1.15** — still > 1. The FAIL does not rest on the not-in-box slots. In-box non-players are 999 COACH'S DECISION
of 1,003. Not-in-box p median 7.6 min (IQR 4.0-13.8), so they are real rotation-share players, not zeros.

**Reading:** the K=2 rule removes about exactly the C2 minutes (A1 4.72 ≈ 4.73 — the effect set IS C2's source), but
for every proxy-minute it would recover by deferring to the report, it would put 2.7 proxy-minutes on players who do
not play — mostly coach's decisions and players absent from the box entirely. The injury report does not separate
them. Nothing changes in code or config; the K=2 rule on the fleet is untouched.

**2026-27 INJURY FEED BUILT (step 3c prerequisite, 218c26dd) 2026-11-02 14:32Z (08:32 CST). Registered window
B1-B3 PASS on the one slate so far; a 10-20..10-31 shakedown (NOT the feed) fails B2 on real healthy teams.**

`r2s/build_inj2627.sh <end> [<backup stamp>]` (re-run it with the read date before the forward read):
`scripts/nba_injury_history_build.py` unchanged, tip − 30 rule. Inputs:
- ESPN games: `basketball_scenario_rates.py real --start 2026-10-20` into its own dir `C:/tmp/bball_sc/inj2627/real`
  (92 finals through 11-01, 0 fails).
- Official PDFs in `inj2627/pdfs` (57 fetched, 0 missing on the host).
- Roster `rosters_2026-27.csv` + `player_logs.csv` copied from the fleet's daily backup `20261102T091500Z` (read only;
  the live tree not touched). **Disclosed choice:** player_logs restricted to SEASON_ID 22026 (2,048 rows through
  11-01): an all-seasons log would put a summer mover with no 2026-27 game yet on LAST season's team in asof_roster,
  which feeds the parser's name repair.

**Feed `inj2627/injury_history_nba_2026-27.csv`** (`--start 2026-11-01 --end 2026-11-01`, sha256 6566bbe709d812c9…):
4 games, 8 team-games, 34 rows, all OUT; B1 0 games without a report, B2 8/8, B3 0/34 off roster -> PASS. Report age
30 min on every game.

**Shakedown `inj2627/shakedown_2026-10-20_10-31.csv`** (NOT the feed; run to test this season's PDF format on more
than one slate): 88 games, 571 rows, B1 PASS, B3 19/571 = 3.3% PASS, **B2 163/176 = 92.6% FAIL**. All 13 unlisted
team-games were read in the PDF text: 7 have no section for the team at all, 6 list only "Available" players (the
parser keeps OUT / DOUBTFUL / QUESTIONABLE / PROBABLE). MIL 6, MIA 5, NYK 1, NOP 1 (10-23 MIL: absent from that game's block; the report's MIL "NOT YET SUBMITTED" row
belongs to 10-24's game). The parser lost
nothing; teams are healthy at the start of the season. Status mix OUT .986 / Q .011 / P .004 vs 2025-26's .996 /
.002 / .002 — no sign of a format change.

**Risk to the forward read, flagged now:** B2's 95% bar came from Nov-Feb 2025-26, when injuries had accumulated. If
a few healthy teams persist, B2 can fail on the forward window for the same benign reason, and 218c26dd says the read
then WAITS. Whether to amend B2 (e.g. "every unlisted team-game is verified absent-or-Available in the PDF text")
is a pre-registration change for the user to decide BEFORE the read; nothing is amended here.

**PRE-REGISTRATION — B2' AMENDMENT to step 3c's (218c26dd) injury-feed gate B2, 2026-11-02 16:50Z (10:50 CST), on the
user's request ("pre-register the B2 amendment"). Registered BEFORE any forward-window data past 11-01 exists; the
forward feed so far (11-01) passes the original B2 8/8.**

**Why:** B2's 95% bar was set on 2025-26 Nov-Feb. The 2026-27 shakedown (10-20..10-31, outside the window) lists 92.6%
of team-games, and all 13 unlisted were healthy teams (see the feed-build record above). Under 218c26dd a B2 miss makes
the read WAIT, so healthy teams alone could hold the read indefinitely. An unlisted team-game puts no rows in the feed
either way; what B2 has to rule out is a team that HAD out players and was lost in parsing.

**Rule (replaces only how a B2 miss is handled; B1 and B3 are unchanged; applies only to the step-3c forward feed,
2026-11-01..read date; not retroactive):** the feed gate passes on B2 if EITHER
- (B2) listed ≥ 95% of team-games, as registered; OR
- (B2') ALL of:
  - (i) listed ≥ 85% of team-games (floor against a wholesale format break);
  - (ii) EVERY unlisted team-game is classed ABSENT or AVAILABLE_ONLY by the verifier;
  - (iii) control: ≥ 99% of LISTED team-games are classed HAS_STATUS (the verifier can see a real listing).
Otherwise the read waits, as registered. NOT_SUBMITTED, HAS_STATUS (a parse loss), EMPTY_SECTION, NO_BLOCK and NO_REPORT
are never benign. When B2' is what passes, the read reports both B2 and B2' and lists every unlisted team-game.

**Verifier** `C:/tmp/bball_sc/r2s/b2_verify.py` (not in git, like stage3b.py), **sha256 07dd34db7551897989aacd278c1ac84a4d891a4e7fcc421a3498f3b2c69b6c67**,
checked before the read. For each team-game it re-picks the build's own tip − 30 report (`pick_report`), reads the
text with pypdf, finds the game's block (`AWY@HOM` token to the next `@` token) and the team's section inside it by
nickname, and classes it. HAS_STATUS (Out / Doubtful / Questionable / Probable) is checked before NOT YET SUBMITTED.
LISTED = the feed CSV has a row for (date, team), the build's own definition. `r2s/build_inj2627.sh` now runs it over
2026-11-01..END after the feed (output `inj2627/b2v_feed.json`), so re-running the build before the read produces it.

**Calibration (all outside the forward window, or the one forward slate already seen):**

| run | team-games | listed | unlisted classes | control (listed HAS_STATUS) | B2 | B2' |
|---|---|---|---|---|---|---|
| shakedown 10-20..10-31 | 176 | 163 (92.6%) | ABSENT 7, AVAILABLE_ONLY 6 | 163/163 | fail | pass |
| feed 11-01 | 8 | 8 | — | 8/8 | pass | pass |
| 2025-26 FIT 11-01..03-01 | 1,640 | 1,627 (99.2%) | AVAILABLE_ONLY 6, ABSENT 3, **NOT_SUBMITTED 4** | 1,627/1,627 | pass | (ii) fails |

- The shakedown classes reproduce the hand check exactly (7 no section, 6 Available-only; same team-games).
- The 2025-26 run shows the failing branch fires: 4 unlisted team-games on 2026-01-25 (DEN@MEM, DAL@MIL) were NOT YET
  SUBMITTED at tip − 30, so B2' alone would NOT have cleared that season; it passed on the original B2.
- **Disclosed design change before the freeze:** the first version checked NOT YET SUBMITTED before real statuses; on
  2025-26 that classed 16 LISTED team-games as NOT_SUBMITTED (their game block runs on into a later NOT YET SUBMITTED
  line), control 99.02%. The order was swapped; the control is now 100% on all three runs. For an unlisted team-game
  the swap cannot make anything benign (both classes fail (ii)).
- **Disclosed:** the 85% floor was chosen after seeing the shakedown's 92.6%; it is not fitted to a pass/fail edge on
  any run above.

- **Wiring checked:** the full `build_inj2627.sh 2026-11-01` re-run (10:42 CST) printed the verifier's sha256 and
  B2_amended_pass true; the feed CSV is byte-identical (sha256 6566bbe709d812c9...).

**Before the read:** re-run `build_inj2627.sh <read date> <newer backup stamp>`; check the verifier's sha256 (printed by
the script) and stage3b.py / launch_fit_inj.sh as already registered; read `feed.json` B1/B3 and `b2v_feed.json`
`B2_amended_pass`. Nothing changes in code or config; nothing is scored.

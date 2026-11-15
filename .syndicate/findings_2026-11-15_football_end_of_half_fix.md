# Findings 2026-11-15 — the end-of-half fix for smartsim2 (todo #808)

Lane `football-end-of-half-fix`, session 69e3a2e5. Started from session 4c32cb26's brief for todo #808. The
engine files are a LOAN from lane `football-scenario-calibration` (user picked "Loan" in chat, 2026-11-15;
recorded on main `ec6002505`). Diagnosis this builds on: `findings_2026-11-15_football_end_of_half_scoring.md`.

Nothing here ships. Code goes on a branch. A push to `main` and any fleet load need the user's OK.

## PRE-REGISTRATION — written 2026-11-15 10:32 CST (commit `03d1066c6`), BEFORE any sim run or league-input measurement in this lane

### The change (ONE change plus a re-fit, `model_engine_standard.md` §4.4)

Three parts. Every new switch is a declared `CalibrationProfile` field, default OFF, byte-identical when OFF.

1. **`halftime_kickoff` ON.** Already built and tested (lane `football-scenario-calibration` H1).
2. **`q2_urgency_ignores_score` (NEW, default OFF).** In Q2 only:
   - the urgency field goal (`drive_simulator.simulate_drive`, gate `-9 <= diff <= 2`) fires at any score;
   - the two-minute drill (`situation_model.classify_urgency`, `diff <= 7`) fires at any score.
   Q4 is unchanged. The halftime kneel (`URGENCY_HALFTIME_PRESERVATION`) still takes precedence.
3. **`end_of_half_clock` (NEW, default OFF).** It applies in regulation Q2 and Q4 only (never Q1/Q3, never OT).
   - **Per-team timeouts:** 3 a half, carried on `PossessionState` (new fields, serialised only when not
     None, so OFF output is unchanged). Reset to 3 at the start of the second half.
   - **The two-minute warning (NFL only; NCAAF has none):** a step that starts above 120 s and would end below
     it stops at 120. If its live play itself crosses 2:00, it stops after the play.
   - **Steps that start inside the last 120 s:** their clock comes from a MEASURED table instead of the sim's
     `expected_clock_seconds x clock_base` draw.
     - The clock stops after an incompletion, after an out-of-bounds play (drawn at the measured rate), and
       after a timeout. The offense or the defense calls one at measured rates while it has one.
     - The clock otherwise runs, by the offense's urgency mode (hurry / preservation / neutral, from
       `classify_urgency` with the part-2 rule).
     - A drive-ending step (TD, FG made or missed, punt, turnover, turnover on downs, safety) consumes the
       measured time to the next snap of the half, so the kickoff or return is included.
   - **NCAAF:** its own table, measured the same way from CFBD plays. No two-minute warning. A first down
     stops the clock in the last 2 minutes (the 2023 rule), measured as its own category.
   - **No fitted dial in the clock.** Every number in the table is measured from FIT-season play-by-play. If
     the snaps miss, that is a FAIL, not a reason to tune.

Not in this change, reported only:
- the two-minute drill's explosive x1.60 and TD +0.04 boosts (trailing by 10+: 2.20 points per end-of-half
  drive against the league's 1.63);
- spikes (0.14 a game in Q2's window);
- live re-sims' real timeouts left. The engine takes `initial_timeouts_home/away` (default None -> 3), but
  nothing feeds it yet. Wiring the live producers is a follow-up, and it gates any live use of the switch.

### Measured inputs (the clock table) — how they will be measured

Source: nflverse pbp 2024-25 REG (local mirror `data/nfl_source/tracking/nflverse/pbp/`; an external historical
set, complete for these seasons, not a production artifact). Window = `quarter_seconds_remaining <= 120` in
Q2 and Q4. A snap is a pass, run, field_goal, punt, qb_kneel or qb_spike row.

Script: `scripts/football_end_of_half_clock_rates.py` (in the repo, so the table can be reproduced).

**Elapsed time.** Delta = the clock at this snap minus the clock at the next snap of the same half, by category:
- incomplete pass;
- out of bounds (`out_of_bounds == 1`, not a scoring or turnover play);
- a play followed by a timeout row before the next snap;
- an in-bounds play with the clock running, by urgency mode;
- penalty (`no_play`);
- each drive-ending result (TD, FG good, FG missed, punt, turnover, turnover on downs, safety).

**Censoring rule.** For running-clock categories, a snap with no next snap in the half is censored. The mean is
taken over snaps starting at >= 45 s, where censoring is rare. The censored share is printed beside each cell.

**Probabilities.**
- `p_oob[mode]`: out of bounds, among runs and completed passes that are not a TD or a turnover.
- `p_to_off[quarter][mode]`: an offense timeout right after a clock-running play, given it has one left.
- `p_to_def[quarter][defense trailing?]`: a defense timeout right after a clock-running play, given no
  offense timeout and the defense has one left.

**Urgency mode** is computed on the REAL situation with the candidate's own rule (`classify_urgency`, Q2
score-blind). The table is therefore keyed on the same function the sim uses.

**NCAAF:** the same definitions over CFBD plays 2024-25 FBS-vs-FBS REG (local mirror
`data/ncaaf_source/historical_truth/plays_<s>_wk<w>.json.gz`, `clock` per play, `Timeout` rows,
`offenseTimeouts`, "out of bounds" / "1ST down" in `playText`).

### Data splits

**FIT: NFL 2024-25 REG.**
- League targets: all 2024-25 games in nflverse (544).
- Sim: every 4th completed 2024-25 game, the SAME 136 games as the diagnosis, x 100 seeds (seeds 1..100), the
  same seeds in every arm.
- Production's own `generate_smartsim2_nfl_projections.build_projection`, in production's env via
  `football_scenario_rates._nfl_init`, profile as shipped plus the arm's overrides.
- `PYTHONHASHSEED=0`, Idle priority.

**HELD-OUT: NFL 2026 REG weeks 1-8.**
- 121 completed games, all with a close in `schedules_games.csv`.
- Private root `C:\tmp\football_scenarios\nfl_root_2026`, pulled 2026-11-03 for the calibration lane's v2 read.
  That read needed >= 128 games and has no recorded result, so 2026 is unread for pregame. Nothing in this
  lane is tuned on 2026.
- 1000 seeds a game in both arms: seed noise in a game's win probability is ~0.016 at 1000 seeds, against
  ~0.029 at 300.

**NFL 2025 is not used as held-out.** The calibration lane spent it (2026-10-07), and the 2024-25 league quarter
targets include its outcomes, which would leak the total's level into a total Brier gate.

**NCAAF arms:** the 2024 FBS-vs-FBS REG task list of `football_scenario_rates.ncaaf_tasks([2024], ...)`, every
4th game, x 100 seeds, via `_ncaaf_init` (production's promoted profile `ncaaf-goal-line-refit-1`).
- League reference: CFBD 2024-25.
- These numbers are DESCRIPTIVE. NCAAF 2025 and 2026 are both spent as held-out (calibration lane), so
  switching NCAAF on would need its own pre-registered held-out design, which is the user's decision.

### Arms (NFL FIT; every arm the same games and seeds)

| arm | halftime_kickoff | q2_urgency_ignores_score | end_of_half_clock | re-fit levers |
|---|---|---|---|---|
| `off` | - | - | - | production |
| `ht` | ON | - | - | - |
| `ht_gates` | ON | ON | - | - |
| `full` | ON | ON | ON | - |
| `fit[...]` | ON | ON | ON | grid below |

### The re-fit (pre-registered grid; nothing outside it is tried without an amendment written first)

The mechanism moves two things a calibrated rate was absorbing: the scoring level (the total) and the home edge.
- The halftime switch takes the second-half kick from the team that held the ball at the half. Measured upstream
  as a home margin of -0.85.
- The sim gives the home team the opening kick.

**Two levers, both existing profile fields, fitted in this order:**

- **R1, home edge, `home_field_bonus`.** Grid {0.0, 0.03, 0.06, 0.09, 0.12, 0.15}, at
  `touchdown_weight_multiplier` 1.0. Pick the value whose FIT mean home margin is closest to `off`'s on the same
  games and seeds. Production's margin is the reference, because it is calibrated against the market (#686
  notes).
- **R2, scoring level, `touchdown_weight_multiplier`.** Grid {1.00, 0.975, 0.95, 0.925, 0.90, 0.875}, at R1's
  value. Pick the minimiser of Q = sum over q1..q4 of ((sim_q - league_q) / se_q)^2, where se_q = the league
  2024-25 CI half-width / 1.96.
- **R3, one pass only.** If R2's choice moves the mean home margin more than 0.15 from `off`'s, redo R1 once at
  R2's value. Stop there.

**Ties:** within 0.25 of Q, take the value closer to 1.0 (the smaller change).

### Gates

**B — byte identity, OFF.**
- sha256 over `SmartSim2SimulationOutput.to_dict()` for seeds 1..20 on three input shapes (pregame NFL default
  profile; pregame NCAAF default profile; a Q2 resume) must equal the digest from the pre-change code.
- Computed by a test before the first edit and pinned in it.

**R — reachability.** Each new switch alone: ON != OFF on the same seeds (asserted in tests) before any
correctness read.

**FIT gates, at the re-fitted candidate.** All must pass.
- G1: each quarter's points a game inside the league 2024-25 95% CI:
  - q1 [8.46, 9.40];
  - q2 [13.47, 14.59];
  - q3 [9.01, 10.00];
  - q4 [12.54, 13.84].
- G2: Q2 last-120 s points a game inside [4.46, 5.10].
- G3: Q2 last-120 s snaps a game inside the league's 95% CI.
  - That CI is computed with the same game bootstrap as G1/G2 (2000 reps, seed 3) by
    `football_end_of_half_clock_rates.py` before the sim's figure is read.
  - The sim's snaps count every step starting at <= 120 s in Q2 except PENALTY steps: the league count excludes
    `no_play`. The count including penalties is reported beside it.
- G4: the sim's first-half points a game > its second-half points (regulation; league 22.95 vs 22.67).

**FIT, reported (not gating):**
- Q4 last-120 s snaps (league 7.38) and points (league 2.63 [2.31, 2.96]);
- the end-of-half kick rate by score bucket;
- drives in Q2's window, and the short final possessions (first window snap < 30 s; league 0.62 a game);
- regulation total;
- the trailing-by-10+ points per drive.

**Held-out gates (NFL 2026 wk1-8, candidate vs `off`, paired by game, game-bootstrap 95% CI, 2000 reps).**
- HB-ML: home-win Brier (ties dropped).
- HB-TOT: Brier of P(total > close total).
  - P is taken from the 1000 per-seed totals, shifted by the production generator's own `total_mean -
    mean(totals)` correction.
  - A seed exactly on the line counts half. Games landing on the line are dropped.
- HB-SPR: Brier of P(home margin > -close spread). Same push rule.
- **Each gate PASSES unless the candidate is SHOWN worse:** the 95% CI lower bound > 0, or the point estimate >
  +0.003.

**False-fail rate under a true null, stated now** (learnings 2026-10-05).
- The calibration lane's paired Brier reads on 136 games had CI half-widths of 0.005-0.0065 at 300 seeds.
  Expected here: SE ~0.0015-0.0025.
- Per gate, P(fail | no effect) = P(lo > 0) + P(point > 0.003): about 0.03-0.14.
- Over three gates: about 0.10-0.35.
- A FAIL whose CI straddles 0 will be reported as "not shown non-inferior", not as "worse".
- The calibration lane's convention (upper bound < +0.003) is NOT used. At this n it fails a true null about
  half the time.

**Also reported, not gating:** margin and total MAE against the actual result, and |sim - close| for margin and
total.

### Predictions (written before any run)

| # | prediction |
|---|---|
| P1 | B holds: the OFF digests are unchanged. |
| P2 | R holds for both new switches. |
| P3 | `full` (no re-fit), FIT: Q2 last-120 s snaps 9.5-11.5 (`ht_gates` ~7.3); Q2 last-120 s points 4.4-5.3; q3 9.3-9.9; total minus `off` +0.2..+1.5; home margin minus `off` -1.2..-0.5. |
| P4 | `full`: Q4 last-120 s snaps 6.0-8.0 (`off` 4.75); Q4 last-120 s points 2.3-3.2. |
| P5 | Re-fit lands at `touchdown_weight_multiplier` in [0.90, 0.975] and `home_field_bonus` in [0.03, 0.15]. |
| P6 | All FIT gates pass at the candidate. The two at risk are q1 (upper bound 9.40; the sim runs 9.68 today) and q2's lower bound. |
| P7 | Held-out: all three Brier deltas inside +-0.003; none shown worse. |
| P8 | NCAAF `full`: Q2 last-120 s points move from the sim's level toward the league's 5.27, and q3's surplus shrinks. |

**Decision rule.**
- If every FIT gate and every held-out gate passes, the candidate profile values are recorded here and handed to
  the user. Shipping to NFL is a profile change plus a fleet load, and it is the user's call.
- The market test after any load is the segment re-grade: #752 (`scripts/nfl_segment_skill.py`) and #805.
- If any gate fails, nothing ships. The switches stay in the code, default OFF, and the failure is written up.

### Amendment 1 — 2026-11-15 10:50 CST (commit `c9ea2e486`), after the clock table and a SMOKE run, BEFORE any FIT read

**What the smoke run was.**
- Neutral teams (all ratings 0), the DEFAULT profile, 300-400 seeds, no FIT game.
- Script `C:\tmp\football_eoh_fix\mix.py` / `smoke.py`.
- Nothing from the 136 FIT games or 2026 was read.

**What it showed.** `full` puts 8.7 snaps in Q2's last 120 s, against the league's 10.5 counted the same way. The
clock table itself reproduces the league's per-category times: incompletions 4.8 s in both, punts 8.9 s in both,
TDs 7.8 / 7.6 s. **The gap is the play mix:**

| Q2's last 120 s, per game | league | sim `full` |
|---|---|---|
| incompletions | 2.30 | 1.20 |
| in-bounds plays (incl. out of bounds and timeouts) | 6.25 | 5.81 |
| kicks, TDs, turnovers | ~2.0 | ~1.7 |

The sim's two-minute drill throws about 17% incompletions. The league throws about 27% in that window.

**Amendment.** Add one more MEASURED input to the clock table: `p_incomplete[mode]`.
- Definition: P(incomplete pass | an offensive play in the window), by urgency mode.
- An offensive play is a run or pass row, sacks, kneels and turnovers included, spikes, kicks and no-play
  penalties excluded.
- Measured the same way as the rest of the table (nflverse 2024-25; CFBD 2024-25 for NCAAF), by
  `football_end_of_half_clock_rates.py`.

**How the sim uses it (only with `end_of_half_clock` ON, only for a snap in the window):**
- `play_simulator._play_outcome_weights` sets the INCOMPLETE_PASS weight so that its share of the non-penalty
  outcomes equals `p_incomplete[mode]`.
- Every other outcome keeps its relative weight, and PENALTY keeps its own weight.

**Why this is a measured input and not a fitted dial.**
- It is set to the league's observed share. Nothing is chosen to hit the snap count, and G3 stays a check on
  everything together.
- It touches `play_simulator.py`, which is on the loan.

**What stays unchanged.**
- Every gate, the re-fit grid, the predictions (P3 is now expected nearer its centre) and the decision rule.
- The two-minute drill's other boosts (explosive x1.60, TD +0.04) are still reported only.

### Amendment 2 — 2026-11-15 10:55 CST (commit `f551cdcb0`), after a second SMOKE run, BEFORE any FIT read. The LAST change to the clock.

**What the smoke run was.** The same neutral-team smoke as Amendment 1, with `p_incomplete` in. Scripts
`C:\tmp\football_eoh_fix\bucket.py` / `bucket2.py`. No FIT game and no 2026 game was read.

**What it showed.**
- Q2-window snaps 9.18 against the league's 10.49, counted the same way.
- The shortfall sits at the end of the window. Snaps a game by clock bucket:

| bucket | league | sim |
|---|---|---|
| 90-120 s | 2.42 | 2.95 |
| 60-90 s | 2.08 | 2.32 |
| 30-60 s | 2.62 | 2.00 |
| 0-30 s | 3.37 | 1.92 |

**The cause is a design error in the pre-registered table.** Its pooled cells cannot represent behaviour that
changes across the window (nflverse 2024-25, Q2+Q4 window):

| cell | 90-120 s | 60-90 s | 30-60 s | 0-30 s |
|---|---|---|---|---|
| running-clock hurry, mean seconds | 24.9 | 20.4 | 14.0 | 9.0 (41% censored) |
| p_incomplete, hurry | 0.203 | 0.231 | 0.255 | 0.331 |
| p_oob, hurry | 0.162 | 0.188 | 0.241 | 0.255 |
| offense timeout, Q2 hurry | 0.012 | 0.050 | 0.192 | 0.212 |

- The pre-registered running-clock cell used snaps at >= 45 s only (the censoring floor). It therefore measured
  the slow part of the window and applied it everywhere: 22.15 s.

**Amendment.** The table keys these cells on a clock bucket as well as their existing key. A step's bucket is
0-30 / 30-60 / 60-90 / 90-120 s left at its snap (`> 90`, `> 60`, `> 30` boundaries).
- `run_hurry`, `run_preserve`, `to_off`, `to_def`: (mean, sd) by bucket.
  - **Censoring rule (replaces the >= 45 s floor):** a bucket whose censored share exceeds 0.15 takes the
    (mean, sd) of the nearest bucket with more time left whose censored share is <= 0.15.
  - Applied that way: `run_hurry` 0-30 <- 30-60; `run_preserve` 0-30 and 30-60 <- 60-90; `to_def` 0-30 <- 30-60.
  - In the sim, a draw longer than the clock left ends the half, which is how the real censoring arises.
- `p_incomplete`, `p_oob`, `p_to_off`, `p_to_def`: by bucket, with no censoring issue (each is the event after
  the play).
  - A cell with no league observation is unreachable under the mode function (Q2 preserve exists only at
    <= 60 s) and is set to 0.0.
- Drive-ending cells, `incomplete`, `oob` and `penalty` stay pooled. Their means are flat across buckets
  (e.g. incompletions 4.8-4.9 s, punts 9.0-9.3 s).
- NCAAF: the same structure, measured from CFBD, the same rule.

**Binding.**
- This is the last change to the clock mechanism before the FIT read.
- The next smoke run is a functional check only. The FIT read runs whatever it shows.
- If FIT misses G3, it is a FAIL and is reported as one. No third clock amendment.

### Amendment 3 — 2026-11-15 11:01 CST (commit `afb93d837`), after Amendment 2's functional check, BEFORE any FIT read. The LAST pre-FIT change of any kind.

**What the functional check showed.**
- The neutral smoke with Amendment 2 in (`bucket.py`) gives Q2-window snaps 8.9: by bucket 2.50 / 2.09 / 2.24 /
  2.09 against the league's 2.42 / 2.08 / 2.62 / 3.37.
- So the last 60 s are still short.
- Amendment 2's binding stands: the clock table is not changed again.

**What a read-only look found (`fgtiming.py`): a defect in PART 2's rule, not in the clock.**
- The urgency field goal fires on ANY down once the clock is <= 90 s and the offense is in range.
- The sim kicks on downs 1-3 at 60-90 s left (0.28 a game) and 30-60 s left (0.16 a game).
- The league NEVER kicks on downs 1-3 before the last 30 s. Its 139 such Q2-window attempts in 2024-25 came at a
  median 3 s left, 90th percentile 6 s, maximum 11 s.
- The league keeps driving and kicks at the end. The sim's drive stops at 1:25, which costs its own remaining
  snaps and its touchdown chance.
- Part 2 makes this worse: removing the score gate extends the early kick to every Q2 score.

**Amendment (Q2 only; only with BOTH `q2_urgency_ignores_score` and `end_of_half_clock` ON).**
- On downs 1-3, the Q2 urgency kick waits until the clock left is <= the time a running-clock play takes in the
  last bucket: the table's own `delta_by_bucket["run_hurry"][0]` mean, 14.0 s NFL / 14.6 s NCAAF.
  - The rule a coach without a timeout follows: if one more running play could end the half, kick now.
  - No new parameter. It is the clock table's measured value.
- On 4th down, the existing <= 90 s rule is unchanged.
- **Q4 is unchanged**, though it has the same defect. Q4's urgency rules are out of this change's scope and go
  to a follow-up.
- With the clock OFF, part 2 keeps the <= 90 s rule. The timing rule needs the clock's stops to be sane: without
  them, a drive waiting for 14 s would usually run the clock out.

**Binding.**
- Nothing else changes before the FIT read.
- The FIT arms and the re-fit grid run as pre-registered, and every gate is read as written.
- A FIT miss is a FAIL. Any later candidate needs a new pre-registration, and it is the user's call.

**Known structural gap, stated now:** the league's G3 count includes spikes (0.14 a game in Q2's window), which
the sim does not model.

## Results — 2026-11-15, FIT arms run ~11:06-12:08 CST (`off` finished 11:11 after 4.6 min; file mtimes), written 12:2x-12:3x CST

### Verdict: FAIL on FIT. Nothing ships, and the held-out read was NOT run.

**Where it failed.**
- At every point of the pre-registered re-fit grid, G3 (Q2's last-120 s snaps) and G4 (H1 > H2) fail.
- At the grid's best point, G1-q2 and G2 fail as well.
- Per the decision rule, nothing ships. The switches stay in the code, default OFF.

**Why NFL 2026 wk1-8 stayed unread.**
- The held-out read gates shipping, and this candidate cannot ship.
- 2026 is the only clean NFL held-out set left. Spending it on a FAIL would leave a fixed v2 nothing to be judged on.
- Whether to read it anyway is the user's decision (the calibration lane's precedent: "Validate only if FIT beats
  production").

**Code (branch only, not pushed):** `79dbfb23c` (`cfbbb8b91` / `de59ab7e7` before rebases onto main) on `claude/admiring-gould-5c7128`.
- The mechanism and its 3 amendments, all default OFF.
- Tests: `tests/test_football_end_of_half_clock.py`, 22 tests. With the engine suites, 160 passed (Idle, finished 11:12 CST).
- B: OFF byte-identical. The three pinned sha256 digests (NFL pregame, NCAAF pregame, NFL Q2 resume) equal the
  pre-change engine's.
- R: each switch alone changes the output.

### FIT read

Setup:
- NFL, every 4th completed 2024-25 game (136), 100 seeds, the same seeds in every arm.
- Production's `build_projection` in production's env. Harness `C:\tmp\football_eoh_fix\fit.py`, reader `analyze.py`.
- **The harness reproduces the diagnosis exactly:** `off` q1-q4 9.68 / 12.54 / 10.52 / 13.10, Q2 last-120 s 3.14
  points, 6.71 snaps with penalties, the same kick rates by bucket. `ht` gives q3 -0.95 and total -1.05;
  `ht_gates` gives q2 +0.22.

| arm | q1 | q2 | q3 | q4 | H1 / H2 | total | home margin | Q2 last-120 s pts / snaps | Q4 last-120 s pts / snaps | Q |
|---|---|---|---|---|---|---|---|---|---|---|
| league 2024-25 | 8.93 [8.46, 9.40] | 14.02 [13.47, 14.59] | 9.50 [9.01, 10.00] | 13.17 [12.54, 13.84] | 22.95 / 22.67 | 45.62 (reg) | | 4.78 [4.46, 5.10] / 10.63 [10.41, 10.86] | 2.63 [2.31, 2.96] / 7.38 [7.08, 7.68] | |
| `off` (production) | 9.68 | 12.54 | 10.52 | 13.10 | 22.22 / 23.62 | 45.95 | +1.93 | 3.14 / 6.50 | 2.25 / 4.59 | 52.8 |
| `ht` | 9.68 | 12.54 | 9.57 | 12.98 | 22.22 / 22.54 | 44.90 | +0.94 | 3.14 / 6.50 | 2.30 / 4.63 | 36.9 |
| `ht_gates` | 9.68 | 12.76 | 9.46 | 12.99 | 22.44 / 22.45 | 45.02 | +1.01 | 3.36 / 7.05 | 2.31 / 4.63 | 29.4 |
| `full` | 9.68 | 13.80 | 9.90 | 14.22 | 23.48 / 24.12 | 47.72 | +1.26 | 4.40 / 9.19 | 3.48 / 7.85 | 22.9 |
| R1 pick `h0.03_t1.0` | 9.76 | 14.05 | 9.98 | 14.30 | 23.80 / 24.27 | 48.19 | +1.98 | 4.47 / 9.22 | 3.49 / 7.83 | 27.0 |
| **R2 pick `h0.03_t0.875`** | 9.28 | **13.42** | 9.53 | 13.74 | **22.70 / 23.27** | 46.08 | +1.67 | **4.32 / 9.32** | 3.32 / 7.85 | **9.58** |

Snaps exclude penalty steps; with them, `full` has 9.49. Paired against `off`, `full` moves: total +1.76
[+1.58, +1.95], home margin -0.67 [-0.87, -0.48], q2 +1.26 [+1.19, +1.33], q3 -0.62 [-0.73, -0.51], Q2 last-120 s
snaps +2.69 [+2.64, +2.74].

**Re-fit, as registered.**
- R1 (`home_field_bonus`, at TD multiplier 1.0): margins +1.26 / +1.98 / +2.52 / +3.18 / +3.80 / +4.34 for
  0 / .03 / .06 / .09 / .12 / .15. **0.03 is closest to `off`'s +1.93.**
- R2 (TD multiplier, at 0.03): Q is 27.0 / 22.1 / 17.2 / 12.9 / 10.1 / **9.6** for 1.0 / .975 / .95 / .925 /
  .90 / .875. **0.875 wins, at the grid's edge.**
- **R3 was NOT run (a deviation, stated here).** R2's choice moved the margin -0.26 from `off`, which triggers R3.
  It could not change the verdict: across all 11 grid points, Q2-window snaps stay at 9.19-9.32 against
  [10.41, 10.86], and H2 > H1 at every point.

**Gates at the R2 pick.**

| gate | result |
|---|---|
| G1 q1 | 9.28 PASS |
| G1 q2 | 13.42 **FAIL** (< 13.47) |
| G1 q3 | 9.53 PASS |
| G1 q4 | 13.74 PASS |
| G2 | 4.32 **FAIL** (< 4.46) |
| G3 | 9.32 **FAIL** (< 10.41) |
| G4 | 22.70 vs 23.27 **FAIL** |

**Predictions.** Held: P1, P2, P4 snaps (7.85), P3's Q2 points (4.40), q3 (9.90) and margin (-0.67), and P5's
home bonus (0.03). Failed: P3 snaps (9.19 < 9.5) and total (+1.76 > +1.5), P4 Q4 points (3.48 > 3.2), P5's TD
multiplier (0.875 < 0.90), P6. P7 was not read.

### What the mechanism did and did not fix

Diagnostic after the read, `full` on 34 FIT games x 50 seeds (`diag.py`); it changes nothing registered.

1. **Q2: the shape is mostly fixed.**
   - Q3's carry-over is gone (q3 9.53-9.90 against 9.50).
   - Q2's last 120 s gained +1.26 points and +2.7 snaps.
   - The end-of-half kick is now flat in score (0.16-0.19 a drive across buckets, 0.14-0.29 `off`). It is lower
     than the league's 0.25-0.30, because the kick now waits until 14 s.
   - **The remaining snap gap is all in the last 60 s.** Snaps a game by bucket: 0-30 s league 3.37 / sim 2.26;
     30-60 s 2.62 / 2.26; 60-90 s 2.08 / 2.05; 90-120 s 2.42 / 2.64.
   - Not modelled: spikes (0.14 a game), and a team in range calling its timeout ON PURPOSE to set up the kick.
     The sim's timeouts are drawn at the measured average rates, not by need.
2. **Q4: the clock exposed a pre-existing scoring defect; it did not create one.**
   - Q4's window gets near the league's snaps (7.85 vs 7.38). But Q4-window points rise to 3.48 (league 2.63
     [2.31, 2.96]), and Q4 to 14.22, so H2 > H1.
   - The source: TDs by the LEADING team in end-game preservation, 1.37 points a game.
   - `URGENCY_END_GAME_PRESERVATION` (Q4, <= 150 s, leading) adds gain weight, cuts incompletions and explosives,
     and never cuts the TD weight. A team that should kneel keeps scoring.
   - The clock's defensive timeouts (Q4 trailing defense, 0.20-0.29 a play) give it more snaps to do so.
   - Q4's last 30 s now carry 2.09 snaps a game against the league's 1.43.
   - Q4 also keeps the <= 90 s any-down urgency kick, which is out of scope here.
3. **The scoring-level lever is weak and near the edge of its grid.** About -0.4 total per -0.025, so the level
   fix lands at 0.875, the grid's edge. Q1 still runs high (9.28-9.68 against 8.93), as the diagnosis found.

### NCAAF arms (descriptive)

Setup:
- Production's NCAAF `build_projection` via `_ncaaf_init` (profile `ncaaf-goal-line-refit-1`).
- The 2024 FBS-vs-FBS REG task list, every 4th game: 164 games x 100 seeds, the same seeds per arm
  (`fit_ncaaf.py`, finished 12:35 CST).
- The league reference is CFBD 2023-25 (2,627 games; points placed at drive-end clocks), so read it as a level,
  not a gate.
- NCAAF ran without a re-fit, as registered: it is descriptive.

| arm | q1 | q2 | q3 | q4 | H1 / H2 | total | home margin | Q2 last-120 s pts / snaps | Q4 last-120 s pts / snaps |
|---|---|---|---|---|---|---|---|---|---|
| league CFBD 2023-25 | 11.37 | 16.23 | 11.65 | 13.83 | 27.60 / 25.48 | | | 5.27 [5.07, 5.48] / 10.59 [10.43, 10.76] | 3.07 [2.85, 3.29] / 7.25 [7.06, 7.45] |
| `off` | 11.37 | 13.78 | 11.71 | 14.36 | 25.15 / 26.07 | 51.33 | +1.58 | 2.86 / 6.34 | 2.47 / 4.55 |
| `ht` | 11.37 | 13.78 | 10.71 | 14.44 | 25.15 / 25.15 | 50.41 | +0.77 | 2.86 / 6.34 | 2.53 / 4.58 |
| `ht_gates` | 11.37 | 13.61 | 10.80 | 14.52 | 24.98 / 25.32 | 50.42 | +0.85 | 2.69 / 7.17 | 2.58 / 4.57 |
| `full` | 11.37 | 15.64 | 11.32 | 16.36 | 27.01 / 27.68 | 54.81 | +0.88 | 4.73 / 9.67 | 4.33 / 8.13 |

Paired against `off`, `full` moves: total +3.48 [+3.29, +3.68], home margin -0.70 [-0.99, -0.42], q2 +1.87
[+1.79, +1.94], q3 -0.39 [-0.52, -0.25].

**Reading.** The same shape as NFL, more strongly.
- **Part 1, the halftime kickoff:** q3 -1.00.
- **Part 2 alone LOWERS NCAAF Q2 by -0.17** (NFL: +0.22). Its kick-rate effect is not NCAAF's lever.
- **The clock closes most of the Q2 gap.** Q2's last 120 s go from 2.86 to 4.73 points (league 5.27) and from 6.34
  to 9.67 snaps (league 10.59).
- **Q4 over-scores more than NFL:** 16.36 against 13.83, Q4-window points 4.33 against 3.07. H2 > H1, against the
  league's 27.60 / 25.48.
- **P8 held:** Q2's window points moved toward 5.27, and q3 fell.
- NCAAF needs the same Q4 fix as NFL ((a) below), plus its own level re-fit. Its held-out seasons are spent
  (2025, 2026), so any NCAAF promotion needs a new held-out design from the user.

### What a v2 would need (for the user to decide; nothing here is pre-registered)

- **(a) The leader's run-out in Q4.** In end-game preservation, a leader kneels: cut its TD and FG weights, or
  route it to kneels. That is a mechanism, with the league's leading-team Q4-window points as the measured target.
- **(b) Clock management by need in the last minute.**
  - A team in range with a timeout calls it to set up the kick.
  - A team without one spikes.
  - The last-minute snaps are the remaining Q2 gap.
- **(c) The same Amendment-3 kick timing in Q4**, which keeps the <= 90 s any-down kick.
- **(d) A scoring-level lever with reach.** The TD multiplier needs a wider grid, or a different lever.
- **(e) Before any live use:** the live producers must pass the real timeouts left (`initial_timeouts_home/away`).
  Nothing feeds them today.

A v2 is a new pre-registration and a new FIT read. 2026 wk1-8 is still unread for NFL.

---

## V2 — PRE-REGISTRATION DRAFT, written 2026-11-15 13:0x CST, BEFORE any v2 code or v2 sim run

**Status:** DRAFT (user: "Yes, draft the v2"). Nothing below is built. Building and running it is the user's
next call.
**Branch:** v1 is at `79dbfb23c` on `claude/admiring-gould-5c7128` (rebased again, onto main `2c9fed5ed`). v2
builds on it.

### Design inputs, measured AFTER the v1 FIT read and BEFORE this draft

Both are read-only diagnostics (`C:\tmp\football_eoh_fix\diag2.py`, `diag3.py`). They compare v1 `full` on 34 FIT
games x 50 seeds with nflverse 2024-25. They apply the rule this lane learned: measure what the engine does PER
SNAP in every state the new snaps fall into, before adding snaps.

**Q4's last 120 s, points a game, by offense.**

| offense | league | v1 sim |
|---|---|---|
| LEADING | 0.44 | **1.69** |
| trailing or tied | 2.11 | 1.83 |

**Leaders' plays (Q4 preserve mode).**
- 2.16 a game in the league against 3.47 in the sim.
- TD share per play: league 0.000-0.029, sim 0.050-0.081.
- Incompletion share at 0-60 s: league 0.006, sim 0.105-0.136.
  - Cause: v1 POOLED Q2 and Q4 preserve. Q2's "halftime preserve" leaders still throw 0.21-0.27 incompletions;
    Q4's run-out throws almost none.
- Sack share in preserve: league ~0.00-0.02, sim 0.06-0.12.
- The sim's leaders run more plays (more stops) and score on them. Real leaders kneel.

**Q2's last 30 s, the remaining G3 gap.**

| per game | league | v1 sim |
|---|---|---|
| drives alive | 1.47 | 1.25 |
| plays per drive | 2.40 | 1.81 |
| offense with 3 timeouts left | 16% | 71% |
| offense with 0 timeouts left | 21% | 0.5% |

**What the timeout data rules out.**
- The league's offense-timeout rate after a clock-running hurry play FALLS with timeouts left:
  - 0-30 s: 1 left 0.315, 2 left 0.161, 3 left 0.016;
  - 30-60 s: 1 left 0.307, 2 left 0.224, 3 left 0.015.
- Teams still holding 3 at the end are not trying to save time.
- Keying the sim's timeout rate on timeouts left would therefore CUT its stops, because its teams arrive with 3.
- The real gap is that the sim never spends timeouts outside "after a clock-running play". The league spends
  ~2.84 a game in Q2's window, ~1.05 of them there, and more before the window.

**Ruled out:** a censoring fix for the last-30 s running-clock cell. Kaplan-Meier on the league's 504
censored-or-observed snaps gives a restricted mean of 14.1 s (median 12, S(30) 0.176), the same as the borrowed
14.0 s.

### The v2 change (one change plus a re-fit; every new switch a declared field, default OFF, byte-identical)

**V2-a. `end_of_half_kneel_out` (NEW; needs `end_of_half_clock` ON for the timeouts).** In Q4 end-game
preservation and Q2 halftime preservation, before the play is drawn:
- If the offense can run out the clock by kneeling, it kneels. The condition:
  `clock <= PLAY_CLOCK * max(0, downs_left - defense_timeouts) + KNEEL_LIVE * downs_left`, with
  `downs_left = 5 - down`.
- `PLAY_CLOCK` = 40 s is the rule.
- `KNEEL_LIVE` is measured: the league's qb_kneel delta when a timeout follows.
- A kneel is a GAIN of -1 yard and cannot score, turn the ball over or be sacked.
- Its clock: if the defense has a timeout, it calls one (the formula assumes it does) and the kneel takes
  `KNEEL_LIVE`. Otherwise it takes the measured kneel delta with no timeout.
- When the clock cannot be run out, the preserve play is drawn as now.

**V2-b. Window cells keyed by QUARTER as well.**
- `p_incomplete`, `p_oob`, and `delta_by_bucket` `run_*` / `to_*` become `"<q>_<mode>"`-keyed, like `p_to_off`.
- Re-measured by the same script, with the same Amendment-2 censoring rule.

**V2-c. The window's non-scoring outcome mix.** Amendment 1's share-setting extends from incompletions to SACKS
and TURNOVERS:
- `p_sack` and `p_turnover`, by `"<q>_<mode>"` and bucket, are the league's shares of offensive plays.
- The other outcomes keep their relative weights, and the TD weight keeps its field-position dependence.
- Not setting the TD share is deliberate. A flat per-snap TD share would make a TD from the own 20 as likely as one
  from the opponent's 5.

**V2-d. Spikes.**
- After a clock-running play in hurry mode that drew no timeout, the offense spikes at the measured rate.
- The rate is P(spike | Q2/Q4 hurry, bucket, offense timeouts left == 0).
- A spike is its own step: an incompletion with 0 yards, which uses a down. It counts as a snap (the league count
  includes spikes).
- The preceding play then consumes the measured time to the spike (a new cell, `to_spike`).

**V2-e. The Amendment-3 kick timing in Q4 too.** A Q4 urgency kick on downs 1-3 waits until one more running-clock
play could end the game. Q4's score gate (-9..2) is unchanged.

**V2-f. NOT in v2, stated as a limit.**
- Timeouts spent outside "after a clock-running play": the offense before the window, and the defense to save time
  after a punt.
- These need a decision model, not a rate. G3 may still miss because of them; see the gate note below.

### Re-fit (pre-registered grid, wider than v1)

- **R1** `home_field_bonus` {0.0, 0.03, 0.06, 0.09, 0.12}, at TD multiplier 1.0. Closest to `off`'s mean home
  margin wins.
- **R2a** `touchdown_weight_multiplier` {1.0, 0.95, 0.90, 0.85, 0.80, 0.75}, at R1's value. Minimise v1's Q.
- **R2b** +-0.025 around R2a's choice. The final choice is the minimiser across R2a and R2b.
- **R3** One R1 pass at R2's value if the margin moved > 0.15. Run it this time unless it provably cannot change
  the verdict, and say so.

### Gates (FIT: the same 136 games x 100 seeds, same seeds; held-out as v1)

- **G1-G4** exactly as v1.
- **NEW G5:** Q4 last-120 s points a game inside the league's [2.31, 2.96]. It is the direct target of V2-a and
  V2-c.
- **Reported, not gating:**
  - Q4 last-120 s snaps (7.38 [7.08, 7.68]);
  - leader / trailer Q4-window points (0.44 / 2.11);
  - Q2 last-30 s drives and plays per drive;
  - the kick rate by score bucket.
- **Multi-gate false-fail note** (learnings 2026-10-05):
  - G1-G5 are "inside the league CI" checks of a mechanism, not tests of a null.
  - The sim's own SE over 13,600 game-seeds is < 0.1 points, so a FAIL means the sim's mean is outside the
    league's CI. It is not noise.
- **Held-out:** NFL 2026 wk1-8 (121 games, the 11-03 private pull, unread), 1000 seeds a game, HB-ML / HB-TOT /
  HB-SPR with v1's "shown worse" rule. **Read ONLY if every FIT gate passes**, so the last clean NFL set is not
  spent on a FAIL.
- **NCAAF:** the same arms, descriptive. NCAAF's held-out seasons are spent.

### Decisions this draft leaves to the user

1. **Build and run v2 as drafted?** About 2-3 h, mostly Idle sim time.
2. **G3.** Keep it gating as in v1, or demote it to reported? V2-f's limit makes G3 the gate most likely to miss.
   - Demoting it would be a CHANGE of the success criterion. It must be decided BEFORE the v2 FIT read and
     recorded here.
   - The market-relevant gates are G1 (quarters), G2 (Q2's window points), G4 (H1 > H2) and G5 (Q4's window
     points). The #752 / #805 segment re-grades are the market test after any load.
3. **The held-out pull.** Use the 11-03 pull (121 games), or OK a fresh nflverse download (weeks 9-10, ~150
   games, more power)? The 11-03 pull was ~44 MB for weeks 1-8, from nflverse's GitHub releases.

### Predictions (v2 `full2`, before the re-fit; written before any v2 run)

| # | prediction |
|---|---|
| V2-P1 | OFF byte-identical (the v1 digests); each new switch reachable. |
| V2-P2 | Q4-window LEADER points 0.25-0.80 (v1 1.69, league 0.44); Q4-window points 2.2-3.0 (G5); Q4 13.0-13.9. |
| V2-P3 | H1 > H2 at `full2` (G4). |
| V2-P4 | Q2-window snaps 9.4-10.2. **G3 is more likely to FAIL than pass** under V2-f's limit. Q2-window points 4.4-5.0. |
| V2-P5 | Total minus `off` between -0.5 and +1.5 before the re-fit; the re-fit's TD multiplier lands in [0.85, 1.0]. |
| V2-P6 | NCAAF `full2`: Q4 falls toward 13.83 (v1 16.36); H1 > H2. |

### V2 — PRE-REGISTERED 2026-11-15 13:0x CST (this section supersedes the draft above wherever they differ), BEFORE any v2 code or v2 sim run

**Decision.** The user asked for the v2 to be built ("build the v2 in the fix session", relayed by session
4c32cb26). The scope relayed:
- Q4 leaders kneel instead of scoring;
- timeouts and spikes used when a team needs them in the last minute, not at average rates;
- the same field-goal timing in Q4;
- a scoring-level lever with more reach.
Same rules as v1.

**Defaults taken, since no decision came back on them:**
- G3 stays GATING.
- The held-out is the 11-03 pull (121 games), read only if FIT passes.

**One design check before this text (`C:\tmp\football_eoh_fix\need.py`, league only, read-only).** In the last
60 s, after a clock-running hurry play, P(offense timeout | >= 1 left):

| Q2 zone | 1 left | 2 left | 3 left |
|---|---|---|---|
| own half | 0.214 | 0.133 | 0.090 |
| 50-64 | 0.378 | 0.294 | 0.067 |
| range (>= 65) | 0.386 | 0.287 | 0.041 |

- Q4 runs 0.12-0.32 at 1-2 left, ~0.0-0.03 at 3 left.
- Spike next (no timeout called): 0.31-0.50 with 0 timeouts left, 0.00-0.02 with >= 1, in every zone.

**What "need" means here, from that check.**
- FIELD POSITION is the need signal for timeouts.
- RUNNING OUT of timeouts is the need signal for spikes.
- **Timeouts left is NOT used as a key for the timeout rate.** The 3-left rows are a selection effect: league teams
  that still hold 3 at the end of the half are mostly not saving time. The sim's teams arrive with 3 regardless
  (71% of the time against the league's 16%). That key would import the selection without the behaviour.

**Switches** (declared fields, default OFF, OFF byte-identical to the v1 digests).

1. **`end_of_half_kneel_out` (NEW, = V2-a).**
   - Applies in Q4 end-game preservation and Q2 halftime preservation, with `end_of_half_clock` ON.
   - Before the play: if `clock <= 40 * max(0, downs_left - defense_timeouts) + KNEEL_LIVE * downs_left`
     (`downs_left = 5 - down`), the offense kneels.
   - A kneel is a GAIN of -1 yard, with no score, turnover or sack.
   - Its clock comes from the window machinery as a clock-running play: the defense may call a timeout at the
     measured rate. Otherwise it takes the measured kneel delta (`kneel`, by quarter).
   - `KNEEL_LIVE` = the league's kneel delta when a timeout follows.
2. **`end_of_half_clock_by_need` (NEW, = V2-d plus need-based timeouts).** In the window, in hurry mode:
   - The offense-timeout rate after a clock-running play is keyed on quarter x clock bucket x field-position zone
     (own < 50 / 50-64 / range >= 65), pooled over timeouts left. It replaces v1's `p_to_off[<q>_hurry]`.
   - With 0 timeouts left and no timeout called, the offense spikes at the measured P(spike | quarter, zone), in the
     last 60 s only.
   - A spike is its own step: an incompletion, 0 yards, a down used. It counts as a snap.
   - The play before it takes the measured `to_spike` delta, and the spike itself the measured `spike` delta.
   - Preserve mode and the defense keep v1's rates.
3. **`q4_kick_waits` (NEW, = V2-e).** In Q4, with `end_of_half_clock` ON, an urgency kick on downs 1-3 waits until
   the clock is <= the last-bucket running-play delta (Amendment 3's rule). Q4's -9..2 score gate is unchanged.
4. **`end_of_half_clock`, its table REVISED (= V2-b, V2-c).**
   - `p_incomplete`, `p_oob`, `delta_by_bucket` `run_*` / `to_*` are keyed `"<q>_<mode>"`.
   - New `p_sack` and `p_turnover` shares, by `"<q>_<mode>"` x bucket, applied like `p_incomplete`. Every other
     outcome keeps its relative weight; the TD weight is not set.
   - v1's own results stay tied to `79dbfb23c`. v1 never shipped, so the revision replaces it.

**Measurement.**
- Every new cell is measured from nflverse 2024-25 (CFBD 2024-25 for NCAAF) by
  `scripts/football_end_of_half_clock_rates.py`, before any v2 sim run.
- The Amendment-2 censoring rule applies to every delta cell.
- A cell with fewer than 30 observations takes its pooled-over-quarters value, and the table says so.

**Arms (NFL FIT: the same 136 games x 100 seeds, same seeds).**
- `off2`: production re-run on today's code, which must reproduce v1's `off` exactly.
- `full2`: v1's three switches + the revised table + the three new switches.
- `full2_nokneel`: `full2` without `end_of_half_kneel_out`. Reported, for attribution.
- The re-fit: R1 / R2a / R2b / R3 as in the draft.

**Gates.**
- G1-G5 as in the draft: G3 GATING, G5 = Q4 last-120 s points in [2.31, 2.96].
- The held-out is read only if all five pass (2026 wk1-8, 121 games, 1000 seeds, the "shown worse" rule).

**Predictions** are the draft's V2-P1..P6, with V2-P4 sharpened: `end_of_half_clock_by_need` adds +0.1 to +0.6
Q2-window snaps over `full2_nokneel`'s Q2 count. **G3 is still predicted to FAIL** (Q2-window snaps 9.4-10.2).

**Binding.**
- One functional smoke run is allowed, for bugs only.
- Any design change after this point is an amendment, written and landed on main before the FIT read.
- After the FIT read, nothing changes for this candidate.

### V2 Amendment 4 — 2026-11-15 13:20 CST, after measuring the v2 table, BEFORE any v2 code or v2 sim run

**`KNEEL_LIVE` in the kneel-out formula is the measured `spike` delta, not "the kneel delta when a timeout
follows".**

**Why the pre-registered definition fails its purpose.** The formula needs the kneel's own length: the clock a kneel
uses when the defense stops it at once. The registered cell measures something else:
- 42 NFL kneels followed by a DEFENSE timeout: median 32 s, 25th percentile 5 s, 75th 40 s. Defenses often let the
  clock run before calling.
- Taken as `KNEEL_LIVE`, its mean of 26 s would let a team "kneel out" 2:24 against 3 timeouts:
  40 x 1 + 26 x 4 = 144.

**The replacement.** A spike is the same snap-and-down play, and the table measures it: NFL 1.0 s (n 146);
NCAAF 4.1 s (CFBD end-of-play clocks, noisier).

**Unchanged.** The kneel's clock in the sim still comes from the window machinery. When the defense calls a
timeout, the step takes the measured `<q>_to_def` cell, which includes that waiting, as the data shows.

**Also recorded (a build note, decided before any v2 output was seen).** Kneels are left out of the denominators of
`p_incomplete` / `p_sack` / `p_turnover`, because v2 draws kneels separately.

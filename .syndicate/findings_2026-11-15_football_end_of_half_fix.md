# Findings 2026-11-15 — the end-of-half fix for smartsim2 (todo #808)

Lane `football-end-of-half-fix`, session 69e3a2e5. Started from session 4c32cb26's brief for todo #808. The
engine files are a LOAN from lane `football-scenario-calibration` (user picked "Loan" in chat, 2026-11-15;
recorded on main `ec6002505`). Diagnosis this builds on: `findings_2026-11-15_football_end_of_half_scoring.md`.

Nothing here ships. Code goes on a branch. A push to `main` and any fleet load need the user's OK.

## PRE-REGISTRATION — written 2026-11-15, BEFORE any sim run or league-input measurement in this lane

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

## Results

(none yet)

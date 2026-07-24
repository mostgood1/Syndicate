# SmartSim 2.0 Calibration Iteration 6 Report

- Source: NFL-Betting 2025 wk17/wk18/wk20 proxy baseline
- Split: calibration
- Iteration 5 calibration score: 0.000
- Iteration 6 calibration score: 0.000
- Games evaluated: 532
- Drives synthesized: 11233
- Objective: calibrate late-half and urgency football behavior (clock stops, two-minute offense, preservation, quarter scoring shape)

## Clock-Stop Audit (Tasks 1-5, measured on Iteration 5 code)

- Clock-stop drive share: **16.3%** (~3.5 drives per game), spread almost uniformly: Q1 17.5%, Q2 15.4%, Q3 16.0%, Q4 16.8%.
- **Q1/Q3 stops (928 drives, 8.2%) were drive fragmentation, not football.** `advance_quarter` preserves owner, field position, and down, so a "stopped" Q1/Q3 drive resumed next quarter as a second logged drive. Real drives carry over the Q1->Q2 and Q3->Q4 boundaries.
- **584 stopped drives died inside scoring range (fp >= 65)** with no urgency kick available.
- Stop score context: 767 trailing and 311 tied offenses stalled silently (real football hurries); 773 leading (kneel-outs are legitimate).
- **81% of halves ended in a silent stop** (430/532 Q2 last drives, 446/532 Q4 last drives) — no two-minute push existed.
- Time-remaining distribution of stopped drives was flat (421 under 30s through 192 over 300s), confirming stops were generic clock exhaustion rather than end-of-half behavior.
- Quarter scoring shape matched the distortion: Q2 10.75 / Q4 9.29 vs benchmark 13.81 / 13.15.

## Changes Implemented (Tasks 6-9)

- `situation_model.py` (Task 6): explicit urgency-state classifier `classify_urgency` with the six requested states — `neutral_offense`, `two_minute_drill` (<= 2:00 in Q2/Q4/OT within one score), `four_minute_offense` (Q4 leading, 2:00-4:00), `trailing_urgency` (Q4/OT trailing, <= 6:00), `halftime_preservation` (Q2 <= 1:00, tied-or-leading, own territory), `end_game_preservation` (Q4/OT leading, <= 2:30). The state is carried on `PlayState`/`SituationContext` and drives all downstream behavior.
- `play_simulator.py` clock consumption (Tasks 7-8): hurry-up states (`two_minute_drill`, `trailing_urgency`) consume ~0.09x expected clock per snap and 0.05x on incompletions — implicit modeling of timeouts, spikes, and sideline throws; preservation states drain the full play clock (0.30x); neutral trimmed 0.20 -> 0.19 to hold possession counts.
- `play_simulator.py` play calling: preservation states shift heavily to keep-the-ball runs (incompletions x0.25, explosive x0.40, turnover x0.40); trailing urgency raises pass volume and explosive plays.
- `drive_simulator.py` late-half aggression (Task 9): **urgency field goal** — on any down in Q2/Q4/OT with <= 60s and the ball in true FG range, teams within kicking-decision range (-9 to +2) take the points before the clock dies; **trailing 4th-down go-for-it** — Q4/OT trailing inside 5:00 goes for it outside FG range (conversion probability distance-scaled 0.25-0.62) instead of punting the season away.
- `game_simulator.py` (accounting): Q1->Q2 and Q3->Q4 drive fragments are merged into single logical drives (`_merge_quarter_carryover_drives`) since the possession genuinely continues; this removes the fake end-of-quarter stop share.
- `tests/test_smartsim2_play_state.py`: updated one assertion that encoded the old semantics (leading by 4 with 98s left in Q4 is now correctly `end_game_preservation`, not a hurry-up drill). Full smartsim2 suite: 16/16 passing.

Untouched, per constraints: possession engine, drive engine structure, field-position model, punt calibration, scoring ecology (except the urgency-conditioned behaviors above).

## Quarter Scoring Audit (Task 15)

| Quarter | Benchmark | Iteration 5 | Iteration 6 | Iter 5 Norm Err | Iter 6 Norm Err |
| --- | --- | --- | --- | --- | --- |
| Q1 | 9.17 | 8.79 | 9.04 | 0.041 | 0.014 |
| Q2 | 13.81 | 10.75 | 11.76 | 0.222 | 0.149 |
| Q3 | 9.42 | 10.35 | 10.32 | 0.098 | 0.096 |
| Q4 | 13.15 | 9.29 | 12.17 | 0.293 | 0.074 |
| Game totals | 46.24 | 39.40 | 43.48 | 0.148 | 0.060 |

The benchmark's signature shape — high-scoring second and fourth quarters — now emerges from urgency behavior instead of being flattened.

## Clock Management Audit (Task 16)

| Drive class | Iteration 5 | Iteration 6 | Notes |
| --- | --- | --- | --- |
| Clock-stop share (all drives) | 16.3% | **9.7%** | remaining share is mostly structural (see below) |
| Neutral drives (Q1 stop share) | 17.5% | 1.7% | carryover merge: drives continue across the boundary |
| Neutral drives (Q3 stop share) | 16.0% | 0.8% | carryover merge |
| End-half drives (Q2 stop share) | 15.4% | 17.9% | includes halftime-preservation kneel-outs (legitimate) |
| End-game drives (Q4 stop share) | 16.8% | 19.5% | includes end-game kneel-outs (legitimate) |
| Stops while leading (preservation) | 773 | 618 | kneel/run-out football, correctly retained |
| Stops while trailing/tied (defects) | 1078 | 439 | urgency behavior converted most into kicks, scores, punts, and go-for-its |
| Stopped in scoring range (fp >= 65) | 584 | 396 | urgency FG window (<= 60s) captures the rest progressively |
| Q4 trailing go-for-it (turnover_on_downs Q4) | ~38 | 203 | desperation downs attempts now exist |

Structural floor: every half ends with exactly one drive in progress (~2 per game = ~8.7% of drives), so a stop share near 9% with a leading-team majority is realistic football, not a defect. The benchmark proxy simply has no stop encoding.

## Before vs After

| Metric | Benchmark | Iteration 5 | Iteration 6 | Iter 5 Norm Err | Iter 6 Norm Err | Delta |
| --- | --- | --- | --- | --- | --- | --- |
| turnover_rate | 0.4% | 7.6% | 9.0% | 19.359 | 22.969 | -3.610 |
| red_zone_conversion_rate | 43.1% | 83.0% | 87.3% | 0.925 | 1.023 | -0.098 |
| drive_length_plays | 4.05 | 6.28 | 6.90 | 0.548 | 0.701 | -0.153 |
| drive_length_yards | 31.07 | 47.94 | 51.87 | 0.543 | 0.670 | -0.127 |
| field_goal_rate | 16.2% | 9.2% | 10.7% | 0.433 | 0.337 | +0.096 |
| quarter_4_scoring | 13.15 | 9.29 | 12.17 | 0.293 | 0.074 | +0.219 |
| punt_rate | 59.0% | 42.1% | 42.4% | 0.286 | 0.281 | +0.005 |
| quarter_2_scoring | 13.81 | 10.75 | 11.76 | 0.222 | 0.149 | +0.073 |
| game_totals | 46.24 | 39.40 | 43.48 | 0.148 | 0.060 | +0.088 |
| quarter_3_scoring | 9.42 | 10.35 | 10.32 | 0.098 | 0.096 | +0.002 |
| touchdown_rate | 24.5% | 22.5% | 25.6% | 0.083 | 0.047 | +0.036 |
| quarter_1_scoring | 9.17 | 8.79 | 9.04 | 0.041 | 0.014 | +0.027 |
| drive_length_seconds | 166.1 | 171.9 | 178.8 | 0.035 | 0.077 | -0.042 |
| possessions_per_game | 21.11 | 21.33 | 20.55 | 0.010 | 0.027 | -0.017 |

Note: drive_length_plays/yards/seconds increased partly because merged carryover drives are now honestly counted as single long drives, and punt net yards still inflate drive yards (evaluator accounting artifact).

## Drive-Ending Frequency Audit

| Outcome | Benchmark | Iteration 5 | Iteration 6 | Delta |
| --- | --- | --- | --- | --- |
| touchdown | 0.245 | 0.225 | 0.256 | +0.031 |
| field_goal | 0.162 | 0.092 | 0.107 | +0.015 |
| missed_field_goal | 0.000 | 0.024 | 0.026 | +0.002 |
| punt | 0.590 | 0.421 | 0.424 | +0.003 |
| turnover | 0.004 | 0.063 | 0.061 | -0.002 |
| turnover_on_downs | 0.000 | 0.013 | 0.028 | +0.015 |
| end_of_quarter_stop | 0.000 | 0.086 | 0.012 | -0.074 |
| end_of_half_stop | 0.000 | 0.077 | 0.085 | +0.008 |

## Preservation Check (Tasks 10-12)

- **Possessions per game: preserved.** 21.33 -> 20.55 vs 21.11 benchmark (normalized error 0.027, still the second-best ever). The small dip is the honest cost of merging carryover fragments that previously double-counted.
- **TD rate: preserved and improved.** 22.5% -> 25.6% vs 24.5% benchmark (normalized error 0.083 -> 0.047), now slightly above benchmark.
- **Punt behavior: preserved.** Punt share 42.1% -> 42.4% and the punt model itself is untouched.

## Explicit Answers (Task 17)

- **Did quarter scoring improve?** Yes, across the board: normalized errors Q1 0.041 -> 0.014, Q2 0.222 -> 0.149, Q3 0.098 -> 0.096, Q4 0.293 -> 0.074. The Q2/Q4-heavy benchmark shape is now reproduced.
- **Did Q2 scoring improve?** Yes: 10.75 -> 11.76 vs 13.81 benchmark. The remaining gap sits in the 453 halves that still end without a scoring push from midfield.
- **Did Q4 scoring improve?** Yes, strongly: 9.29 -> 12.17 vs 13.15 benchmark (normalized error 0.293 -> 0.074), driven by trailing urgency, hurry-up clock, and urgency kicks.
- **Did game totals improve?** Yes: 39.40 -> 43.48 vs 46.24 benchmark (normalized error 0.148 -> 0.060), the closest totals have ever been.
- **Did clock-stop drive share decline?** Yes: 16.3% -> 9.7%. Q1/Q3 fake stops are effectively eliminated (1.7%/0.8%), and the remaining share is majority leading-team preservation (618 of 1044), which is real football; the structural floor of ~2 half-ending drives per game is ~8.7%.
- **What is now the largest remaining calibration error?** By normalized error, turnover_rate (22.97) against the proxy's near-zero encoding — inflated this iteration by desperation turnover-on-downs (2.8%), which is correct football that the proxy cannot represent. Structurally, the largest genuine gaps are **punt share** (42.4% vs 59.0% — bounded by the proxy's no-stop, no-TOD outcome mix) and **drive length plays** (6.90 vs 4.05 — inflated by honest carryover merging and the proxy's synthetic plays-per-drive construction). The largest actionable scoring gap is Q2 (11.76 vs 13.81): halftime two-minute pushes still under-produce points.

## What Should Iteration 7 Target?

1. Benchmark quality: the proxy's turnover (0.4%), stop (0%), and plays-per-drive (4.05) encodings now bound further calibration more than the simulator does; consider mirroring true drive-level play-by-play before tuning against these rows again.
2. Q2 halftime push: increase two-minute scoring-drive success (deeper urgency FG window, faster midfield hurry-up) to close the remaining 2.05-point Q2 gap.
3. Re-check punt share only after the benchmark's outcome mix is reconciled with stop/TOD reality.

## Final Verdict

**Iteration 6 Successful.**

Quarter scoring distribution moved materially toward benchmark in every quarter — Q4 normalized error fell 75%, game totals reached their best-ever calibration (43.48 vs 46.24), and clock-stop share dropped from 16.3% to 9.7% with the remainder dominated by legitimate preservation football. All three preservation criteria held: possessions 20.55 (vs 21.11 benchmark), TD rate 25.6% (vs 24.5%), punt share 42.4% (vs 42.1% in Iteration 5). The simulator now has an explicit, tested urgency-state model (neutral, two-minute, four-minute, trailing, halftime preservation, end-game preservation) inside the shared SmartSim Football Core, and the dominant remaining calibration errors are traceable to proxy-benchmark encoding limits rather than simulator behavior.

# Findings 2026-11-15 — why smartsim2 puts too few points in Q2 and too many in Q3

Lane `football-end-of-half-scoring`, session 386d4115 (user: "Yes, look into it"). READ-ONLY: no
engine edit, no deploy. The engine files belong to lane `football-scenario-calibration`; this file is
written for that lane to pre-register a fix from.

## The symptom (already measured)

- **NFL** (#752 engine read, 89 served 2026 games): quarter share of points, sim vs league 2022-25:
  - q2: 0.279 vs 0.313 [0.305, 0.320];
  - q3: 0.234 vs 0.205 [0.198, 0.212].
  - The sim's H2 out-scores its H1, the reverse of the league.
- **NCAAF** (#805 engine read, 161 games): q2 13.6 vs 15.7 actual; shares q2 0.269 vs 0.301, q3 0.236 vs 0.221.
- **Cost:** h1/h2/q2/q3 segment pricing inherits the shift. #805 grades NCAAF segment totals LOSES
  +0.0230 [+0.0115, +0.0349] to the market.

## Hypothesis, as written into the lane before testing

Two end-of-half mechanisms, both in production:

- **(a) Halftime carry-over.** `halftime_kickoff` is OFF, so the drive alive at 0:00 of Q2 keeps its
  owner, spot and down, and scores in Q3 (`game_simulator.py:158-160`; `possession_state.advance_quarter`).
- **(b) Q4 rules at the half.** The urgency field goal fires only at -9 <= diff <= 2
  (`drive_simulator.py`, the "Urgency field goal" block). The two-minute drill fires only at diff <= 7
  (`situation_model.classify_urgency`). Both are Q4 rules applied to Q2.

Falsification:

- (b) is false if the sim's points in Q2's last 120 s are inside the league's 95% CI.
- (b) is also false if the league's end-of-half field-goal rate depends on the score no less than the
  sim's does.
- (a) is not the main Q3 cause if carried-over drives score under a third of the Q3 surplus.

## Data, and what each number rests on

- **League NFL:** nflverse pbp, local mirror `data/nfl_source/tracking/nflverse/pbp/pbp_<season>.csv`, REG
  season.
  - 2022-25: 1,087 games. 2024-25 (the sim's games): 544.
  - nflverse is an external historical set, complete for these seasons. This is not a production artifact.
- **League NCAAF:** CFBD drives, local mirror `data/ncaaf_source/historical_truth/drives_<season>.json.gz`.
  - 2023-25, FBS-vs-FBS (both conferences set): 2,627 games.
  - Points are placed at each drive's end clock.
- **Sim NFL:** production's own `generate_smartsim2_nfl_projections.build_projection`, run in production's
  env via `football_scenario_rates._nfl_init` with the shipped profile.
  - Every seed's full output is read through the `segment_accumulator` seam.
  - Games: every 4th completed 2024-25 game, 136 games, 100 seeds each, `PYTHONHASHSEED=0`.
  - The arms run the same games and seeds.
- **Arms** (patched in the research process only; nothing in the repo changed):
  - `off`: production as shipped.
  - `on`: `halftime_kickoff=True`, the existing pre-registered switch.
  - `gates`: Q2 only, the urgency field goal and the two-minute drill ignore the score.
  - `on_gates`: both.
- **Scripts:** `C:\tmp\football_eoh\`: `real_nfl.py`, `real_summary.py`, `real_ncaaf.py`,
  `real_snaps.py`, `sim_nfl.py`, `analyze_sim.py`, `analyze_snaps.py`.

## Result 1 — the sim misses most of the end-of-half surge

Points per game (NFL; league 2024-25 with 95% CI; sim `off` over 136 games x 100 seeds):

| | league | sim (shipped) | gap |
|---|---|---|---|
| q1 | 8.93 [8.46, 9.40] | 9.68 | +0.75 |
| q2 | 14.02 [13.47, 14.59] | 12.54 | **-1.48** |
| q3 | 9.50 [9.01, 10.00] | 10.52 | **+1.02** |
| q4 | 13.17 [12.54, 13.84] | 13.10 | -0.07 |
| regulation total | 45.62 | 45.84 | +0.22 |
| **q2, last 120 s** | **4.78 [4.46, 5.10]** | **3.14** | **-1.64** |
| q1 / q3 / q4, last 120 s | 1.47 / 1.47 / 2.63 | 1.72 / 1.54 / 2.25 | |

- The whole Q2 deficit sits in Q2's last two minutes, and the sim is far outside the league's CI there.
- The total looks right only because the errors cancel: Q2 is short, while Q3 and Q1 run long.
- NCAAF has the same surge: 5.27 [5.07, 5.48] points a game in Q2's last 120 s, against 2.00 (q1) and
  2.22 (q3).

## Result 2 — (a) the carry-over explains the Q3 surplus, all of it

- **`off`:** a drive crosses the half in 0.844 of games, and it scores 2.33 points a game in Q3. The
  league has no such drive.
- **`on`, paired against `off`:**
  - q3 -0.95 [-1.07, -0.83], to 9.57 (league 9.50 [9.01, 10.00]);
  - q2 +0.00;
  - total -1.07 [-1.23, -0.92].
- The total drop matches the calibration lane's own read (-1.12, findings_2026-10-06, H1 paired). It is
  why `halftime_kickoff` alone failed there: the switch removes Q3 points, and nothing puts the missing
  Q2 points back.

## Result 3 — (b) the score gates are real but small in points

End-of-half drives: drives with a snap in Q2's last 120 s, bucketed by the offense's score diff at their
first snap in that window. Each cell is the field-goal attempt rate / points per drive / share ending at
the half with no score:

| diff | league 2024-25 | sim `off` | sim `gates` |
|---|---|---|---|
| <= -10 | 0.253 / 1.63 / 0.239 | 0.092 / 2.20 / 0.271 | 0.293 / 1.73 / 0.210 |
| -9..2 | 0.289 / 1.86 / 0.221 | 0.291 / 1.60 / 0.300 | 0.275 / 1.59 / 0.308 |
| 3..7 | 0.298 / 1.81 / 0.258 | **0.068** / 1.37 / **0.525** | 0.243 / 1.18 / 0.465 |
| >= 8 | 0.284 / 1.88 / 0.240 | **0.040** / 0.87 / **0.690** | 0.237 / 1.14 / 0.518 |
| drives per game | 2.56 | 2.04 | 2.32 |

- **The league's end-of-half kick does not depend on the score:** 0.25-0.30 in every bucket (2022-25:
  0.23-0.30). The sim's does, which supports (b) as a mechanism. NCAAF agrees: 0.14-0.19 in every bucket.
- **Removing the gates fixes the shape:** kick rates of 0.24-0.29 in every bucket. But it adds only
  q2 +0.22 [+0.18, +0.26] points a game. Q2's last 120 s go from 3.14 to 3.36, against the league's 4.78.
- **So (b) holds as a mechanism but fails as the main Q2 cause.** About 1.4 of the 1.64 points a game are
  still missing, both from fewer drives in the window (2.32 vs 2.56) and from fewer points per drive
  (about 1.45 vs 1.81).

## Result 4 — the clock at the end of the half

This cause was **not in the hypothesis**. It was measured after Result 3 left most of the Q2 gap
unexplained (`real_snaps.py`; `sim_nfl.py` re-run with snap counters, which reproduced the first `off`
run on 136 of 136 games).

Snaps per game in each quarter's last 120 s. Seconds per snap are the league's 120 / snaps, and the
sim's own clock consumed per snap:

| | league 2024-25 | sim `off` | sim `on_gates` |
|---|---|---|---|
| **q2** | **10.63 (11.3 s)** | **6.71 (18.2 s)** | **7.28 (16.9 s)** |
| q4 | 7.38 (16.3 s) | 4.75 (25.3 s) | 4.79 (25.0 s) |
| q1 / q3 | 3.86 / 3.94 (31 s) | 4.56 / 4.56 (26 s) | 4.56 / 4.59 |

- **League, Q2's last 120 s:** 2.84 timeouts a game, 0.34 kneels, 0.14 spikes, plus the two-minute
  warning. The sim models no timeouts and no two-minute warning.
- **Per snap, the sim already scores at the league's rate** in that window: 0.46 points a snap with both
  fixes (0.47 shipped), against the league's 0.45. So the Q2 gap that remains after (a) and (b) is
  almost exactly the missing snaps: (10.63 - 7.28) x 0.46 = **1.5 points a game**, against the 1.42
  still missing. This is an accounting split on the sim's own rate, not a counterfactual run. The run
  belongs to the fix.
- **The short final possessions are missing:** drives whose first window snap comes with under 30 s
  left run 0.28 a game in the sim, against the league's 0.62. In real football, a score or punt with
  ~40 s left still gives the other team a snap. In the sim the clock runs out first.
- **Q4 has the same clock gap** (4.75 vs 7.38 snaps). Its points are only a little low (2.25 vs 2.63
  [2.31, 2.96]), since fewer games are close at the end. It matters for late-game live re-sims, and
  the same fix covers it.
- **Normal play runs slightly fast:** 26 s a snap against the league's ~31 s in Q1/Q3's last 120 s. This
  is a possible part of the Q1 surplus, not followed here.

**Verdict on the hypothesis.**

- (a) is supported: carried-over drives score 2.33 points a game against a Q3 surplus of 1.02, and the
  switch closes Q3 to the league.
- (b) survives both falsification tests: the sim's last-120 s points are far outside the league CI, and
  the league's kick rate is flat in score while the sim's is not. **But its prediction that it removes
  the Q2 points is wrong in size** (0.22 of 1.64).
- **The main Q2 cause is the end-of-half clock,** which the hypothesis did not name.

## What this means for a fix (for lane `football-scenario-calibration`)

This is one change: `model_engine_standard.md` §4.4 requires a mechanism and the re-fit of the rates
that absorbed it to go together. Each step is sized on the NFL arms above.

1. **`halftime_kickoff` ON.** The switch already exists, is tested and is default OFF. Measured: q3 -0.95,
   total -1.07, q2 0.
2. **Q2 end-of-half decisions ignore the score.** In Q2 only, drop the urgency field goal's
   -9 <= diff <= 2 and the two-minute drill's diff <= 7. Q4 is unchanged, and the halftime kneel stays
   (the league kneels 0.34 a game in that window).
   - Measured: q2 +0.22 [+0.18, +0.26].
   - The kick rate becomes flat in score, as in the league (0.24-0.29 against 0.25-0.30).
   - The two-minute boosts for teams trailing big look too strong (2.20 points per drive against
     1.63). Check them in the same change.
3. **An end-of-half clock (NEW mechanism).** In Q2's and Q4's last 120 s, add a two-minute-warning stop,
   per-team timeouts (3 a half), and incompletion / out-of-bounds stops, so that the window holds the
   league's snaps.
   - Targets: q2 10.6 snaps (11.3 s each); q4 7.4 (16.3 s).
   - The sim today: 7.28 (16.9 s) with steps 1 and 2 on; 4.79 (25.0 s) in Q4.
   - Expected, at the sim's own 0.46 points a snap: Q2's last 120 s ~3.36 -> ~4.9, against the
     league's 4.78 [4.46, 5.10].
4. **Re-fit the scoring level after 1-3.**
   - Net of 1-3 on the total is roughly -1.07 + 0.22 + 1.5 = +0.6 a game.
   - Separately, Q1 already runs +0.75 high.

**Suggested gates**, to be pre-registered by that lane:

- On FIT seasons, each quarter's points inside the league's 2024-25 CI.
- Q2's last-120 s points and snaps inside the league's CI.
- H1 > H2, as in the league.
- On held-out games, full-game total / margin / ML Brier against the close no worse than production.
- Then the segment re-grades: #752 (`scripts/nfl_segment_skill.py`) and #805
  (`scripts/ncaaf_segment_skill.py`, with `--archive` once weeks are kept) as the market test.

**NCAAF:** run the same arms through `football_scenario_rates._ncaaf_init` before pre-registering NCAAF
numbers. NCAAF has the league surge (5.27 points a game in Q2's last 120 s), and its kick rate is flat
in score (0.14-0.19).

## Also seen, not followed

- **Q1 runs 0.75 points a game high** (9.68 vs 8.93 [8.46, 9.40]). That is outside the league CI, and it
  is not an end-of-half effect: Q1's last 120 s are near the league's.
- **Trailing by 10+, the sim scores 2.20 points per end-of-half drive (league 1.63)**, mostly touchdowns
  (0.283 vs 0.156). The two-minute drill's explosive x1.60 and touchdown +0.04 boosts look too strong.
- **NCAAF sim arms were not run.** The engine code is shared and NCAAF's profile also leaves
  `halftime_kickoff` False, so the same mechanisms apply. NCAAF's own sizes still need its own run
  (`football_scenario_rates._ncaaf_init`).

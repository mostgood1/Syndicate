# FINDINGS — WNBA SmartSim per-minute rates shrunk toward the player's own rate (fix #3)

**Lane** `wnba-sim-rate-shrink`, session `39b666bb`. **Date** 2026-10-03. **No deploy; flag default OFF.**
Fit ON TOP of fix #2 (availability rule on): both the training (May–July, 3,185 player-games) and test (Aug–Sep 2,041;
playoffs 165) re-runs are availability-on, 500 sims, fleet code `9a7f0d2f` + the lanes' hooks — evidence about the CODE.

## 0. Headline

1. **With minutes corrected, the sim's per-minute rate carries only a little signal beyond the player's own rate:**
   fitted weight on the sim's departure **pts 0.15, reb 0.15, ast 0.10, threes 0.35** (all interior to 0–1.2).
   Without the availability fix the same fit put **0.0** on points/rebounds/assists — the sim's departures were
   minutes error, not rate information.
2. **Held out, the prop mean now ties or beats the player's own season average** for the first time in this series:
   points −0.037 [−0.098, +0.026] (tie), **rebounds −0.038 [−0.068, −0.006]**, **RA −0.057 [−0.100, −0.011]**, PRA
   −0.105 [−0.211, +0.003], assists −0.016 [−0.032, +0.001]. **Threes is the exception: +0.018 [+0.008, +0.028]**.
3. **Book-line Brier improves on every market** vs the availability-only ladders, every CI < 0 (points −0.019,
   rebounds −0.026, PRA −0.029, threes −0.007). Gap to the book narrows to: rebounds 0.250 vs 0.245, assists 0.256 vs
   0.248, points 0.262 vs 0.249.

## 1. The stack so far (Aug–Sep held out, points)

| stage | points mean bias | points MAE | vs own avg (dMAE) | book-line Brier (book 0.249) |
|---|---|---|---|---|
| today's engine | −1.48 | 4.65 | +0.31 worse | 0.302 |
| + availability (fix #2) | −0.07 | 4.35 | +0.20 worse | 0.280 |
| + rate shrink (fix #3) | — | **4.11** | **−0.04 (tie)** | **0.262** |

(Rows from three runs on the same games; the first two are unpaired harness scores, the step from 2 to 3 is paired.)

## 2. Held-out table (fit `scripts/fit_wnba_sim_rate_shrink.py`)

| market | n | MAE shrunk / sim / own avg | d vs sim [CI] | d vs own avg [CI] | Brier shrunk / book | d Brier vs availability-only [CI] |
|---|---|---|---|---|---|---|
| points | 2,041 | 4.114 / 4.350 / 4.151 | −0.236 [−0.302, −0.171] | −0.037 [−0.098, +0.026] | 0.2616 / 0.2489 | −0.0187 [−0.0265, −0.0110] |
| rebounds | 2,041 | 1.702 / 1.800 / 1.740 | −0.098 | **−0.038 [−0.068, −0.006]** | 0.2503 / 0.2447 | −0.0263 |
| assists | 2,041 | 1.191 / 1.276 / 1.207 | −0.085 | −0.016 [−0.032, +0.001] | 0.2557 / 0.2478 | −0.0241 |
| threes | 2,041 | 0.780 / 0.835 / 0.762 | −0.055 | +0.018 [+0.008, +0.028] | 0.2489 / 0.2431 | −0.0071 [−0.0117, −0.0025] |
| PRA | 2,041 | 5.455 / 5.694 / 5.560 | −0.240 | −0.105 [−0.211, +0.003] | 0.2696 / 0.2492 | −0.0288 |
| PR | 2,041 | 5.004 / 5.276 / 5.073 | −0.272 | −0.069 [−0.160, +0.021] | 0.2658 / 0.2498 | −0.0276 |
| PA | 2,041 | 4.562 / 4.778 / 4.631 | −0.217 | −0.069 [−0.146, +0.008] | 0.2635 / 0.2495 | −0.0232 |
| RA | 2,041 | 2.307 / 2.389 / 2.364 | −0.082 | **−0.057 [−0.100, −0.011]** | 0.2584 / 0.2493 | −0.0170 |

Playoffs (165 rows): same direction on every mean vs the sim (points −0.225 [−0.372, −0.071]); vs own average and vs
the book the CIs are wide and straddle 0.

## 3. The change

- NEW `syndicate/features/shared/wnba_sim_rate_shrink.py`: per player with ≥3 prior games and sim minutes, sets
  `<stat>_mean = min_mean × (own_rate + w × (sim_rate − own_rate))`, moves `pra_mean` by the sum, SHIFTS every ladder
  (pts/reb/ast/threes/PRA/PR/PA/RA) by its components' summed delta with the vendor builder; width unchanged; stamps
  `rate_shrink` per row. Own rate from `boxscores_history.csv`, games strictly before the slate. Weights from
  `wnba_sim_rate_shrink.json`. Missing/broken inputs → untouched with a named reason. WNBA only; OFF unless
  `SYNDICATE_WNBA_SIM_RATE_SHRINK` is set.
- ONE call in the vendor-call wrapper of `basketball_props_smart_sim.py`, before fix #1's widening.
- **Reachability through the real engine** (one-date re-run 2026-07-20, availability + rate shrink on):
  `SIM_RATE_SHRINK applied players=19/20` per game; **316 of 316** stamped player-stat means equal an independent
  re-derivation from the box history (max abs error 1.8e-05). Tests: `tests/test_wnba_sim_rate_shrink.py` (9), plus
  77 related tests.

## 4. NOT done, needs a user decision

The stack is fixes #2 + #3 together (fix #3 was fit on availability-on runs; shipping it without #2 is untested).
Enabling = `SYNDICATE_WNBA_SIM_AVAILABILITY=1` + `SYNDICATE_WNBA_SIM_RATE_SHRINK=1` on the WNBA props worker(s), the
weights file on the fleet disk (`wnba_source/data/processed/wnba_sim_rate_shrink.json`; under the engine standard §3 it
needs an allowlist line in `artifact_publisher.py`, claimed by lane `nhl-live-resim` → cross-lane approval), fleet ff.
Then fix #1's widths must be re-fit on fix #2+#3 ladders.

## 5. What is left

Props are still behind the book at its own line on every market (points 0.262 vs 0.249). The mean now matches the
player's own average, so the remaining gap is mostly information the book has and the model does not (game-day
injuries/minutes news), plus width (fix #1, to re-fit). Threes is the one market where the shrink leaves the mean
slightly worse than the own average; its weight (0.35) keeps too much of the sim's threes rate.

## Addendum 2026-10-04 — ladder-shift rounding fixed (user: "fix the rate shrink rounding")

**Defect.** The engine and this lane's fit script both shifted integer ladders by v' = round_half_up(v + delta). That is
a **no-op for any |delta| < 0.5**, so most threes and assists deltas never reached the ladder the board reads; the
means moved but the probabilities did not. Found while building `wnba_sim_minutes_redistribution` (a −0.3 threes shift
left the ladder byte-identical).

**Fix.** `shift_values` in `wnba_sim_rate_shrink.py`: every draw moves by floor(delta), then round(n·frac(delta)) draws,
evenly spaced through the value-sorted order, get +1. The mean moves by exactly delta (floored at 0), the width stays
within ±1, and it is deterministic. The fit script now scores with the same function, so the evaluation is what the
engine publishes. Weights are unchanged (fitted on mean MAE, which this does not touch). Tests: a discriminating
sub-half-unit case that the old rule fails, plus mean/width/determinism over six deltas.

**Re-measured** (same availability-on archive, same rows, Aug–Sep regular season held out, n 2,041 per market).
Ladder Brier old → new: assists **0.2557 → 0.2516** (−0.0041), threes 0.2489 → 0.2474 (−0.0014), PR −0.0011,
points −0.0006, PA −0.0005, RA −0.0004, rebounds +0.0003, PRA +0.0001. These are point differences on identical rows;
no CI is computed for the difference itself. Brier vs the unshrunk sim is still better on every market, with every
CI below zero. Playoff threes: +0.0020 [0.0, +0.0049] (worse than no shrink) → −0.0008 [−0.0175, +0.0145].

**Not explained by this:** threes' failing MEAN condition (MAE vs own average +0.018 [+0.008, +0.028]) is unchanged —
it is a property of the mean, which the rounding never touched. (`findings_2026-10-04_wnba_minutes_redistribution.md`
§6 suggested otherwise; corrected there.)

Fix #3 stays HELD, flag OFF.

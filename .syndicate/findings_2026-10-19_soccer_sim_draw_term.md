# Soccer: a gap-tied draw term fit on the SERVED SIM's own 1X2 (lane `soccer-team-strength` stage 4) — 2026-10-19

Lane `soccer-team-strength`, session e44b3e73. The user decided at 2026-10-19 ~21:0xZ: "ship the correction, ship
the rating changes, drop a2". This file covers the draw correction (b) only.

## Why a refit, and not the stage-3 parameters

Stage 3's draw term (b) was fit on the research Poisson link (`findings_2026-10-19_soccer_favourite_gain.md`).
There, δ0 ≈ +0.16 and δ1 ≈ −0.36..−0.41 per unit of rating gap, so draws are inflated near level and
deflated in mismatches. **The served sim does not have that Poisson's draw shape.** A descriptive read (no fit) of
its 2025-26 output (`C:/tmp/soccer-lpb/h2h_armA_<league>.jsonl`, the production arm, market anchor OFF, 2,724
matches in 9 leagues), in terciles of `x = |log(home_mean/away_mean)|`:

| x tercile | sim draw | close draw | actual draw |
|---|---|---|---|
| 0.00-0.24 | 0.271 | 0.278 | 0.259 |
| 0.24-0.54 | 0.254 | 0.262 | 0.270 |
| 0.54-1.92 | **0.197** | 0.217 | **0.220** |

The sim already UNDER-predicts draws in mismatches, so the stage-3 parameters would push it the wrong way. The
user chose to refit the same form on the sim's own output (option "Refit on the sim").

## 1. PRE-REGISTRATION (committed BEFORE any fit)

Only the descriptive table above has been computed.

- **Data:** every row of `h2h_armA_<league>.jsonl` for the 9 leagues (epl, la_liga, bundesliga, serie_a,
  ligue_1, eredivisie, primeira_liga, belgian_pro_league, championship; `h2h_armA_goals.jsonl` is a duplicate
  pool and is excluded). Fields: `model_home/draw/away` (the served sim's 1X2, 300 simulations), `model_home_mean`
  / `model_away_mean`, `actual`, `close_home/draw/away` (de-vigged close; rows without a close are scored
  against outcomes but left out of the close comparisons).
- **Form:** `p'_D ∝ p_D·exp(δ0 + δ1·x)`, `p'_H ∝ p_H`, `p'_A ∝ p_A`, renormalised, with
  `x = |log(model_home_mean/model_away_mean)|`. That is the sim's own goal-mean ratio, which is available at
  serving time with no rating join. Model probabilities are floored at 1e-4 and renormalised before the map, so a
  0/300 draw cannot produce log(0).
- **Fit:** δ0, δ1 by 1X2 multinomial log loss against outcomes (stage 3's `fit_post("draw", ...)`).
- **Primary hold-out (chronological):** fit on matches dated before 2026-01-01 and score matches on or after it.
  Δ = LL(corrected) − LL(sim), paired over held-out matches, 95% CI from 2,000 bootstrap resamples over matches
  (seed 699).
  - **SUPPORTED** if the CI lies entirely below 0;
  - **NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0;
  - **FALSIFIED** if the point estimate is ≥ 0.
- **Secondary (no verdict):** leave-one-league-out (fit on 8, score the 9th, pooled); the δ0-only
  decomposition; Brier; KL to the close; draw calibration by x tercile; top-decile favourites (by close and by
  the sim's own probability).
- **Ship rule:** ship ONLY if the primary verdict is SUPPORTED. The shipped parameters are then refit on ALL
  2025-26 rows. Otherwise nothing ships for draws, and the lane says so.

## What this does NOT establish

- Whether the term still fits after the rating change ships with it. The new ratings widen the sim's 1X2 slightly
  (stage 1: sd 0.323 → 0.327), but the draw shape is a property of the sim's score mechanics. Re-measure after
  the change is live.
- More than one season: 2025-26 is the only season of served-sim output on disk.

## 2. Results

## 3. Deviations

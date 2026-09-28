# Per-market `k` does NOT justify itself, and the residual failures are not a `k` problem

`[measured 2026-09-28, lane layer2-triad-alignment, session 4ab694ed]`

Follows `findings_2026-09-28_nfl_spread_shrinkage_sweep.md`. The shipped
configuration (`stdev` + usage-scaled CV shrinkage at a GLOBAL k=6, plus the
re-fitted blend) passes the `#499` bar in aggregate at 0.0878 but leaves 3 of 8
markets failing individually. Per-market `k` was the obvious next lever. It was
selected on the fit seasons only and graded out of sample, and it does not pay.

## Selected on 2022-2023, graded on 2024-2025

Selection rule: minimum Brier, with the worst-powered-bucket gap breaking ties
among candidates within 0.1% relative Brier of the minimum. Selecting directly on
the bucket gap would be optimising the admission bar itself.

    market             k   Brier delta   bucket gap  (global k=6 -> per-market)
    passing_attempts   2    -0.001124     0.1619 -> 0.1463   crosses the bar
    interceptions     12    -0.001083     0.2577 -> 0.2613   worse, still fails
    passing_yards      8    -0.000149     0.1324 -> 0.1278
    rushing_yards      4    -0.000068     0.0359 -> 0.0560   WORSE
    receiving_yards    8    -0.000133     0.0740 -> 0.0756   worse
    receptions         6     0.000000     unchanged
    rushing_attempts   8    +0.000233     0.0404 -> 0.0504   WORSE
    passing_tds        3    +0.000374     0.1570 -> 0.1672   WORSE

    POOLED Brier 0.211695 -> 0.211617,  delta -0.000077

**NOT SHIPPED.** The pooled gain is **1% of what the shrinkage itself delivered**
(-0.0078), five markets improve and three get worse, and the bucket gaps move
BACKWARDS on the two best-calibrated markets (`rushing_yards`,
`rushing_attempts`). It would replace one maintained constant with eight and
require a third blend re-fit, for a gain indistinguishable from noise.

## THE RESIDUAL FAILURES SPLIT INTO TWO DIFFERENT PROBLEMS

Outcome support on the GRADED population (high-usage p70):

    market             distinct actuals   P(0)   P(<=2)
    interceptions              5          0.52    0.96
    passing_tds                6          0.18    0.77
    passing_attempts          57          0.00    0.01
    rushing_attempts          38          0.01    0.07
    receiving_yards          198          0.04    0.05

**`interceptions` and `passing_tds` are DISCRETE, with five and six distinct
outcomes.** A continuous Normal/log-normal cover probability cannot be calibrated
against a variable with that support at ANY sd -- which is exactly why per-market
`k` moved them the wrong way (0.2577 -> 0.2613, 0.1570 -> 0.1672). They are not
under-shrunk; they are being modelled with the wrong family.

**The fix for them is precedented IN THIS FILE.** `_nfl_prop_model_probability`
already special-cases `anytime_td`: "a one-sided market with no line -- the rate
itself IS the probability of scoring, no distribution needed". `interceptions`
and `passing_tds` want the same treatment in discrete form (a Poisson or
zero-inflated count), not a continuous CDF.

**`passing_attempts` is the ONE genuine `k` case:** 57 distinct outcomes, so the
continuous model is appropriate, and it fails at the global k=6 (0.1619) while
k=2 crosses the bar (0.1463) with a Brier gain (-0.001124). A single targeted
override is defensible where the full table is not -- it would need its own blend
re-fit, since the calibrator fits `w` per market.

## What this closes

`k` is done as a lever. The global k=6 is the right constant, the full per-market
table is refuted on its own out-of-sample grade, and the remaining calibration
failures are a DISTRIBUTION FAMILY problem rather than a tuning one.

# NFL prop spread: swept out of sample. `stdev` + k=3 is a REAL but PARTIAL fix

`[measured 2026-09-28, lane layer2-triad-alignment, session 4ab694ed;
scripts/calibrate_nfl_spread_shrinkage.py]`

Follows `findings_2026-09-28_nfl_prop_model_diagnosis.md`. Fit on 2022-2023,
reported on 2024-2025, graded against real settled nflverse outcomes through the
PRODUCTION probability function (`_nfl_prop_model_probability`, including its
log-normal blend), over a ladder of half-integer lines. No lookahead.

## SELECTED on 2022-2023 — a genuine convex minimum

27,679 common rows / 140,529 scored cells.

    estimator  k=0       k=3       k=4       k=12      k=30
    pstdev     0.187627  0.185892  0.185889  0.186838  0.188565
    stdev      0.185842  0.184754  0.184829  0.186068  0.188049

**`stdev` beats `pstdev` at EVERY k**, and each arm has a real interior minimum
rather than a monotone "more shrinkage is free" slope -- the same shape `#471`
required of `ANYTIME_TD_SHRINKAGE_K` before accepting it.

**SELECTED: `estimator=stdev`, `k=3.0`.**

## HELD OUT on 2024-2025 — all three arms on the SAME 28,618 rows

    arm                          Brier      cov80
    production (pstdev, k=0)     0.192516   0.7011
    estimator only (stdev, k=0)  0.190527   0.7448
    selected   (stdev, k=3)      0.189037   0.7541

    delta vs production: -0.003479  BETTER

Decomposed: the estimator fix is worth **-0.001989** and the shrinkage a further
**-0.001490**. Roughly equal; neither is the whole story, so shipping only one
leaves half the gain.

## THE HONEST LIMIT: it is a PARTIAL fix and the distribution is STILL too narrow

80% interval coverage goes 0.7011 -> 0.7541 against a target of **0.80**. After
both fixes the realised value still falls outside the model's own 80% interval
about 25% of the time instead of 20%.

A principled term that is still missing: the predictive sd should carry the
uncertainty of the ESTIMATED MEAN as well as the player's game-to-game spread --
`sqrt(sd^2 + sd^2/n)`, which at n=3 is a further x1.155. That is not enough on
its own to close 0.754 -> 0.80, so something else is compressing it too. NOT
diagnosed here.

## A NUMBER I NEARLY REPORTED AS A WIN, AND IT IS NOT ONE

The sweep found **39,094 of 67,712 held-out rows (57.7%) that production cannot
price at all** (`raw sd == 0`, so `_nfl_prop_model_probability` returns None),
every one of which any shrinkage would rescue. That reads as an enormous coverage
gain. It is not. Measured on 2025: of 17,183 such rows, **17,087 (99.4%) are
STRUCTURAL ZEROS** -- `mean == 0`, a player who never does that stat at all
(interceptions 3,341, passing_tds 3,314, passing_yards 3,263 -- receivers and
backs, who have no passing props). Only **96 (0.6%)** are a real repeated value.
Rescuing them would price a receiver's passing-yards prop. **Reported as a count
and excluded from the Brier**, because including them would have made every
comparison composition rather than accuracy.

That exclusion was itself a correction mid-run: the first pilot showed shrinkage
"winning" by -0.0516, which was entirely the degenerate rows entering one arm and
not the other (11,038 cells vs 15,659). Pinning the population to rows every arm
can price removed the whole effect. The real effect is 15x smaller.

## What must ship WITH it, not after it

`_COVER_PROBABILITY_BLEND_WEIGHT` (`props.py:205`) is a FITTED table calibrated
by `calibrate_nfl_cover_probability_blend.py` **on top of the current too-narrow
sd**. This sweep scored through that table UNCHANGED, so `k=3` is the best
constant *given the existing blend*. Widening the sd changes what those weights
were fitted to absorb. `docs/ai_context/model_engine_standard.md`: adding a
mechanism to a calibrated engine requires RE-FITTING the rates that were
absorbing it, and two mechanisms shipped together produced a NEGATIVE interaction
in 4 of 4 markets. **The blend re-fit is part of this change, not a follow-on.**

## Not addressed

Defect B from the diagnosis -- the MEAN is often far from the line (Boston 77.0
against 35.5). Widening the distribution makes those rows less confidently wrong,
not right. `player_stats._zero_involvement_weeks`'s own docstring already records
a MEASURED mean bias of +7.7% median / +12.1% mean over 1,923 quoted week-1 rows,
with receiving_yards +18.2%. That is the next thread.

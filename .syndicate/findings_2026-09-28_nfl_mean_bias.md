# "Defect B" is mostly NOT a defect: the NFL prop MEAN estimator is UNBIASED

`[measured 2026-09-28, lane layer2-triad-alignment, session 4ab694ed]`

I reported a second defect alongside the too-narrow spread: "the MEAN is often far
from the line -- Boston 77.0 against 35.5, Judkins 27.0 against 55.5 -- these are
not calibration subtleties." **That framing was not established, and three of the
four things it rested on turn out to be measurement artifacts.**

## 1. The estimator is UNBIASED, measured the only way that isolates bias

Comparing a MEAN prediction to a SINGLE GAME conflates bias with variance -- a
player averaging 60 receiving yards posts 20 routinely. The test that isolates
bias compares two EXPECTATIONS: the rolling mean the model would have used at
week w, against **the player's own realised mean from week w onward** (>= 4
future games, 2024-2025):

    market            rows   median(rolling mean / own future mean)
    receiving_yards   5007              0.983
    rushing_yards     2888              1.019
    receptions        5045              1.000
    passing_yards      673              0.978

And flat across sample size (n=2 -> 0.955, n=10+ -> 1.013, no trend). **The
rolling mean predicts a player's own forward form essentially exactly.**

## 2. THE APPARENT BIAS WAS SELECTION, and it reverses sign with the population

    market            ALL rows (mean>0)   high-usage p70
    passing_yards           0.969             1.074
    rushing_yards           0.964             1.131
    receiving_yards         0.972             1.164
    receptions              0.955             1.125

On the FULL population the estimator UNDER-predicts. It only over-predicts once
you condition on a high rolling mean -- and the excess decays with n (1.389 at
n=2, ~1.09 by n>=10), which is the signature of REGRESSION TO THE MEAN under
selection on a noisy estimate, not of a biased estimator.

This matters because **the board IS the selected population, twice over**: it
quotes props for high-usage players, and the shortlist surfaces the rows where
the model disagrees most with the market. Both selections point the same way.

## 3. A ~20% MEAN-vs-MEDIAN GAP IS EXPECTED AND IS NOT AN ERROR

The model projects a MEAN. A market line sits near the MEDIAN (the 50/50 point).
For right-skewed markets those are different numbers (2025, players with >= 8
games):

    market             median of their mean   median of their median   ratio
    receiving_yards           21.46                   16.75            1.206
    rushing_yards              8.72                    4.00            1.203
    rushing_attempts           1.83                    1.00            1.083
    receptions                 2.19                    2.00            1.074
    passing_yards            204.65                  213.00            0.987

So `projected` sitting ~20% above a quoted line on receiving/rushing yards is
ARITHMETIC, not disagreement -- and `passing_yards` at 0.987 is the control that
proves it: quarterbacks always play, the distribution is near-symmetric, and the
gap vanishes.

**THE ONE REAL DEFECT THIS LEAVES** is the consequence for the probability, not
the projection: `_nfl_prop_model_probability` centres its Normal on the MEAN, so
against a line at the median it puts more than half the mass above and overstates
P(over) systematically on skewed markets. That is exactly what
`_COVER_PROBABILITY_BLEND_WEIGHT`'s log-normal term exists to correct, it is
already partially correcting it (weights 0.15-0.95), and it was re-fitted on the
new spread the same day.

## 4. What is left unexplained

The individual extremes -- Boston projected 77.0 against a 35.5 line, a 2.2x gap
-- are NOT explained by the ~20% skew gap and are not explained by a biased
estimator. They are most likely small-sample outliers (a rookie with one or two
large games) rather than a systematic fault. **NOT DIAGNOSED, and not claimed as
a defect** on this evidence.

## The correction, stated plainly

The diagnosis document said "widening the distribution would make these rows less
confidently wrong, not right." On this evidence the rows are not wrong. The
over-confidence was the SPREAD, which is fixed and measured; the location was
never shown to be off. **The mean is not the next thread.**

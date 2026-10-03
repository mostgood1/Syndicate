# NFL prop predictive spread — the fit "MET" its Brier target and is NOT a repair (2026-10-03)

Lane `nfl-prop-predictive-spread` (session 05b01a84). Measurement only: no production file edited, no deploy.
Script `scripts/fit_nfl_prop_predictive_spread.py`. The prediction was pre-registered in the lane block and
landed on main (`c69737cb`) BEFORE the fit ran. Outputs: `C:\tmp\nflbt\spread\fit_nfl_prop_predictive_spread.{json,md}`.

## Verdict

**The pre-registered Brier criterion was met.** Fitted on 2023-24 and scored on 2025, the chosen arm closed
72.5% (receptions) and 71.1% (receiving_yards) of the Brier gap to the de-vigged book. No market got worse.

**The pre-registered SLOPE caveat was triggered, and it governs.** The lane said: *"If the slope comes out
< 0.6, the fit is shrinking toward the base rate, not fixing the spread, and the result is NOT a repair."*
The calibration slopes of logistic(y ~ a + b·logit(p)) on 2025 are below. The chosen fits all ran to the
grid edge that flattens probabilities (shrinkage off, c = 3.0, log-normal weight 0).

| market | 2025 rows | book slope (sd of logit p) | PRODUCTION model slope (sd of logit p) | chosen arm slope | 2026 chosen slope |
|---|---|---|---|---|---|
| receptions | 14,126 | **1.09** (0.27) | **0.11** (0.95) | 0.35 | −1.00 |
| receiving_yards | 15,148 | **0.96** (0.07) | **−0.07** (0.98) | −0.15 | −1.65 |
| rushing_yards | 7,376 | 0.78 (0.09) | −0.01 (0.88) | −0.06 | 0.88 |
| rushing_attempts | 3,805 | 1.40 (0.16) | 0.08 (0.85) | 0.22 | −1.34 |
| passing_yards | 3,195 | 1.56 (0.05) | −0.06 (1.24) | −0.05 | −2.37 |
| passing_attempts | 2,739 | 0.44 (0.09) | −0.00 (1.08) | −0.16 | 2.59 |

**What it means:**
- The book is calibrated (slope ≈ 1) and barely moves off 50%.
- The model's probability at the line swings ~10x more and carries **no information about the outcome**:
  its slope is ≈ 0 in every market, sometimes negative.
- Widening the spread "closes the gap" only by flattening that noise toward 50%, i.e. toward the book.
  It makes the probability less wrong. It does not make it informative, and it cannot create an edge.
- **The drift mechanism (rate uncertainty) is NOT supported.** The best `drift` arm alone closed 49-73%
  only for receptions/receiving and 11-24% elsewhere. The joint fit then went to the flattening edge.
- Control: at production settings the arm machinery reproduced `_nfl_prop_model_probability` on every
  row (max |diff| 0.0).

## This OVERTURNS a recommendation in `findings_2026-10-02_nfl_lines_props_backtest.md` section 7

That section read the Murphy split as "the loss is RELIABILITY, not resolution, so a calibration change can
close it", and ranked "widen the predictive spread" first. **The reading was wrong.**

- At a main line the book's probability sits near 50% by construction, so the BOOK's binned resolution is
  near zero.
- The model's binned resolution was "at or above the book's" only because both were near zero, and the
  model's is noise. Comparing two near-zero resolutions discriminates nothing.
- The calibration slope does discriminate: the book ≈ 1, the model ≈ 0.

**What stands from section 7:** the market-anchored mean result (86-97% of the gap). It says the same thing
from the other side: the information is in the LINE, not in the model's mean.

## Where the fix actually is

The model's season-to-date mean disagrees with the line, and that disagreement is uninformative at the line
(slope ≈ 0). The ranked options, honestly stated:

1. **Give the mean the information the line has:** usage (snap / route / target share, carries), depth
   chart, injuries (own and teammates'), role change.
   - The anchored-mean ceiling (86-97%) bounds what that can buy, and it is the only route to a
     probability that is informative at the line.
2. **Until then, an HONEST probability is close to the de-vigged line.**
   - Shrinking toward 50% (or toward the book) improves every market's Brier (this file, 25-85% of the
     gap).
   - It does so by removing the model's opinion, so it produces ~no model edge.
   - That is a per-line display/pricing choice for the user. It is not a model repair, and it is not a
     market-level gate: every line stays shown.
3. **Do NOT deploy the fitted spread constants** (K off, c = 3, w = 0) as "the fix". They are a flattener
   with a mechanism story attached.

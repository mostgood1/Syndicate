# Totals: the outcome resolution was never wrong. The BASELINE was — and it invalidates the spreads result too.

**2026-09-08, lane `profitable-buckets`, session 3492626c.**
`scripts/bucket_realised_performance.py`.

## What "REFUSED" actually meant

The bucket harness refused totals because the market's de-vigged probability
predicted 49.0% overs while 58.9% landed — a 10pp miss, which I read as *my*
outcome resolution being wrong.

**It was not.** `total > line` is correct. The de-vig is the problem.

## The market's price is not its view

Books price totals and spreads about −110/−110, so the de-vigged price is ~0.50
**whatever the line is**. Measured here, independently:

| check | measured | expected if the price tracked the line |
|---|---|---|
| within-game slope d(P_over)/d(line) | **−0.005 / run** | about −0.12 / run |
| P(over) across ten runs of line | 0.512 → 0.453 | ~0.95 → ~0.10 |
| within-game monotone vs inverted pairs | 867 / **672** | near-zero inverted |

44% of line pairs are inverted. The field is essentially uncorrelated with the
line, which is not a defect — it is what −110/−110 pricing *means*. **The market
expresses its view as the LINE, not as a probability.**

`live_gameline_ledger` already records this, in the comment directly above the
fields involved: comparing an informative estimator to that constant "is exactly
the fake ~90% ATS result `subset_edge_scan` produced before it learned to refuse
these markets." The measured market-leg sd is h2h 0.251, spreads 0.132, totals
0.058.

## This invalidates the spreads finding for a SECOND reason

`spreads q4_late` was already withdrawn as a stale-quote artifact. It was also
measuring an informative model probability against a near-constant ~0.50 market
probability — the same mechanism that produced the fake ATS result. The stale
quotes were real and secondary; **this is the primary defect**, and it applies to
every totals and spreads number the harness produced.

h2h is unaffected: there the de-vig *is* the market's view (leg sd 0.251), which
is why h2h came back a clean null rather than a spectacular one.

## The fix: score point forecasts against the line

    h2h              de-vig IS the view      -> compare probabilities (unchanged)
    totals, spreads  the LINE is the view    -> compare POINT FORECASTS

`model_total_mean` against the line on the actual total; `model_margin_mean`
against the line on the actual margin. The 0.50 directional baseline is
legitimate here **because** the book prices it as a coin flip at that line.
A row without the mean is UNMEASURED, never folded in with a probability
comparison as a substitute.

## And an error of mine worth recording

I first reported `total_mean` and `home_margin` as **0.0% populated on all 9,226
rows** and was about to chase an unfed-field defect through four pipeline hops.
The ledger columns are named **`model_total_mean`** and **`model_margin_mean`**.
Reading `total_mean` returns None on every row and looks *identical* to a field
nothing feeds — the exact failure mode the file's own v4 comment warns about,
arrived at from the opposite direction. Under the right names the fill is **62%**.

## Status: measurable, not yet measured

`model_total_mean` only began appearing on **2026-09-06/07** — 1,802 rows but
just **12 games**. So:

- **The formulation is fixed and in the harness.**
- **Totals and spreads are UNMEASURED today at n=12**, and will become
  measurable as v5 records accumulate — roughly a week for ~100 games.
- Nothing about totals or spreads profitability should be quoted from the
  earlier runs. Those numbers measured the artifact.

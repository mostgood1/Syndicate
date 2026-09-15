# MLB bucket re-run with totals/spreads: 74 games are measurable now, and NO bucket survives in any market.

**2026-09-15, lane `profitable-buckets`, scheduled task `mlb-bucket-rerun-with-totals`.**
Re-run deferred from 2026-09-08. Production ledger via `/api/ops/artifacts/export`,
finals from statsapi.

## Population

- `bucket_realised_performance.py --sport mlb --days 14`: 82,560 rows over 12
  dates, 166 finals. **2026-09-10 returned HTTPError** in that run.
- Scratch re-pull of the same window (used for everything below): **86,965 rows,
  13 dates (09-02..09-14, 09-10 included), 171 finals.** Every row is
  `game_state = live`. Versions: v4 17,278 / v5 69,687.

## Step 1: precondition, counted in GAMES

| field | games carrying it | with final | `segment=full` with final |
|---|---|---|---|
| `model_total_mean` (totals rows) | **74** | 74 | 74 |
| `model_margin_mean` (spreads rows) | **74** | 74 | 74 |

Per date: 09-06 1, 09-07 11, 09-08 14, **09-09 0**, 09-10 4, 09-11 14, 09-12 5,
09-13 15, 09-14 10. Fill rate on v5 totals/full rows is **100% on every date**,
so this is not an unfed field. It is a small number of v5 totals/full rows: 3,311
rows in total, and none on 09-09 despite 12,967 ledger rows that day (cause not
investigated). Wrong-name control: `total_mean` and `home_margin` are non-null on
**0** rows, as expected.

74 clears the ~60 floor, but only just: one bet per game gives se ≈ 5.7pp, so a
real 1-3pp edge **cannot be detected at this n**. Everything below is "not
demonstrated", never "absent".

## A defect found before any number: the harness never scores point forecasts

`scripts/bucket_realised_performance.py` defines `point_forecast_side()`, and its
docstring says totals and spreads are scored as point forecasts against the line.
**`main()` never calls it.** Totals and spreads still go through the
`market_fair_prob` calibration gate and are REFUSED, exactly as before:

    spreads  mean_pred 0.500 vs actual 0.432  -> REFUSED
    totals   mean_pred 0.493 vs actual 0.551  -> REFUSED

So the 09-08 statement "the formulation is fixed and in the harness" describes
code that exists but is not reachable. The harness produced **no** totals or
spreads numbers today. The numbers below come from a scratch script that calls
`point_forecast_side()` and `band_for()` from the harness directly, over the same
rows, with one bet per game per band (earliest row) and `segment=full` only,
because the final score cannot resolve a first-5 line.

## Totals: +12pp, and all of it is "bet the over"

Pooled figure, first row per game: **74 games, won 62.16%, +12.16pp vs 50,
+2.16σ**. Leave-one-date-out stays between +11.0 and +15.0. It looks robust, and
it is not a model signal:

| band | games | model backs over | model won | **always-over won** |
|---|---|---|---|---|
| all (first row) | 73 | **69/73** | 61.6% | **61.6%** |
| q1_early | 66 | 63/66 | 62.1% | 63.6% |
| q2_midearly | 57 | 51/57 | 56.1% | 59.6% |
| q3_midlate | 59 | 48/59 | 54.2% | 59.3% |
| q4_late | 52 | 33/52 | 53.8% | 44.2% (se 6.9) |

The model backs the over in 69 of 73 games, and its win rate is exactly the rate
at which overs landed. It adds **nothing** beyond that. LODO is stable only
because the over rate is stable. The 0.50 baseline is not the right null when the
forecaster almost always picks one side: the null is "always pick that side".

Why it always says over: the model runs high.

- First row per game: model mean **10.85**, line **8.31**, actual **9.43**.
  mean(model − line) **+2.57** vs mean(actual − line) **+1.14**, so the model is
  **~1.4 runs high** early in the game (1.12 runs already scored at record time).
- Accuracy against the actual total: **MAE model 3.46 vs line 3.05**, and
  **corr(model, actual) 0.295 vs corr(line, actual) 0.518**. The live line is the
  better forecast.
- The bias closes late: in q4_late, mean(model − line) is +0.08 vs actual +0.20.
- For context, not a claim: the over landed in **57.4% of all 141 games** with a
  totals row, at the first line (se 4.2). That is the sample's over rate, and it
  is what the model's "edge" rides on.

Quote age on totals rows: p10 45s, **p50 109s**, p90 438s, 57.3% ≤120s. The
fresh-only cut gives the **same 62.16% on the same 74 games**. That is expected
when the side barely varies: the outcome is per game, not per quote.

**Verdict: totals NULL.** The +12pp is the sample's over rate, not a model
signal, and the model's point forecast is worse than the line.

## Spreads: q4_late +18.5pp is the scoreboard against a price that is not a coin flip

Pooled first row per game: 74 games, 54.05%, **+4.05pp, +0.70σ**. By band vs 0.50:

| band | games | won | edge vs 50 | σ | fresh ≤120s |
|---|---|---|---|---|---|
| q1_early | 66 | 56.1% | +6.1 | +0.99 | +6.1 (66) |
| q2_midearly | 57 | 61.4% | +11.4 | +1.77 | +7.1 (56) |
| q3_midlate | 60 | 56.7% | +6.7 | +1.04 | +6.7 (60) |
| **q4_late** | 54 | 68.5% | **+18.5** | **+2.93** | +18.0, +2.73σ (50) |

q4_late disagreement terciles are +5.6 / +16.7 / **+33.3**. Under this task's own
rules that is too good (>5pp, top tercile +33). So I checked what produced it:

1. **The model is reading the scoreboard.** In 50 of 54 games it backs the side
   the *current* score already covers. The dumb rule "back whichever side
   currently covers the line" wins **72.2%** (n=54), **more than the model's
   68.5%**. On the fresh cut the rule wins 74.0% against the model's 68.0%.
2. **Late spread prices are not ~0.50, so the 0.50 null is wrong here.** The
   ~−110/−110 premise holds early and breaks late. The run line stays at ±1.5
   (|line| = 1.5 in 40 of 54 games; corr(line, current margin) +0.909), and the
   book moves the PRICE. De-vigged sd by band: **0.086 → 0.118 → 0.152 → 0.208**.
   The market's own probability for the side the model backed averaged **0.669**
   in q4_late.
3. **Against that market probability, nothing is left:** q1 56.1 vs 51.9,
   q2 61.4 vs 54.6, q3 56.7 vs 61.6, **q4 68.5 vs 66.9 (+1.6pp, se 6.3)**. All
   inside noise.

A caveat on (3): the spreads `market_fair_prob` is not clean either. It is null on
some rows, and in a hand check of 12 q4_late rows, 2 had the wrong direction for
the score (line −1.5 with home down 4-5 carried mp 0.40 and 0.52). 58 of 74 games
carry lines of both signs. That is consistent with the harness's spreads gate
refusing the market. So (3) is an approximate baseline, and (1) is the
load-bearing check, because it needs no price at all.

**Verdict: spreads NULL.** q4_late is the third appearance of this artifact family
(stale quotes on 09-08, the 0.50 de-vig on 09-08, and now a scoreboard-follower
against a runline priced away from 0.50).

## h2h: still a clean null, on all 13 dates

Harness formulation (probabilities; the de-vig is the view here), one bet per game
per band:

| band | pooled games | edge pp | σ | fresh ≤120s games | edge pp | σ |
|---|---|---|---|---|---|---|
| q1_early | 152 | −0.66 | −0.16 | 147 | −0.54 | −0.13 |
| q2_midearly | 140 | +6.81 | +1.61 | 132 | +7.44 | +1.71 |
| q3_midlate | 142 | +5.90 | +1.41 | 133 | +3.96 | +0.91 |
| q4_late | 135 | −1.57 | −0.37 | 120 | −3.08 | −0.68 |

Quote age on h2h rows: p50 125s, 48.2% ≤120s. The harness's own run (12 dates)
gave q2_midearly +7.06pp and a chronological holdout of **+11.79pp ±6.68
(+1.77σ, n=56)**.

q2_midearly is the best of 4 bands and clears no family-wise bar (~2.2σ for 4
looks). Its effect size is above the ~5pp plausibility line. Its disagreement
profile is **not monotone and does not replicate across cuts** (pooled −1.2 /
+2.1 / +19.1; fresh +11.6 / +1.0 / +9.8), and it was +2.83pp on 09-08. That is
noise, not a profile.

## Step 3 was not run

No bucket survived step 2, and step 3 is conditional on a survivor. Separately,
`scripts/bucket_edge_concentration.py` scores `model_home_win_prob` against
`market_fair_prob`, which is the formulation withdrawn for spreads and totals on
09-08. Running it on spreads q4_late would re-measure the artifact. Its three
checks (per-date, leave-one-date-out, disagreement terciles) were run above under
point-forecast scoring instead.

## Standing result

**NO DEMONSTRATED LIVE-GAMELINE EDGE ON MLB, in any market, at 74 games
(totals/spreads) and 120-152 games per band (h2h).** At that n a real 1-3pp edge
is below detection.

## Owed (not done in this scheduled run)

1. **Harness:** wire point-forecast scoring into `main()`, with a null that is
   *not* a constant 0.50: "always the model's majority side" for totals, and
   "back the currently covering side" plus the market price where it departs from
   0.50 for spreads. Until then the docstring overclaims, and the script cannot
   measure totals or spreads.
2. **Model-engine lead, not this lane:** live `total_mean` runs ~1.4 runs above
   finals early in the game (q1: model − line +2.55 vs actual − line +1.19) and
   is less accurate than the line (MAE 3.46 vs 3.05). It is calibrated by q4.
3. **Ledger coverage lead:** no v5 totals/full rows on 09-09 (12,967 rows that
   day), and 4-5 games on 09-10 and 09-12. That is thin v5 point-forecast
   coverage, cause unknown.

# Ranking the Suggested set: current score vs score_v2 vs fee-net EV -- 2026-10-13

Lane `layer2-score-study-suggested` (session 9e18a0e7). Hypotheses H1-H3 were committed to the lane (`a7b0d7b5`) BEFORE any
outcome was read. Read-only; substrate = the fleet (production since 09-30).

## Data

| set | what | size |
|---|---|---|
| Suggested rows | recorder (`opportunity_population`) 09-21..10-12, the Suggested rule applied to each record (opportunity lane, market EV in [+2, +5.26], two-sided fair, fee-net >= 2, one side per line per day), graded on the FIRST QUALIFYING sighting with the production grader; NCAAF registry from the primary checkout (`SYNDICATE_NCAAF_SOURCE_ROOT`) | 559,211 records -> 2,288 suggested -> **2,030 graded, 282 games** |
| CLV | `/api/ops/clv/report?rows=1`, same-book pregame closes only; joined on event/market/player/segment/side/line/bookmaker AND equal open price | 773 pregame rows -> 688 joined -> **483 same-price** |

- **The real window is 09-30..10-12.** The fleet recorder holds nothing graded before 09-30 (Render's files did not move with the fleet). Halves: H1 = 09-30..10-04 (1,026 rows, 112 games), H2 = 10-05..10-12 (1,004 rows, 170 games).
- `clv_pct` is in PROBABILITY POINTS (a row priced +115 -> close +114 reads 0.2173 = 46.73% - 46.51%).
- Rankings are within sport x date x phase; terciles need >= 3 rows in the slate. 95% CIs bootstrap over games.
- Live rows have no CLV (the report closes pregame only); live is graded on ROI alone.

## The Suggested set itself

**ROI -2.5% [-9.4, +4.4] on 2,030 bets / 282 games; pregame CLV +0.95 pp (n=483).** Beats the close, as the 09-21 study found
for positive-EV rows (CLV real, ROI not yet). Both halves agree: H1 -2.4%, CLV +0.90; H2 -2.7%, CLV +1.00.

By sport x phase (all intervals span zero except WNBA pregame): NFL live +4.1% (468), NCAAF live +2.4% (401), WNBA live
+10.7% (194, 10 games), NCAAF pregame -2.0% (407), NFL pregame -9.5% (127), soccer pregame -22.6% (82), MLB pregame -20.7% (53),
**WNBA pregame -43.6% [-84.9, -2.0] (97, 10 games)**.

## The three rankings (top tercile minus bottom tercile, same slates)

| ranker | ALL: ROI diff [CI] | ALL: CLV diff [CI] | H1 top CLV | H2 top CLV | H1 ROI diff | H2 ROI diff |
|---|---|---|---|---|---|---|
| `sc` (live score) | +2.8 [-12.5, +16.8] | +0.34 [-0.51, +1.28] | +0.99 | **+1.41** | +4.7 | +0.9 |
| `s2` (score_v2, expected growth) | -3.6 [-22.3, +11.9] | +0.16 [-0.75, +1.25] | +1.04 | +1.08 | -8.4 | +1.5 |
| fee-net market EV | +2.5 [-11.3, +19.1] | **+0.52** [-0.41, +1.50] | **+1.17** | +1.35 | +0.3 | **+4.8** |
| model edge (`me`) | +0.1 [-17.4, +15.3] | +0.37 [-0.54, +1.47] | +1.30 | +1.19 | +6.6 | -6.8 |

Top-tercile ROI, ALL: fee-net EV **+0.8%**, sc -3.8%, model edge -3.3%, s2 -4.1%.

## Verdicts on the pre-registered hypotheses

- **H1 (s2 beats sc on CLV in both halves): REJECTED.** H1 half 1.04 vs 0.99 (s2 ahead), H2 half 1.08 vs **1.41** (sc ahead). Promoting score_v2 to rank Suggested is NOT supported.
- **H2 (sc's extra terms over EV do not predict): NOT FALSIFIED.** Model-edge ordering inside Suggested: CLV diff +0.37 [-0.54, +1.47], ROI diff +0.1, and its ROI sign flips between halves (+6.6 -> -6.8). Consistent with `[sim-weight-clv-decomposition]` and the 10-07 season-metric null.
- **H3 (selection, not ordering, carries the return): SUPPORTED.** No ranker's top-vs-bottom difference has a CI excluding zero on ROI or CLV, in either half.

## What this means for scoring

1. **The score's job inside the bet list is small.** On this window, which lines get in (Suggested) matters. How they are ordered once in shows no measurable effect.
2. **Fee-net market EV is the directionally best, and simplest, order:** the best overall CLV gap (+0.52) and top-tercile ROI (+0.8%), positive in both halves on CLV. Not significant. It is also exactly the quantity the flag is defined on.
3. **Do not promote score_v2** (H1 rejected) and **do not add weight to the model term** (H2).
4. **Re-run on more data** before any ordering change has a claim on profit: 282 games is about a quarter of the 09-21 study's 931.

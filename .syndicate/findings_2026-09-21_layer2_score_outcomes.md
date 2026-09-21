# Layer 2 score, graded against outcomes and closes for the first time

Lane `layer2-score-outcome-calibration`, session 236bd219, 2026-09-21. Hypotheses H1-H4
were written into the lane (`615efa70`) before any outcome was read.

**User request:** assess the Layer 2 board scoring for live and pregame game/prop lines,
compare to industry methods, adapt the scoring to best in class, and make sure the top
ranked opportunities hit at a high rate.

## Data: what every number rests on

| dataset | what it is | window | size |
|---|---|---|---|
| A. recorder, graded | `opportunity_population_ledger`: every PRICED candidate, first sighting per identity per phase, with `sc`/`ev`/`fp`/`px`/`bq`/`ba`/`fm`/`ln`/`gs`. Graded row by row with the production grader and settlers (`scripts/score_ranking_backtest.py pull`). | 09-14..09-20 (the recorder started 09-14) | 194,983 graded rows; 103,371 served-equivalent (opportunity lane, EV <= 5.26, scored), 309 games |
| B. CLV, published | `/api/ops/clv/report?rows=1` joined to `clv_openings` (bookmaker, every book's price, `bq`, ages), same-book pregame closes; today's score recomputed exactly with production `blended_score` (movement is 0 at first sighting) | 09-01..09-20 | 157,079 rows, 931 games, 82 date x sport slates |
| C. paper bets | `/api/portfolio/paper` orders with fill price and outcome: the board's actual top picks | 09-08..09-20 | 2,699 settled, 223 games |

The recorder carries no bookmaker, so venue and fee effects are measured on B and C only.
All intervals are 95% bootstraps over GAMES (or over slates for paired contrasts), never rows.
Everything was run locally over production files; nothing in `data/` was used.

## 1. How we score today

`score = min(value, value x reliability)`, where `value = ev_pct + clip(0.125 x model_edge, +/-1.5) + movement (cap 1.0)`
and `reliability = book factor (0.5-1.0) x freshness (0.08-1.0) x price reliability (1 pp floor)`
(`opportunity_signals.blended_score`). `ev_pct` prices the best BETTABLE book against a
fair that is the median of per-book multiplicative de-vigs (`consensus`, 1,900 of 2,000
served rows on 09-21; the Pinnacle `sharp_anchor` on 92). The shortlist drops EV > 5.26
(implied book total < 95%); the portfolio sizes only 2.0 <= EV <= 5.26.

## 2. Does it rank winners? (H3: CONFIRMED -- non-monotone)

Dataset A, served-equivalent, all sports and phases: **top score decile ROI -14.9%**, no
better than deciles 2, 3, 6 and 8 (-9% to -11%); only the bottom decile separates (-30.3%).
The top of the board is a price-shopping list, not a ranking of likely winners.

**The paper bets it produced (C)** hit **45.6% against a 45.2% break-even, ROI +0.5%
[-6.0, +8.8]**, against a stated EV of +3.6%. Realized ROI FALLS as stated EV rises:

| stated EV | orders | ROI | note |
|---|---|---|---|
| 2-3% | 1,105 | +4.7% [-4.2, +13.4] | |
| 3-4% | 753 | +3.6% [-6.4, +14.9] | |
| 4-5.27% | 708 | -4.4% [-16.9, +7.6] | |
| > 5.27% | 133 | **-26.7% [-46.3, -5.9]** | all Kalshi / Polymarket venue-repriced orders |

## 3. Where the value is real, and where it is not

**Price-shopping edge is real in closing-line terms (B).** Positive-EV published rows beat
the same book's close by ~1 probability point; CLV rises from +0.72 (EV 0-1) to +1.09
(EV 3-4) and then PLATEAUS (+1.00 at 4-5.27). Today's score top-10 per slate: **+3.94%
ROI-equivalent CLV [+3.19, +4.80], beat-the-close 59.5%.**

**H1 (winner's curse from sole-best outliers): REJECTED in CLV terms.** Sole-best vs tied
best: +2.47% vs +2.35%. Rows priced 5+ pp off the median book show the BEST CLV (+4.59%):
the generous book corrects toward us. **Venue is what matters: exchange rows +1.58% vs
sportsbook +4.07%**, and **Kalshi rows trail Kalshi's own close by -1.58 points
[-2.05, -1.15] before any fee** (11,319 rows, 602 games).

**H2 (fair quality): PARTLY.** Efficient markets are where an apparent edge is least real:
rows quoted by 7+ books show the lowest CLV (+1.57%) and, on outcomes (A), **-13.8% ROI
[-26.2, -2.6]** in the positive-EV region. Main pregame lines at stated EV 2-5.27%:
**-21.2% [-37.2, -2.9]** (115 games).

**The fair price itself.** On dataset A the consensus fair is well calibrated on game lines
band by band (hit minus fair within about +/-1 pp), and consensus props are calibrated
(-0.1 pp). Two exceptions:
- **`book_margin_model` (one-sided props) fair is overstated by 8.5 pp**: hit 18.0% vs fair
  26.5% [-9.3, -7.7] over 24,442 rows, 264 games. Its EV assumes a much smaller hold than
  those markets carry.
- A logistic slope above 1 in aggregate (favourite-longshot bias: pregame main 1.18
  [1.08, 1.30], live main 1.27 [1.07, 1.53]). **Not adopted**: inside the positive-EV subset
  longshots are calibrated (pregame fair < 0.45: hit = fair within 0.3 pp) and the
  shortfall sits at even money (fair 0.45-0.55: -3.5 pp), where a slope does nothing.
  A global recalibration would demote the +EV longshots that deliver.

**Live.** Live main-line rows with stated EV > 5.27% realized **+34.7% ROI [+21.1, +49.5]**
(211 games; hit 42.0% vs 36.2% break-even) on RECORDED prices. They are stale books after
game events; whether any venue fills at those prices is unmeasured, and both the shortlist
ceiling and the portfolio's in-play refusal already keep them out. Live extreme longshots
(fair < 0.15) with positive EV lost -56.5% (52 games). The separate lane
`ncaaf-live-h2h-top-scores` found in-play +EV longshots at 5-15% implied made +1.20/game;
different cut (implied, all markets, per game), recorded here without resolving it.

## 4. Industry comparison

| Dimension | Syndicate today | Industry best practice | Measured cost of the gap |
|---|---|---|---|
| Fair price | median of per-book multiplicative de-vigs over whoever quotes | de-vig the sharp market, or weight books by measured closing-line accuracy | efficient 7+-book markets: lowest CLV, negative ROI |
| De-vig | multiplicative for consensus | power/Shin default; worst-case for a conservative EV | small in the +EV subset (see section 3) |
| **Fees** | **EV gross; fees only at execution** | **EV is net of commission/fees** | **Kalshi -1.58 pts CLV; >5.27% venue orders -26.7% ROI** |
| Estimate uncertainty | reliability multipliers, `min` rule | Bayesian shrinkage (optimizer's curse), Kelly under parameter uncertainty | the reliability terms help: fee-net EV x reliability beat bare fee-net EV at the top 10 (unpaired) |
| Ranking objective | EV + capped sim + capped movement, discounted | find by EV, prioritize by fractional-Kelly log growth | today's top-10 break-even 0.378 (median +150) |
| Live | same formula, looser clocks | synchronized quotes, suspension detection | +EV live rows win on recorded prices; fillability unknown |
| Validation | score never graded before this lane | CLV as KPI, ROI by EV bucket, calibration, out of sample | -- |
| Movement | rewards moves toward the pick | follow sharp-book moves; the lagging soft book is the value | away-moved rows beat the close (lane `layer2-adverse-movement-sanity`) |

Sources for the practice column: de-vig methods and worst-case EV (Outlier, OddsJam,
Crazy Ninja guides); Pinnacle as the reference market; Baker & McHale (2013),
"Optimal Betting Under Parameter Uncertainty"; fractional Kelly as the professional norm.

## 5. What was built (on main, NOT deployed)

- `scripts/score_ranking_backtest.py` + `scripts/score_ranking_analysis.py` (`1e9b687b`):
  the instrument this lane was missing -- the priced population graded row by row with its
  score kept. 10 tests. It also fixed its own bug: an `id()`-keyed chip cache grew to 8.9 GB
  and could return another day's scoreboard in a playoff series.
- **`score_v2`, SHADOW** (`456e264f`, `97f01a37`): `min(g, g x reliability)`, g = quarter-Kelly
  log growth (bp) at the FEE-NET price, or the fee-net EV (<= 0) when nothing is sizable.
  Kalshi 0.07 x m x P(1-P) per series (unknown series charged full rate, flagged); Polymarket
  0.015 per contract (measured). No sim term, no movement term. Stamped as
  `candidate["score_v2"]`; nothing ranks, admits or sizes on it. Off: `SYNDICATE_SCORE_V2=0`.
- **`SYNDICATE_SCORE_FEE_NET` (default OFF)**: when on, a market-fair row at a fee venue feeds
  `blended_score` its fee-net EV. `ev_pct` stays gross. The board-scoring change, awaiting
  the user.

## 6. Which candidate wins (B, paired over 82 slates, net of the fee actually paid)

| contrast (top-K per date x sport, <= 3 per game) | top 10 | top 25 |
|---|---|---|
| **today's score with fee-net EV - today's score** | **+0.79 [+0.27, +1.29]** | **+0.71 [+0.40, +1.04]** |
| fee-net EV x reliability (no sim) - today | +0.71 [+0.13, +1.29] | +0.62 [+0.28, +0.98] |
| score_v2 (Kelly) - fee-net EV x reliability | -0.01 [-0.66, +0.69] | -0.18 [-0.50, +0.16] |

(MLB Kalshi at its real half rate; with the full rate for MLB, v2 - today is +0.91
[+0.19, +1.64] at the top 10.) Fee-netting helps in every sport (NFL +1.34/+1.44, soccer
+1.32/+0.80, MLB -0.04/+0.67, NCAAF +0.51/+0.19). The Kelly re-rank is sport-dependent:
soccer +3.00 [+1.75, +4.22], **NCAAF -2.71 [-4.03, -1.47]** at the top 10.

**Hit rate.** score_v2's top-10 break-even is **0.464 vs 0.378** (median price +114 vs +150),
beat-the-close 61.7% vs 59.5%: the higher hit rate the request asked for, at statistically
equal edge overall -- but NOT in NCAAF.

**On dataset A (7 days of outcomes)** no candidate separates from today's score at the top
(every top-K interval spans roughly +/-25 ROI points). One week of outcomes proves
calibration errors; it cannot settle a ranking contest.

## 7. Not claimed

- CLV is not ROI; the CLV population is the PUBLISHED board, not fills.
- The recorder records the FIRST sighting, not the price a row held at the top.
- Exchange fees beyond Kalshi/Polymarket (ProphetX, Novig) are taken as zero -- unverified.
- The +34.7% live result is on recorded prices, not fills.

## 8. Recommendations (each the user's decision)

1. **Turn on `SYNDICATE_SCORE_FEE_NET`** (refresh-worker env + deploy): the one change with a
   robust out-of-sample gain (+0.7 pts fee-net CLV at the top 25).
2. **Deploy the shadow** so `score_v2` is on the served board and graded nightly; promote the
   Kelly rank per sport only where it holds (soccer yes, NCAAF no, others pending).
3. **Portfolio:** apply the 5.26 ceiling and the fee to VENUE-repriced EV (the -26.7% bucket).
4. **Recorder:** let this lane take `opportunity_population_ledger.py` (held by OPEN lane
   `model-scorecard-cron`) to record `score_v2` and the bookmaker, so the nightly scorecard
   grades both scores on the whole priced population.
5. `book_margin_model` fair: overstated 8.5 pp; any consumer of that fair should be reviewed.
6. Live fillability: measure whether the venues fill at the stale in-play prices before
   touching the in-play refusal.

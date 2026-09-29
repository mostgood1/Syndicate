# The fee-net Layer 2 score, tested out of sample: MET

Scheduled task `layer2-fee-net-7-slate-reading-0929`, run unattended 2026-09-29 10:15-10:40 CDT.
Brief: `scheduled_task_layer2_fee_net_7_slate.md`. **Read-only: nothing was deployed, no env var
changed, `render.yaml` untouched.** Everything below was read from production (web's disk over
`/api/ops/artifacts/stream`, `/api/ops/clv/report`, `/api/portfolio/paper`, `/api/portfolio/live`,
the public scoreboards). Nothing in `data/` was used except the git-tracked NCAAF team registry,
copied into the snapshot as the brief requires.

**Pinned tree:** every script and brief was read from `origin/main` **`a5b06c7b`** (captured once at
10:15 CDT, snapshot built by `git archive` from that SHA into `C:\tmp\l2win`).

This discharges the `verify (OWED)` in `deploys.md` at 2026-09-21 21:43:55Z (refresh-worker
`dd43fd49`, `SYNDICATE_SCORE_FEE_NET=1`, live 16:49 CDT 09-21).

## Verdict (pre-registered rule, top 25, fee-net CLV points)

| | paired diff, new - old | 95% interval | rests on |
|---|---|---|---|
| **top 25, bootstrap over GAMES (primary)** | **+0.65 pp** | **[+0.45, +0.86]** | 231 games, 40 date x sport slates, 8 dates (09-21..09-28) |
| top 25, slate-paired (the in-sample section 6 presentation) | +0.70 | [+0.44, +0.97] | 40 slates |
| top 10, games (secondary) | +0.54 | [+0.20, +0.89] | 177 games, 40 slates |
| in-sample being tested (09-01..09-20) | +0.71 top 25 / +0.79 top 10 | [+0.40, +1.04] / [+0.27, +1.29] | 82 slates |

**MET**: the mean is positive and the interval excludes 0. The out-of-sample estimate matches the
in-sample one: +0.70 slate-paired against +0.71.

**The contrast is measurable. It is not a small-support null.** 211 of the 853 top-25 picks differ
between the two rankings (25%), and 33 of 40 slates changed. The fee-venue share of the top 25 falls
from 29.5% (old) to 4.9% (new). Fee-venue rows are 4,992 of 66,545 joined openings (7.5%): Kalshi
4,331, Polymarket 661.

**Robustness:**
- **Without 09-21** (the deploy day; 7 dates, 34 slates, 219 games): +0.65 [+0.45, +0.86] at the top
  25 and +0.48 [+0.10, +0.85] at the top 10.
- **This is not just the fee being charged to the old picks.** On GROSS CLV (no fee charged to either
  arm) the new top 25 still beats the old one: +0.29 [+0.10, +0.47]. On the ROI-equivalent scale the
  top-25 gain is +1.65% [+1.09, +2.20].

**Per sport, top 25 (games bootstrap):** NFL +0.98 [+0.62, +1.44], WNBA +1.26 [+0.40, +2.36],
soccer +0.85 [+0.42, +1.37], NCAAF +0.63 [+0.17, +1.15], **MLB +0.40 [-0.17, +0.94] (spans 0)**,
NHL 0.00 (no fee-venue rows in its top K, so nothing moved). MLB was also the weakest sport in
sample (-0.04 / +0.67).

## How the CLV route was run

- **Population:** `/api/ops/clv/report?date=d&sport=s&rows=1` for d = 09-21..09-28 and six sports.
  Each row is joined on (date, key) to `reports/intelligence/clv_openings/<d>.jsonl`, keeping only
  pregame closes at the same book. The filters are the in-sample ones: `book_margin_model` fairs are
  dropped and EV must be <= 5.263. That leaves 66,545 rows (12,000 were not pregame/same-book and 56
  had no price or fair).
- **Both scores are recomputed** with production `opportunity_signals.blended_score` from the pinned
  tree. Movement is 0, as at first sighting. The old score uses gross `ev_pct`. The new score feeds
  the value term the fee-net EV `100 x (fair / (price_prob + fee) - 1)`, using the production fee
  (`venue_fees.taker_fee_per_contract`, with sport/market/segment) and only where the fee basis is
  not `none`, which is the production gate.
- **Metric: fee-net CLV in probability points** = `100 x (implied(close) - implied(open) - fee per
  contract)`. `clv_pct` is `implied(close) - implied(open)` (`clv_join.clv_pct_from_prices`), so this
  charges both arms the fee they would actually pay.
- **Selection and inference:** top K per (date x sport), at most 3 per game (`score_ranking_analysis.top_k_per_date`).
  The interval is a 2,000-draw bootstrap that resamples GAMES and keeps each game's contribution to
  both arms. Seed 20260929.
- **Stated plainly:** the in-sample paired script behind section 6 was **never committed**. This
  run rebuilds it from the lane's surviving scratch (`C:\tmp\l2score\clv_join_openings.py`) and from
  the section 6 text. Because the new number lands on the in-sample one (+0.70 vs +0.71), the
  reconstruction is probably faithful. Probably is not proven.
- Scripts: `C:\tmp\l2score\oos\{fetch,clv_contrast}.py`; output: `clv_contrast_out.txt`, `clv_contrast_0922on.txt`.

## The recorder route (outcomes), 7 kickoff dates: uninformative, as expected

`scripts/score_ranking_backtest.py pull --start 2026-09-14 --end 2026-09-28` graded **406,814 rows**.
`extra_team_unresolved` was only 764 against 24,829 on the 09-22 run, so the registry copy worked
and NCAAF is present. After filtering to kickoff dates 09-22..09-28, served-equivalent rows, and first
sightings after 2026-09-22T00:12:34Z carrying `n2`/`fb`, the population is 108,970 rows, 244 games,
**24 date x sport slates over 7 dates** (MLB 6, NHL 5, WNBA 4, NFL/NCAAF/soccer 3 each). 5,646 of
those rows carry a fee.

| top-K by recomputed score, outcome ROI | diff new - old | games |
|---|---|---|
| top 25 | -25.7 [-81.7, +6.6] | 191 |
| top 25, hit minus break-even | -0.57 pp [-4.29, +3.29] | 191 |
| top 25, ex-soccer | -0.6 [-11.7, +9.7] | 178 |
| top 10 | -0.5 [-13.3, +11.5] | 136 |

**The -25.7 comes from a single row:** a Kalshi soccer totals contract priced **+9900** (a 1-cent
contract) on 09-26. It ranked in the OLD top 25, the fee term demoted it, and it won 99x the stake.
Every outcome interval spans zero. That matches both earlier readings, which said one week of
outcomes cannot settle a ranking contest. Not a contradiction of the CLV verdict.

A 1-cent Kalshi contract near the top of a ranking is worth a look on its own. **Recorded here as
a lead only. It was not investigated and no lead file was written.**

On non-fee rows the recomputed old score equals the recorded `sc` on only 48,668 of 103,324 rows. The
recorded score carries the movement term, and model-basis rows use model EV. So the recorder route
compares two recomputed scores, not the served one.

## Paper-order ROI by venue, selected dates 09-22..09-28

`settlement.by_venue` summed over the seven `/api/portfolio/paper?date=` payloads:

| venue | settled | staked | P&L | ROI |
|---|---|---|---|---|
| **sportsbook (`paper`)** | 1,501 | $3,983.10 | -$77.93 | **-1.96%** |
| **exchange (`paper:*`)** | 1,440 | $3,886.77 | -$20.67 | **-0.53%** |
| paper:kalshi | 212 | $396.35 | +$10.32 | +2.60% |
| paper:novig | 335 | $956.71 | -$53.91 | -5.63% |
| paper:polymarket | 61 | $103.38 | +$19.02 | +18.40% |
| paper:prophetx | 832 | $2,430.33 | +$3.90 | +0.16% |

On order level (`orphan_orders`: 3,600 unique, 2,756 settled with P&L), with a game bootstrap:
sportsbook -2.51% [-8.7, +3.7] over 131 games, exchange -1.20% [-7.9, +5.8] over 121 games. Neither
is distinguishable from zero.

**The stated-EV > 5.27% bucket is EMPTY, and the empty result is informative.** It lost -26.7%
[-46.3, -5.9] in sample. The bucket holds 0 of 3,600 paper orders, 0 plan rows and 0 venue-comparison
(`paper2`) rows submitted after the cut. It is not empty for lack of orders: the buckets beside it are
full. 2-3%: 1,122 settled, +0.99% [-11.2, +12.3]. 3-4%: 708, -12.63% [-24.7, -0.1]. 4-5.27%: 926,
+2.62% [-7.8, +13.3]. The highest stated EV on any venue is 5.262.

## The Kalshi half of the venue ceiling: DISCHARGED

The first live Kalshi order after the ceiling went live was placed **2026-09-26 15:04 CDT**. There are
**26** through 09-29 01:29 CDT (`/api/portfolio/live?on=all&show=all`). All 26 carry stated
`ev_pct` <= 5.263 (max 5.250). **All 26 have positive EV after the fee actually charged**
(`fees_dollars / contracts`): min +0.91%, max +2.68%. Zero violations. 8 have settled: 3 won, 5 lost,
-$4.92 on $11.56. That is too few to say anything about ROI.

Polymarket, 25 live orders since 09-22 (max stated EV 5.005): 24 of 25 are positive after the fee
charged. The exception is a 1-contract NCAAF totals order at 0.48, 2026-09-27 23:11 CDT, whose fee
rounded up to $0.02 against a modelled $0.015: fee-net -0.16%. That is cent rounding on a single
contract, not a ceiling failure. Realised Polymarket fees run at about $0.017-0.020 per contract
against the $0.015 the model charges.

**Endpoint fact, corrected:** the 09-22 finding said `/api/portfolio/live` "ignored the date filter".
The parameter is **`?on=<date>|all`**, not `?date=` (`intelligence._resolve_live_slate`). `?date=` is
silently ignored and the view defaults to today.

## `score_v2`: running tally only, NOT decided here

The gate is todo `#679` step 5, about 2026-10-06, with a multiple-comparisons guard. The recorder
route over 7 dates, `s2` against the recorded `sc`:

- **Top 25:** `s2` -0.0% [-11.4, +11.5] against `sc` -12.7% [-25.9, +0.6]. Paired difference
  +12.6 [+3.8, +22.0] over 202 games. Hit rate against break-even: 0.497/0.499 for `s2`, 0.374/0.411
  for `sc`.
- **Top 10:** +4.5 [-12.3, +20.6].
- **Per sport, top 25:** MLB +21.0 [+5.2, +36.6], WNBA +20.0, soccer +22.2, NCAAF +10.7, NFL -2.2,
  NHL -2.0. Every sport except MLB spans zero.
- **NCAAF at the top 10: -15.8 [-83.5, +39.5].** Same sign as the in-sample -2.71, and nowhere near
  resolved.

## Not claimed

- CLV is not ROI. The CLV population is the published board, not fills.
- That the outcome route supports the verdict. It is uninformative, and it neither supports nor
  contradicts.
- That the reconstructed metric is identical to the uncommitted section 6 script. See "How the CLV
  route was run".
- Any `score_v2` decision.

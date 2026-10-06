# `score_v2` promotion decision, per sport (todo `#679` step 5): DO NOT PROMOTE in any sport

Scheduled task `layer2-score-v2-promotion-decision-1006`, ran unattended 2026-10-06 from about 10:05 to 10:30 CDT.
Brief: `scheduled_task_score_v2_promotion_decision.md`. **Read-only.** Nothing was deployed, no env var
was changed, nothing was promoted, and `render.yaml` was not touched.

**Pinned tree:** every script, brief and prior finding was read from `origin/main` **`51d68f1a`**
(`51d68f1ab2f0510705778a2e0753745d07ae6881`). The SHA was captured once at the start, and the snapshot was cut
from that SHA by `git archive` into `C:\tmp\l2win1006`, with the git-tracked NCAAF team registry
copied in. `origin/main` had moved to `ec240921` by the time this was written.

**Substrate.** The run read the **local fleet** (`http://127.0.0.1:10000`, which has been production since the
Render suspension on 2026-09-30). Openings and CLV for 09-21..09-28 were reused from the 09-29 run's Render
pull (`C:\tmp\l2score\oos\`). 09-29..10-05 were fetched from the fleet today. The recorder parts are
cached across both.

## Verdict: the rule was fixed before any number was read

The primary contrast is per sport: `s2` ranking minus live-score (`sc`) ranking, measured in fee-net CLV probability
points. It takes the top 25 per (date x sport) slate, at most 3 rows per game, and uses a 2,000-draw bootstrap over GAMES
(seed 20261006). The "games" count is the union of games in either arm's top 25.

| sport | top 25, s2 - sc | top 10 | games / slates | in-sample sign (top 10) | verdict |
|---|---|---|---|---|---|
| **NCAAF** | -0.28 [-0.67, +0.11] | -0.03 [-0.47, +0.44] | 106 / 10 | **negative** (-2.71) | **DO NOT PROMOTE** (spans 0, leans the in-sample way) |
| soccer | -0.02 [-0.12, +0.06] | +0.07 [-0.28, +0.52] | 17 / 9 | positive (+3.00) | **NOT DECIDABLE**: only 5 of 159 picks differ |
| NFL | +0.04 [-0.14, +0.24] | +0.19 [-0.11, +0.52] | 32 / 13 | not separated | **DO NOT PROMOTE** (spans 0) |
| MLB | -0.19 [-0.58, +0.14] | +0.23 [-0.21, +0.71] | 87 / 11 | not separated | **DO NOT PROMOTE** (spans 0; regular season and postseason mixed) |
| NHL | -0.06 [-0.18, +0.05] | +0.04 [-0.16, +0.25] | 76 / 11 | not separated | **DO NOT PROMOTE** (spans 0; preseason; 10 of 204 picks differ) |
| WNBA | **+0.96 [+0.15, +1.78]** | +0.45 [-0.60, +1.34] | 22 / 8 | **none, not separated** | **DO NOT PROMOTE**: significant with no in-sample sign to agree with (see the guard) |
| **all** | -0.04 [-0.17, +0.09] | +0.14 [-0.04, +0.32] | 340 / 62 | -0.18 [-0.50, +0.16] | equal edge, reproduced |

**No sport is REJECTED.** No interval excludes 0 on the negative side over the full window.

**The multiple-comparisons guard.** One sport of six cleared 95%, and chance alone produces about that many. WNBA has no
in-sample estimate, so the second condition (sign agreement) cannot be met. Its +0.96 is therefore a
**lead, not a discovery**. It also rests on 22 playoff games, 16 of them in the first week (+1.11 [+0.04, +2.15]),
and only 6 in the second (+0.56 [-0.29, +1.41]).

**Coverage.** The population is 113,913 joined rows: 384 games and 62 slates across 13 dates, 09-22..10-05 **minus 09-29**. The
fleet has no `clv_openings/2026-09-29.jsonl`, and every 09-29 CLV report is empty. The CLV route recomputes
`s2` for every row, so it covers 100% of the joined population. On the recorder route, **`s2` is carried by
100%** of served-equivalent rows first sighted after the cut, in every sport (MLB 55,196, NCAAF 39,745, NFL 44,779,
NHL 7,832, soccer 4,015, WNBA 31,300). Neither route is a subset contrast.

## The shape reproduced, and the shape is not the decision

Overall, `s2`'s top 25 sits at a shorter price: break-even 0.452 against 0.413, as in sample (top 10: 0.451 vs 0.397, against
0.464 vs 0.378). **Beat-the-close did NOT reproduce**: 59.2% for `s2` against 61.0% for `sc` at the top 25, and
59.7% vs 59.5% at the top 10. The in-sample figures were 61.7% vs 59.5%. Edge is equal and the board would hit more
often at shorter prices. That is a preference, and it is the user's to state. This reading does not infer it.

Against the in-sample section 6 comparator (fee-net EV x reliability, no sim), `s2` comes out at +0.00
[-0.11, +0.11] at the top 25 overall. No sport excludes 0 there except NHL at the top 10, on 1 differing pick.

## NCAAF, the sport the decision turns on: unstable, not resolved

- 09-22..09-28 (6 slates, 58 games): **-0.61 [-1.16, -0.06]**. This has the in-sample sign and excludes 0.
- 09-30..10-05 (4 slates, 48 games): **+0.16 [-0.31, +0.68]**.
- Full window: -0.28 [-0.67, +0.11].

The halves disagree in sign. The direction is still the in-sample one, but nothing is settled. In any case, a negative NCAAF reading
can only ever argue against promotion.

## Soccer, the only sport with a positive prior: the population cannot test it

There are 17 games across 9 slates, and **5 of 159 top-25 picks differ** between the two rankings, so the two arms are nearly
the same rows. The CLV report resolves very little soccer. On 09-30..10-02 it resolved 28/37/29 rows against
57/59/61 report openings. On 10-03 and 10-04 it returned **0 rows and 0 openings**, while the fleet's 10-04
openings file holds 967 soccer rows. **This is a lead and was not investigated.** Soccer CLV coverage is either a capture
or a join gap. Until it is fixed, the in-sample +3.00 cannot be re-tested.

## Secondary route: outcomes from the recorder (not the decision metric)

`scripts/score_ranking_backtest.py pull --start 2026-09-18 --end 2026-10-05` graded **467,833 rows**.
`extra_team_unresolved` came to **1,284**, so the registry copy worked and NCAAF is present. That leaves 182,867 rows
across kickoff dates 09-22..10-05: served-equivalent, first sighted after 2026-09-22T00:12:34Z, with recorded `s2` and `sc`. They cover 378 games
and 47 slates. Outcome ROI for `s2` minus `sc`, games bootstrap:

| | top 25 | games | top 10 |
|---|---|---|---|
| all | +9.8 [+2.5, +16.9] | 313 | +3.9 [-7.7, +15.7] |
| MLB | +18.4 [+2.5, +32.2] | 91 | +7.1 [-20.6, +30.8] |
| NCAAF | +16.3 [-8.6, +42.3] | 76 | -0.5 [-36.4, +36.1] |
| NFL | +2.3 [-19.1, +22.3] | 31 | +0.3 |
| NHL | -1.9 [-7.7, +3.6] | 75 | -1.2 |
| soccer | +17.6 [-13.2, +49.0] | 17 | +6.6 |
| WNBA | +14.2 [-16.2, +43.4] | 23 | +13.1 |

The overall +9.8 is driven by `sc`'s top 25 **hitting below its own break-even** (0.398 vs 0.424) while `s2` sits
on it (0.505 / 0.505). That is a live-score finding as much as an `s2` one. MLB's outcome result points the opposite way from its CLV
result (-0.19), and outcomes over two weeks are the noisier instrument. All three earlier readings said this route cannot
settle a ranking contest. **It is recorded here and it changes no verdict.**

**Faithfulness of the recomputed `s2`:** `opportunity_signals.score_v2`, recomputed from the recorder's own inputs,
lands within 1 bp of the recorded `s2` on 552 of 552 sampled positive rows, and matches on 177 of 180 fee rows. The
apparent misses on non-positive rows are differences of about 0.005 that come from the recorder rounding `fp` to 4 decimal places.

## Method

- **CLV route.** `/api/ops/clv/report?date=d&sport=s&rows=1` is joined on (date, key) to `clv_openings/<d>.jsonl`. The run keeps
  pregame same-book closes, drops `book_margin_model` fairs, and caps EV at 5.263. `sc` is the production `blended_score` with the
  fee-net EV wherever the production fee basis is not `none`, which is the live score since `SYNDICATE_SCORE_FEE_NET=1`, pinned on the fleet
  10-04. Movement is 0, as at first sighting. `s2` is the production `score_v2` with the same `venue_fees.taker_fee_per_contract` fee. The metric is
  `100 x (implied(close) - implied(open) - fee)`.
- Scripts and outputs are in `C:\tmp\l2score\v2\`: `v2_clv_contrast.py` (`clv_full.txt`, `clv_halves.txt`), `v2_recorder.py`
  (`recorder_out.txt`), `fetch.py`, `pull_1006.log`.

## If this is to become decidable

- **Soccer** needs a CLV population first. The resolved-row gap above has to be closed, and then the run repeated over at least about 10 match-days.
  This is the only route to a PROMOTE, because soccer is the only sport with a positive in-sample sign.
- **NCAAF** needs about 4 more Saturdays (to roughly 11-01) for the halves to settle. Even then it can only confirm DO NOT PROMOTE or REJECT.
- **WNBA**: its season ends inside this window, so the lead cannot be re-tested until 2027.

If any sport later qualifies, `docs/ai_context/model_engine_standard.md` applies. The change is a mechanism change to a calibrated
ranking, so the terms that absorb what `score_v2` expresses (the sim term and the movement term) may need re-fitting. Two mechanisms added
together have produced a NEGATIVE interaction in this repo before. A per-sport switch also needs a reachability test (`off != on`)
before correctness tests.

## Not claimed

- That `s2` is worse than `sc` anywhere. No negative interval excludes 0 over the full window.
- That WNBA's +0.96 is real.
- That the fee-net live score is better than `s2`. Both are equal edge.
- Anything about 09-29, which has no data on the fleet.
- CLV is not ROI, and the CLV population is the published board, not fills.

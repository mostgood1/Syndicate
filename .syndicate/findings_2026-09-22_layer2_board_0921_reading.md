# The Layer 2 board on 2026-09-21, graded — the first slate after the fee-net score, and it cannot grade it

Session `dc70079c`, 2026-09-22 20:2x-21:0xZ. **No lane** — read-only, in answer to the user's
question "how did the Layer 2 board do yesterday after implementing the new scoring model?".
Substrate `render` throughout (production files over `/api/ops/artifacts/stream`, the public
scoreboard, and two production APIs); nothing in `data/` was used.

**The headline is a negative:** 2026-09-21 is not a reading on the new scoring model, and no
arrangement of it can be made into one. The change went live *during* the evening it would be
judged on, it touches only exchange-priced rows, and the recorder keeps each row's FIRST
sighting — so most of Monday's board is recorded with a pre-change score. Every positive number
below has an interval spanning zero.

## What every number rests on

| dataset | what it is | how |
|---|---|---|
| A. recorder, graded | 405,081 records 09-14..09-21 pulled from production, 182,769 graded row by row with the production grader and settlers (`mlb/1`, `soccer/1`, `espn/1`, `nhl/1`) | `scripts/score_ranking_backtest.py pull --start 2026-09-14 --end 2026-09-21`, run 2026-09-22 20:2xZ from a git-archive snapshot of `origin/main` `7981b304` |
| B. CLV, published | `/api/ops/clv/report?date=2026-09-21&sport=<s>&rows=1`, six sports | fetched 2026-09-22 20:5xZ |
| C. paper book | `/api/portfolio/paper?date=2026-09-21` | fetched 2026-09-22 20:4xZ |
| D. slate control | `statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-09-21` | fetched 2026-09-22 21:0xZ |

Intervals are 95% bootstraps over **games**, never rows, matching
`findings_2026-09-21_layer2_score_outcomes.md`. Hit rate is always reported beside break-even.

**One limitation of THIS run, stated up front.** The snapshot carries no `data/`, so
`ncaaf_team_registry_snapshot.csv` is empty and 24,829 NCAAF rows fell out as
`extra_team_unresolved`. That is irrelevant to 09-21 (zero NCAAF kickoffs) but it means the
09-14..09-20 baseline quoted here **undercounts NCAAF** and is not identical to the 194,983-row
population in the 09-21 findings file.

## 1. The slate, and it is complete

14 games with a Central kickoff date of 2026-09-21: **MLB 3, NFL 1 (MNF), NHL 8 (preseason),
WNBA 2**. Zero NCAAF and zero soccer kickoffs.

This is coverage, not a gap: dataset D returns `totalGames 3` for MLB — TOR @ BAL, WSH @ DET,
MIN @ SF, all Final — so the whole league played three games. The recorder carried exactly 3 / 1
/ 8 / 2 distinct events for the date and the grader dropped **none** of them (distinct recorded
events per sport == graded games per sport). A Monday in the last week of the MLB season is the
smallest slate the board sees.

## 2. What went live, and when (local CDT, because the question was about a day)

| change | commit | live |
|---|---|---|
| fee-net EV in `blended_score` (`SYNDICATE_SCORE_FEE_NET=1`) | `dd43fd49` | **09-21 16:49** (21:49:21Z) |
| MLB Kalshi fee series resolved from the market (real x0.5 rate) | `03d3f801` | 09-21 18:04 (23:03:59Z) |
| venue 5.26% ceiling + recorder fields `s2/n2/fb/bk` | `f0e60bec` | 09-21 19:12 (2026-09-22T00:12:34Z) |

**Two facts make 09-21 unusable as a verdict, and they are structural, not bad luck.**

- **The fee-net term only moves rows priced at a FEE VENUE.** `deploys.md` records 315 such rows
  at the deploy reading and 158 of 1,837 on the board written at 00:16:57Z. For the other ~90%
  of rows the new score is byte-identical to the old one. Its visible effect is *demotion* —
  Kalshi + Polymarket in the top 100 went **62 -> 8**.
- **The recorder keeps the FIRST sighting per identity per phase.** Most of Monday's pregame rows
  were first sighted between 00:00Z and 07:00Z on 09-21 (i.e. Sunday evening CT) and carry a
  pre-deploy `sc`, even though the served board rescored them from 16:49 CDT onward. So "old" and
  "new" cannot be separated by re-reading the recorder; only rows FIRST SEEN after 21:49:21Z
  carry a fee-net score.

## 3. The whole board, 09-21 vs the week before it

```
population                       n     games   hit    break-even    ROI
09-21 all served-equivalent    7,124     14   48.1%     51.6%     -10.2% [-12.3, -7.0]
09-14..09-20 baseline         92,736    305   41.6%     46.6%     -16.9% [-19.2, -14.8]
```

Monday looks better than the week and the reason is slate composition, not scoring: no NCAAF or
soccer alternate-line ladders, and a break-even 5 points higher (shorter prices).

Per date, served-equivalent ROI: 09-14 -8.1%, 09-15 -12.4%, 09-16 -12.5%, 09-17 -8.8%,
09-18 -18.8%, 09-19 -25.1%, 09-20 -16.3%, **09-21 -10.2%**.

## 4. The part the portfolio actually bets, and the top of the board

```
                                 n     games   hit    break-even    ROI
09-21 bet window (EV 2-5.26)     138      9   42.0%     38.8%      -1.4% [-17.4, +20.4]
baseline bet window            1,408    233   37.9%     38.8%      -2.1% [-10.3,  +5.9]

09-21 top-10 per slate (<=3/g)    28     10   50.0%     40.0%     +15.1% [-42.5, +76.8]
baseline top-10                  217    127   42.4%     41.2%      +0.9% [-17.1, +19.6]

09-21 top-25 per slate            42     14   47.6%     42.6%      +7.2% [-34.8, +53.2]
```

**Indistinguishable from the baseline in both.** The bet window moved 0.7 ROI points on an
interval 38 points wide; the top-10 moved +14 points on an interval 119 points wide.

## 5. Restricted to the rows the new score actually ranked

Rows with a 09-21 kickoff first sighted at or after 21:49:21Z — 4,315 rows, 13 games, 87% live:

```
                                 n     games   hit    break-even    ROI
all new-scored                 4,315     13   48.8%     52.4%      -8.9% [-12.4, -6.0]
  mlb                            996      3   47.7%     51.2%      -8.7% [-11.6, -6.4]
  nfl                            945      1   50.2%     52.5%      -5.1%  (one game, no CI)
  nhl                             88      7   53.4%     53.3%      -8.0% [-14.6, -1.5]
  wnba                         2,286      2   48.6%     52.9%     -10.7% [-14.1, -6.6]
bet window                       104      8   48.1%     40.2%      +9.9%  [-6.4, +34.5]
top-10 per slate by `sc`          28     10   50.0%     45.0%      -0.4% [-47.5, +54.4]
top-25 per slate by `sc`          39     13   48.7%     46.2%      -1.6% [-36.7, +39.5]
```

**The deciles are still non-monotone**, which is the defect the calibration lane found and which
fee-netting was never meant to fix:

```
decile  1      2      3      4      5      6      7      8      9     10
ROI  -15.4  -12.1   -3.7   -6.8   -1.5   +0.4  -16.3  -10.5   -6.8  -16.7
```

The top decile is the second worst of the ten.

**The pregame/live split is confounded and is recorded only so nobody re-derives it as a
contrast.** Pregame sighted before 21:49Z: -12.2% [-15.8, -7.8] (n 2,809, 14 games). Pregame
sighted after: -19.7% [-27.8, +5.5] (n 575, 10 games). Live (all after): -7.3% [-10.0, -6.0]
(n 3,740, 13 games). The two pregame groups differ in *when in the day the row was first
priced*, not only in which score stamped it.

## 6. The shadow `score_v2` — the one signal pointing anywhere

3,595 of those 4,315 rows carry `s2` (the recorder field went live 19:12 CDT). Ranking the SAME
population two ways:

```
top-K per slate, <=3/game       n     games   hit    break-even    ROI
by `s2` (shadow Kelly)  top-10   28     11   60.7%     51.0%      +4.6% [-19.6, +27.8]
                        top-25   35     12   62.9%     53.1%      +6.4% [-11.9, +24.2]
by `sc` (live score)    top-10   28     11   53.6%     44.0%      +4.5% [-39.3, +53.2]
                        top-25   35     12   54.3%     46.9%      +1.7% [-33.7, +41.5]
```

Same direction as the 7-day result in `findings_2026-09-21_layer2_score_outcomes.md` (top-10
break-even 0.464 vs 0.378): **a higher hit rate at a shorter price, on a tighter interval, at
statistically equal edge.** n=35 on one night. It is a second independent slate agreeing, and
nothing more. Filed as a lead, not promoted — `#679` step 5 still wants 14+ days of recorder
grading from 09-22, and the sport-dependence (soccer +3.00, NCAAF -2.71) was untestable on a
Monday with neither sport playing.

## 7. CLV, 09-21 (dataset B)

| sport | avg CLV | beat-close | same-book rows | openings / resolved |
|---|---|---|---|---|
| mlb | **+0.43%** | 40.5% | 247 | 2,893 / 585 |
| nfl | +0.26% | 40.7% | 435 | 2,059 / 435 |
| wnba | +0.51% | 47.6% | 2,120 | 4,296 / 2,120 |
| nhl | +0.38% | 32.1% | 28 | 102 / 28 |
| soccer | — | — | 0 | 417 / 0 |
| ncaaf | — | — | 0 | 1,777 / 0 |

Soccer and NCAAF resolve to nothing because neither had a 09-21 kickoff; the openings are
next-weekend rows. These are whole-population averages, not the top-K contrast the deploy owes.

## 8. The paper book (dataset C)

834 orders, **222 decided: 96 won / 126 lost = 43.2%**. By sport: MLB 52W / 76L
($115.90 / $170.23 staked), WNBA 44W / 50L ($101.80 / $103.83).

537 `not_started` is **not** a settlement failure: 475 of them are NCAAF orders for future
Saturdays ($1,751.66 staked) and 37 are NFL. The payload carries stake but no price, so **paper
ROI is not computable from it** and none is claimed here.

## 9. Real money on 09-21

Ledger-recorded by lane `layer2-score-outcome-calibration`, not re-measured here: 9 Kalshi orders
on 09-21, **all submitted before the ceiling went live, 6 of the 9 carrying stated EV > 5.26%**
(max 28.0%) — the bucket the 7-day calibration measured at **-26.7% ROI [-46.3, -5.9]**. So
yesterday's real-money book was placed under the old rules end to end. The first orders under the
ceiling are 09-22's, and that reading (13:23 CDT 09-22) held on n=8, all Polymarket; the Kalshi
half is still owed.

## 10. Not claimed

- That the fee-net score helped or hurt on 09-21. It cannot be read from one slate, and for ~90%
  of rows it changed nothing at all.
- That the top-10's +15.1% means anything. Its interval is 119 ROI points wide on 10 games.
- That `score_v2` should be promoted. Two agreeing slates is not the 14 days `#679` step 5 asks for.
- Any per-sport statement for soccer or NCAAF on 09-21 — neither played.
- A paper-book ROI (no prices in the payload) or a 09-21 real-money ROI (`/api/portfolio/live`
  ignored the date filter on the order list and returned 09-22's open orders).

## 11. What would settle it

Unchanged from the deploy's own `verify (OWED)` in `deploys.md`: **fee-net CLV of the served
top-K against the pre-deploy baseline over >= 7 finished slates, paired on the same slates**
(`scripts/score_ranking_backtest.py`), plus paper-order ROI by venue after 09-21. With 09-21 as
day 1, the window closes around **2026-09-28**. `score_v2` promotion is a separate gate: 14+ days
of recorder grading from 09-22, decided per sport.

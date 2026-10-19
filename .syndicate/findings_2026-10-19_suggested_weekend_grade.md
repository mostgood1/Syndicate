# FINDINGS — Suggested (`sg`) graded over the weekend Sat 2026-10-17 / Sun 2026-10-18

Scheduled task `layer2-suggested-weekend-grade-1019`, run 2026-10-19 ~15:40–16:10Z (10:40–11:10 AM CDT). Lanes
`layer2-suggested-opps` and `fair-price-v2`. **Read-only**: no threshold, env, code or fleet change. Times below are
US Central unless marked Z.

## What every number rests on

| dataset | what | how |
|---|---|---|
| R. population | `opportunity_population`, 162,034 records for 10-17/18 (mlb, nfl, ncaaf, soccer, nhl; **no NBA parts exist for these dates**). `sg` is present on 162,034 of 162,034 records; `sg=true` on 369. | `score_ranking_backtest.py pull --source recorder`, via a scratchpad wrapper that only adds `sg`/`k` to each graded row and grades two sets |
| P. published | `clv_openings`, 62,198 records; 33,138 graded | same, `--source openings` |
| Paper book | `/api/ops/execution/ledger-summary` on the fleet (`127.0.0.1:10000`), read 15:4xZ | `days=5` minus `days=3` window: isolates the 10-17 and 10-18 dates |
| Close fairs | fleet quote logs `~/syndicate-prod/data/<sport>_source/tracking/book_quotes/`, through `scripts/fair_price_eval.py` (production `devig`), fleet repo `e88cd098` | per-book de-vig at each book's last pre-commence quote (≤ 6 h stale), median over books |

- **Suggested set:** the earliest `sg=true` sighting per identity per phase, which is the price the paper book takes. One side
  per line held without intervention (342 rows → 342 lines). Graded 342; ungraded 14 not_yet, 8 no_chip_match, 2 push, 2 other.
- **All set:** the earliest sighting per identity per phase over every opportunity-lane record. 71,093 graded of 101,145.
- **Flat 1 unit at the recorded price. Venue fees are NOT netted** (exchange rows are 60 of 339). 95% intervals are 2,000
  bootstrap resamples over GAMES.
- **Season phases are not pooled.** The headline is the four regular-season sports (NFL, NCAAF, NHL, soccer). MLB is
  postseason (3 suggested bets, 1 game). NBA is preseason until 10-20, and the recorder holds **0 NBA records** for these dates.
- NCAAF teams resolved from the primary tree's git-tracked registry (`SYNDICATE_NCAAF_SOURCE_ROOT`); 173 rows still
  `extra_team_unresolved` in All, 0 in Suggested.
- Context: since 10-16 22:32Z `single_book_fair` / `books_quoting_unknown` also block a row from Suggested, so this weekend
  is the first one graded under that rule as well as under the Shin fair (live 10-13 21:02Z).

## 1. Suggested vs everything priced (R, first sighting)

| set | bets | games | hit / break-even % | ROI [95% by game] | units |
|---|---|---|---|---|---|
| **Suggested, regular-season sports** | 339 | 105 | 51.3 / 48.3 | **+3.9% [-7.7, +15.4]** | +13.11 |
| All priced, regular-season sports | 69,924 | 154 | 40.7 / 46.8 | -17.3% [-21.0, -14.1] | -12,131.73 |
| Suggested, MLB (postseason) | 3 | 1 | 0 / 71.2 | -100% (n/a) | -3.00 |
| All priced, MLB (postseason) | 1,169 | 2 | 47.0 / 51.8 | -13.8% [-15.4, -11.9] | -160.94 |

By sport (Suggested vs All):

| sport (phase) | Suggested bets / games | Suggested ROI | All bets / games | All ROI |
|---|---|---|---|---|
| NFL (regular) | 80 / 12 | +3.4% [-22.9, +29.8] | 23,589 / 12 | -5.1% [-6.2, -4.1] |
| NCAAF (regular) | 147 / 51 | +3.3% [-11.8, +20.1] | 20,907 / 52 | -7.7% [-9.1, -6.3] |
| NHL (regular) | 63 / 16 | +20.7% [-0.7, +39.0] | 3,583 / 16 | -17.6% [-24.6, -7.9] |
| soccer (regular) | 49 / 26 | -15.4% [-50.8, +27.3] | 21,845 / 74 | -39.8% [-43.7, -35.0] |

Cells, regular-season sports only:

| cell | Suggested bets / games | Suggested ROI | All ROI (bets / games) |
|---|---|---|---|
| game lines | 232 / 91 | +1.0% [-12.5, +15.0] | -5.7% (27,123 / 154) |
| props | 107 / 28 | +10.1% [-8.3, +26.8] | -24.7% (42,801 / 141) |
| pregame | 133 / 63 | +2.0% [-19.2, +21.4] | -25.9% (33,397 / 154) |
| live | 206 / 75 | +5.1% [-8.6, +19.7] | -9.5% (36,527 / 153) |
| exchange-priced | 60 / 34 | +2.5% [-21.0, +25.8] (fees not netted) | -6.9% (6,649 / 121) |
| sportsbook | 279 / 96 | +4.2% [-10.0, +19.0] | -18.4% (63,275 / 154) |

Suggested sport × phase (all intervals span 0): NFL live +2.3% (73 / 12), NCAAF live +8.6% (108 / 44), NCAAF pregame
-11.3% (39 / 30), NHL pregame +19.7% (60 / 15), soccer pregame -21.8% (27 / 13), soccer live -7.4% (22 / 16).

Published (P): regular-season -11.7% [-15.1, -9.2] (32,562 / 154). Published rows whose key was Suggested: +1.8%
[-11.4, +14.8] (344 / 101). MLB published -14.1% [-19.5, -8.8] (576 / 2).

**Reading.** Suggested again sits about 20 points above the board (+3.9% vs -17.3%), on a bet list about 1/200th the
size. For the first time its point estimate is positive, but the interval spans 0 and it is one weekend of 105 games.
No cell's interval excludes 0. NHL pregame props (+19.7%, 15 games) carry most of the profit. Soccer is the one sport
negative on both weekends (-19.4% over 10-06..12, -15.4% here).

## 2. EV at the close: fair-price-v2's owed reading (pregame Suggested only)

Price taken vs the de-vigged consensus at the close. 130 of 134 pregame suggested bets have a close fair (62 games).

| close fair | EV at close [95% by game] | beat the close |
|---|---|---|
| **Shin (the board's fair since 10-13)** | **+1.45% [+0.25, +2.73]** | 81 / 130 |
| power | +0.64% [-0.74, +1.81] | 79 / 130 |
| multiplicative | +2.65% [+1.14, +4.47] | 85 / 130 |

By sport, Shin: NHL +1.45% [-0.02, +3.07] (60 / 15), NCAAF +0.67% [-0.75, +2.04] (37 / 28), soccer +3.17% [-1.0, +7.42]
(25 / 13), NFL +0.04% (7 / 5). Game lines +1.74% (67 / 44); props +1.21% (62 / 17).

- **Against the 10-13 backtest:** that backtest gave Shin +1.53% for EV ≥ 2 selections, valued at the POWER close by
  `selection_test`. On the same power basis this weekend reads +0.64% [-0.74, +1.81]. On a Shin close it reads +1.45%
  [+0.25, +2.73]. Either way the sign holds, the size matches within noise, and the Shin-close interval excludes 0. **The
  selection beats the close. It does not yet beat outcomes reliably.**
- **Engine read.** Board `ev` on these rows averages +3.51%, while a Shin fair rebuilt from the quote logs at the sighting
  gives +2.11% (124 rows). The gap sits in NCAAF (board +4.07 vs +0.80) and soccer (+2.89 vs +0.15). Props agree
  exactly (+3.43 / +3.45). About half of the edge the board sees on NCAAF and soccer game lines is not in the quote-log
  consensus at that moment. Lead: compare the board's per-row fair inputs with the logged books at the same instant
  (book set / fair anchor).

## 3. Paper book, 10-17 + 10-18 (fleet ledger-summary)

- **Settled: 759 orders, 384 W - 374 L - 1 P, P&L -$24.07 on $6,092.53 settled stake = ROI -0.4%.** 126 still pending.
  Source: the sum over `sim_view_roi.by_verdict`, `days=5` minus `days=3` (the 3-day window holds 0 settled).
- Caveat: `sim_view_roi` counts 885 orders for these dates, while `summary` counts 1,149 filled orders (staked $11,315 across
  paper/kalshi/novig/polymarket/prophetx). The endpoint gives no per-date P&L outside `sim_view_roi`. A bet planned on
  several slate dates is several rows. Only 23 of 39 novig and 1 of 14 prophetx orders on 10-18 had settled.
- By verdict (whole window, all settled orders): agrees +0.9% ($6,043 staked), unpriced (market fair) +8.3% ($920),
  disagrees (EV-conditioned) -22.7% ($148).
- The book stakes far more rows per game than the flat-unit Suggested grade, and sizes them, so it is a different
  instrument. Its -0.4% beside Suggested's +3.9% is consistent within noise.

## 4. Beside the earlier evidence

| reading | Suggested | board / all |
|---|---|---|
| 10-06..10-12 backtest (rule re-applied; 843 bets / 162 games) | -4.1% [-12.8, +7.5] | -16.8% |
| weekend 10-10/11, published EV ≥ 2 | +4.6% [-4.1, +14.0]; live +9.9%, exchange +9.6% | -10.0% |
| **weekend 10-17/18, recorded `sg` (339 bets / 105 games, regular season)** | **+3.9% [-7.7, +15.4]**; live +5.1%, exchange +2.5% | -17.3% |
| fair-price-v2 EV at close, 10-13 backtest → this weekend | Shin +1.53% → **+1.45% [+0.25, +2.73]** (Shin close), +0.64% (power close) | |

Three readings, three intervals that each span 0. The board-relative lift (+13 to +21 points) is consistent across all
three. Live and exchange, the strongest cells on 10-10/11, are no longer standouts (+5.1%, +2.5%).

## 5. Recommendation: KEEP 2 (no change), with soccer flagged

- **Keep `SYNDICATE_SUGGESTED_MIN_EV_PCT=2`.** It is the first reading graded on the real `sg` field and it agrees with the
  backtest. The flag cuts the board's loss by ~20 points, the selection beats the Shin close by +1.45% with an interval
  above 0, and the outcome ROI is positive but not significant. Raising the threshold would shrink a list that is already
  ~170 bets/day, without evidence that higher EV bands do better. On 10-10/11 the pregame bands were non-monotone (2–5 +1.7%, 5–10
  -4.1%). Live rose by band (+0.9 / +3.3 / +10.2%), but every one of those intervals spanned 0.
- **Do not restrict to cells yet.** No cell's interval excludes 0 on either weekend, and the 10-10/11 leaders (live,
  exchange) regressed toward the pool.
- **Soccer is the candidate exclusion if one is wanted.** It is negative on both graded weeks (-19.4% on 122 bets, then
  -15.4% on 49) while its EV at close is positive (+3.17%). That pattern fits a fair problem (the one-sided
  `book_margin_model` / three-way devig, lane fair-price-v2 H6) more than a threshold problem. **This is the USER's
  decision.**
- **What would change it:**
  - **raise:** a pooled 3-weekend grade where EV 2–3 is reliably below EV 3–5.26;
  - **restrict:** any cell's game-clustered interval excluding 0 on a second, independent weekend;
  - **lower or abandon:** EV at the Shin close turning ≤ 0 over another weekend. The selection would then no longer beat the
    market, and outcome ROI would be noise around a negative edge.
- Next reading: weekend 10-24/25, plus a pooled 10-17..10-25 grade (≈ 200+ games), which would be the first with a chance
  of an interval clear of 0.

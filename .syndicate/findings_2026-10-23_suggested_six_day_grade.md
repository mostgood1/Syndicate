# FINDINGS — Suggested (`sg`) graded over six days, Sat 10-17 → Thu 10-22, plus the NBA alt-ladder engine read

Session 9e18a0e7, 2026-10-23 (graded 10-22 evening, engine read 9–10 AM CT 10-23). Lane `layer2-suggested-opps`.
**Read-only**: no threshold, env, code or fleet change. Times are US Central unless marked Z.

## What every number rests on

- **Population:** the opportunity-population recorder, **384,888 records** for 10-17..10-22, all sports. It is read from
  the fleet data root (`/home/amyn/syndicate-prod/data/reports/intelligence/<population subdir>`) through a local
  reader that takes the place of `score_ranking_backtest.py pull`'s token-gated web reader. Parser, grader and settlers
  are the same (`bs.grade_population`, `MlbPropGrader`, `build_extra_settler`).
  - Scripts: `C:\tmp\edge-analyses\suggested-grade\suggested_grade.py` (grade) and `suggested_analyze.py` (bootstrap,
    splits, ladder view).
- **Suggested:** 1,088 `sg=true` records, 1,038 graded. **All:** 268,048 opportunity-lane records, 157,587 graded.
  - Both use the earliest sighting per identity per phase (the price the paper book takes).
  - Flat 1 unit at the recorded price. **Venue fees are NOT netted.**
  - 95% intervals: 2,000 bootstrap resamples over GAMES.
- **Season phases are not pooled.**
  - Headline sports (regular season): NFL, NCAAF, NHL, soccer, and NBA from 10-20. The recorder's first NBA records are
    at 10-19 1:06 AM CT.
  - MLB and WNBA are postseason and reported apart.
- Overlap with `findings_2026-10-19_suggested_weekend_grade.md`: 10-17/18 are in both. This grade adds 10-19..10-22,
  which brings NBA in for the first time.

## 1. Suggested vs everything priced

| set | bets / games | hit % | ROI [95% by game] | units |
|---|---|---|---|---|
| **Suggested, regular season** | 973 / 176 | 48.5 | **−0.8% [−7.9, +8.2]** | −7.32 |
| All priced, regular season | 147,309 / 270 | 44.2 | −12.5% [−15.4, −9.9] | −18,462.97 |
| **Suggested, ladders counted once** (§3) | 833 ladders / 176 | 51.0 | **+1.5% [−5.4, +8.6]** | +12.15 |

By sport (Suggested vs All):

| sport (phase) | Suggested bets / games | Suggested ROI | All ROI |
|---|---|---|---|
| NHL (regular) | 161 / 41 | **+12.7% [−1.9, +27.6]**, hit 61.5% | −16.3% |
| NFL (regular) | 94 / 14 | +9.0% [−14.5, +32.7] | −5.2% |
| NCAAF (regular) | 164 / 58 | +4.3% [−11.8, +19.7] | −7.7% |
| NBA (regular from 10-20) | 468 / 15 | −7.0% [−18.5, +4.8] | −6.2% |
| soccer (regular) | 86 / 48 | −12.5% [−44.2, +25.8] | −34.7% |
| MLB (postseason) | 7 / 2 | −48.3% | — |
| WNBA (postseason) | 58 / 3 | −7.2% | −16.9% |

Cells (Suggested, all sports, vs All):

| cell | Suggested | All |
|---|---|---|
| props | 490 bets, **+4.3% [−5.0, +14.0]** | −18.8% |
| game lines | 548 bets, −6.6% [−19.1, +6.9] | −5.7% |
| pregame | 286 bets, −0.5% [−16.5, +17.2] | −16.9% |
| live | 752 bets, −1.8% [−9.4, +6.2] | −7.8% |

Sport × kind (Suggested):
- **NHL props:** +14.0% [−0.0, +27.4] on 149 bets / 39 games. The lower bound sits at 0, the closest to a real signal in
  any cell. NHL game lines: −3.6% (12 bets).
- **NFL:** props +12.5% [−19.2, +42.1] (53 / 14); game lines +4.5% (41 / 13).
- **NCAAF game lines:** +5.0% [−10.3, +20.4] (163 / 58).
- **NBA:** game lines −13.5% [−37.5, +16.9] (205 / 15); props −1.9% [−17.6, +12.1] (263 / 15).
- **Soccer game lines:** −12.5% (86 / 48), hit 33.7%.

NBA by phase × kind (Suggested vs All):

| | Suggested | All |
|---|---|---|
| pregame props | −9.0% (25 / 11) | −6.8% |
| **pregame game lines** | **0 of 23, −23.00 u** (4 games) | −5.6% |
| live props | −1.2% (238 / 15) | −5.8% |
| live game lines | −2.6% (182 / 14) | −6.9% |

By date (Suggested, all sports): 10-17 +0.2%, 10-18 +5.9%, 10-19 +20.9%, **10-20 −14.3%** (the NBA opener),
10-21 +1.6%, 10-22 −8.3%.

**Reading.** Suggested again sits about 12 points above everything priced (−0.8% vs −12.5%), but its interval spans 0.
The edge is in props (+4.3%), led by NHL. Game lines are a wash. **23 bets account for −23.0 of NBA's −32.6 units**
(§4). The other 445 NBA Suggested bets are −2.2%.

## 2. Beside the earlier evidence

| reading | Suggested | all / board |
|---|---|---|
| 10-06..10-12 backtest (843 bets / 162 games) | −4.1% [−12.8, +7.5] | −16.8% |
| weekend 10-10/11, published EV ≥ 2 | +4.6% [−4.1, +14.0] | −10.0% |
| weekend 10-17/18, recorded `sg` (339 / 105) | +3.9% [−7.7, +15.4] | −17.3% |
| **10-17..10-22, recorded `sg` (973 / 176)** | **−0.8% [−7.9, +8.2]**; ladders once +1.5% [−5.4, +8.6] | −12.5% |

Four readings, four intervals spanning 0. The lift over the population (+12 to +21 points) holds in every one.

## 3. Ladders counted once (new measurement view)

Suggested flags each rung of an alternate ladder on its own merits. That is correct: every line is its own decision.
But one game's final score settles every rung on the same side together, so a five-rung ladder is one outcome graded
five times.

The ladder view treats every rung of one (game, phase, market without `_alt`, segment, player, side) as one bet at the
rungs' mean result:
- regular season: +1.5% [−5.4, +8.6] on 833 ladders / 176 games
- NBA: −4.9% (356)
- props: +3.9% (449)
- game lines: −1.3% (384)

From here on, report this view beside the per-bet view. It changes the instrument, not the selection.

## 4. NBA engine read — why the opening-night alt lines lost

The 23 bets:
- 22 on the 10-20 opener, across three games: Celtics @ Pistons, 76ers @ Knicks, Thunder @ Spurs.
- One first-quarter total on Nuggets @ Thunder, 10-22.
- Markets: `spreads_alt` (5) and `totals_alt` (18).
- Prices +190 to +476, plus two FanDuel overs at −205 / −192.
- Books quoting: 2–5.

Rebuilt from the fleet's NBA quote log (`nba_source/tracking/book_quotes/2026-10-20.jsonl.gz`, production
`consensus_fair_probability`, Shin) by `nba_alt_rebuild.py`:

1. **The fair has no bug.** The rebuilt sighting fair equals the board's `fp` on **23 of 23**.
   - The consensus rested on 2–5 books quoting both sides.
   - The price taken was the outlier book: Bovada on the spreads, DraftKings on the long tails, FanDuel on the short
     overs.
2. **The prices were taken 37–44 hours before the listed start.** All 22 opener rows were first sighted at 10-19
   1:06 AM CT. That is the recorder's first NBA regular-season snapshot.
   - Two different games (76ers @ Knicks, Thunder @ Spurs) carry IDENTICAL fairs on the same rungs (0.6887 / 0.6711 /
     0.3367), with identical FanDuel prices. Both had a 231.5 main total.
   - The books' opening alt ladders were templated by main line. They were not game-specific.
3. **The selection beat the close.**
   - EV at the close (each book's last quote ≤ 6 h before the listed start): **mean +5.6%, median +4.1%**, against
     +3.0% at the sighting. 14 of 23 were positive at the close.
   - Thunder @ Spurs moved against the overs (main 231.5 → 230.5; −6 to −7% each) and toward the unders (+25 to +30%).
4. **The outcomes swept.** Every game landed in the gap between the rungs taken:

   | game | final | rungs taken |
   |---|---|---|
   | Celtics @ Pistons | 234 total, Pistons by 8 | over 234.5 / under 207.5; Celtics −6.5 / Pistons −9.5 |
   | 76ers @ Knicks | 206 total | over 223.5 and up |
   | Thunder @ Spurs | 220 total | over 223.5 / under 218.5 |

   - At the close fairs the 23 bets expected **7.6 wins**.
   - The chance all five ladders miss is about **0.6% (1 in 170)**, treating a game's spread and total as independent.
5. **Are alt-ladder fairs biased on the tails? No, on what exists.** All NBA pregame `_alt` rows, first sighting,
   10-20..10-22 (16,754 rows / 16 games): rungs priced under 35% hit **+1.5 to +2.4 pts MORE** often than their fair.
   Every interval spans 0.
   - Live: 10,194 rows, the same picture.
   - Near the money: 35–50% hit +2.2 [+0.9, +3.6] and 50–65% hit −2.1 [−3.3, −0.8]. These are the two sides of the same
     rungs (unders landed), not a tail bias.
   - Other sports carry no `_alt` game rows in this population.
6. **The sim had no say.** On NBA pregame game lines the sim's edge over the fair (`me`) is under 0.5 pts on
   **8,421 of 9,066 totals rows (93%)** and on **all** spread (8,194) and moneyline (222) rows. These bets were priced
   on the market fair (`eb = market_fair`). The engine neither caused them nor could have caught them.
   - **Lead (engine bias, not a cause of these losses):** on main totals the sim leaned OVER in **15 of 16** games.
     9 of those 15 went under. One lean under, which went under.
   - A one-way lean in 15 of 16 is unlikely without a bias (p ≈ 0.0005 under a fair coin). Its cost is unproven: 6 of
     15 over, 16 games.
   - Re-read at ≥ 50 regular-season games: the sim's mean total vs the closing total vs the final.

**Verdict.** The opener loss is correlated variance on four ladders, not a mispriced fair and not the engine. The bets
were sound by the selection's own test: they beat the close. The book-vs-consensus price gaps 40 hours out came from
templated ladders. The close mostly confirmed them.

Open question, not answered here: whether flagging **every** rung of a templated early ladder should be stake-capped in
the paper book. For example, a per-ladder stake that does not grow with the number of rungs. That is a sizing choice for
the user. It is not a withhold, and no market is excluded.

## 5. Recommendation: KEEP 2 (no change). The decision stays the user's.

- **Keep `SYNDICATE_SUGGESTED_MIN_EV_PCT=2`.**
  - Nothing here says a higher bar would do better. The NBA opener rungs were EV 2.0–5.1%, and they beat the close.
  - No cell's interval excludes 0, NHL props included.
- **Soccer** is negative on all three graded windows (−19.4%, −15.4%, −12.5%). It remains the fair-price question
  (`fair-price-v2` H6, scored offline from 10-30), not a threshold question. **The user decides.**
- **What would change it:** the same criteria as `findings_2026-10-19_suggested_weekend_grade.md` §5.
  - **raise:** EV 2–3 reliably below EV 3–5.26 over a pooled multi-weekend grade.
  - **restrict:** a cell clear of 0 on a second, independent window. NHL props are the candidate to watch.
  - **lower or abandon:** EV at the Shin close ≤ 0.
- **Next reading:** Mon 10-26 10:00 AM CT, scheduled task `layer2-suggested-grade-1026`.
  - The weekend 10-24/25 alone, plus a pooled 10-17..10-25 grade.
  - Both the per-bet and ladder views.
  - EV at the Shin close for pregame Suggested.

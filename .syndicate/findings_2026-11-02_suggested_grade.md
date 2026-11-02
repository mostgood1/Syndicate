# FINDINGS — Suggested (`sg`) graded: weekend Sat 10-31 / Sun 11-01, pooled Sat 10-17 → Sun 11-01, and the third window 10-26 → 11-01

Run by the scheduled task `layer2-suggested-grade-1102` on 2026-11-02, 10:01–10:55 AM CST (Central is UTC−6 from 11-01).
Session 2486a60b, lane `layer2-suggested-grade-1102`. The reading was requested by the user on 10-27 in session 9e18a0e7.
**Read-only**: no threshold, env, code or fleet change, no restart, no deploy and no odds fetch. Times are US Central
throughout.

The user decided on 10-26 to keep 2% and to cap paper stake per alt ladder. §8 sets this reading against the 10-26 §7
criteria. The decision stays with the user.

## What every number rests on

- **Population:** the opportunity-population recorder on the fleet data root
  (`/home/amyn/syndicate-prod/data/reports/intelligence/opportunity_population/`), read by the fleet checkout at
  `b958db63`.
  - Weekend: 218,519 records (recorder files 10-31..11-01).
  - Third window: 658,904 records (10-26..11-01).
  - Pooled: 1,387,319 records (10-17..11-01).
- **Scripts:** the 10-26 scripts in `C:\tmp\edge-analyses\suggested-grade\`, unchanged: `suggested_grade.py`,
  `g1026_analyze.py`, `g1026_ev_close.py`, `g1026_evband_diff.py`, `g1026_nba_lean.py` and `g1026_notyet.py`.
  - They ran under the fleet venv (`/home/amyn/.venvs/syndicate/bin/python`) at `nice -n 19`. System `python3` has no
    numpy, as on 10-26.
  - The outputs are in `out_1031_1101\`, `out_1026_1101\` and `out_1017_1101\`, with text copies `a_*.txt`, `ev_*.txt`,
    `band_1017_1101.txt` and `lean_1017_1101.txt`.
- **Three additions, each a copy of a 10-26 script with one change, saved beside it:**
  - `g1102_ev_close_safe.py`: on the pooled rows, `fair_price_eval.calibration` overflowed (`math.exp`) and crashed the
    run. That calibration fit is a side diagnostic; EV at the close does not use it. The copy returns "no fit" when the
    fit diverges (5 times). Every EV-at-close number is computed exactly as before.
  - `g1102_ev_close_nopin.py`: drops Pinnacle quotes before the close fair is built. This is a robustness check only (§4).
  - `g1102_evc_split.py`: EV at the close by sport-excluded and by date slice, from the rows the evaluator wrote.
  - The alt-ladder reading (§7) is `g1102_ladder_cap.py` and `g1102_ladder_builds.py`.
- **Suggested:** the earliest `sg=true` sighting per identity per phase.
  - Weekend: 909 records, 884 graded (16 not_yet, 6 push, 3 DNP void). Regular season: **860 bets / 115 games**.
  - Third window: 3,009 records, 2,952 graded. Regular season: **2,883 / 223**.
  - Pooled: 5,598 records, 5,505 graded (23 not_yet, 23 push, 18 DNP void, 4 NHL name). Regular season: **5,353 / 551**.
- **All priced:** the earliest sighting per identity per phase over every opportunity-lane record.
  - Weekend: 143,215 records, 109,572 graded. Regular season: 106,821 / 173.
  - Pooled: 982,217 records, 642,525 graded. Regular season: 617,279 / 764.
- **`not_yet` is NOT late Sunday games.** Every Suggested `not_yet` row on the weekend is a game that kicks off 11-02 or
  later: soccer 11-02 ×6, NFL 11-02 ×1 (Monday Night Football, outside the window by design), soccer 11-03 and 11-05,
  and NCAAF 11-05..11-07 ×7.
  - All priced: 9,919 rows, all kicking off 11-02..11-09.
  - Nothing that kicked off inside the window is ungraded as `not_yet`.
- **Method:** flat 1 unit at the recorded price. **Venue fees are NOT netted.** 95% intervals: 2,000 bootstrap resamples
  over GAMES.
- **Season phases are never pooled.**
  - Regular season: NBA (every row dated 10-20 or later; 0 earlier), NHL, NFL, NCAAF and soccer.
  - Postseason, reported apart: MLB (the World Series) and WNBA.
  - The weekend recorder files carry **no MLB records at all**.
  - NCAAB has no rows in any window.
- **The windows overlap by construction,** as on 10-26.
  - A run reads only its own recorder files, so the pooled run's earliest sighting of a weekend game can come from an
    earlier file than the weekend run's.
  - That matters for EV at the close (§4): weekend soccer sighted from the weekend files is +2.24% at the close (16
    bets). The same games' earliest sightings in the pooled run are −4.40% (38).
- **Reproduction check:** the pooled run's 10-17..10-25 slice reproduces 10-26's EV at the Shin close: +1.44%
  [+0.54, +2.40] (460 / 192), against +1.51% [+0.63, +2.44] (457 / 191).

## 1. Headline: Suggested vs everything priced (regular season)

| window | set | bets (ladders) / games | hit % | ROI [95% by game] | units |
|---|---|---|---|---|---|
| **weekend 10-31/11-01** | **Suggested, per bet** | 860 / 115 | 47.9 | **+0.2% [−11.6, +11.2]** | +1.68 |
| | **Suggested, ladders once** | 676 / 115 | 47.9 | **−1.8% [−9.5, +5.9]** | −12.01 |
| | All priced, per bet | 106,821 / 173 | 43.3 | −14.4% [−18.1, −11.6] | −15,383.97 |
| | All priced, ladders once | 30,717 / 173 | 42.4 | −21.9% [−26.0, −17.8] | −6,716.72 |
| **third window 10-26..11-01** | **Suggested, per bet** | 2,883 / 223 | 49.4 | **+1.7% [−3.8, +7.2]** | +48.96 |
| | **Suggested, ladders once** | 2,213 / 223 | 51.1 | **+2.9% [−1.8, +7.8]** | +63.43 |
| | All priced, per bet | 301,928 / 290 | 45.3 | −11.5% [−13.5, −9.6] | −34,685.73 |
| | All priced, ladders once | 71,128 / 290 | 46.5 | −19.7% [−22.6, −16.9] | −14,019.15 |
| **pooled 10-17..11-01** | **Suggested, per bet** | 5,353 / 551 | 48.1 | **−1.1% [−5.2, +3.0]** | −59.04 |
| | **Suggested, ladders once** | 4,216 / 551 | 50.7 | **+1.8% [−1.6, +5.1]** | +75.85 |
| | All priced, per bet | 617,279 / 764 | 44.8 | −12.6% [−13.9, −11.3] | −77,530.31 |
| | All priced, ladders once | 158,149 / 764 | 45.3 | −20.4% [−22.2, −18.6] | −32,277.63 |

Postseason, reported apart:
- **MLB.** Weekend: no records. Third window: Suggested 14 / 3 games, −8.5% (13 ladders −17.1%); all priced 2,063 / 3,
  −9.3%. Pooled: 24 / 7, −11.2% [−58.2, +26.1]; all priced 5,480 / 8, −10.7%.
- **WNBA.** Weekend: Suggested 24 / 1 game, +120.2% (+28.84 u); all priced 2,751 / 1, −17.1%. Pooled: 128 / 7, +25.6%
  [−19.4, +73.2], or 94 ladders +31.7%; all priced 19,766 / 7, −15.3%.

**Reading.**
- The weekend is flat (+0.2% per bet), against −10.1% on the previous weekend.
- **The third window is the best Suggested reading so far:** +1.7% per bet and +2.9% ladders once.
- Pooled, the gap over everything priced is about 11.5 points per bet and about 22 points per ladder.
- Every outcome interval spans 0, as before.
- By date (pooled run, Suggested, regular season):
  - 10-17 +1.5% (238 / 85), 10-18 +5.9% (109 / 22), 10-19 +32.7% (27 / 10)
  - 10-20 −14.3% (179 / 23), 10-21 +4.6% (266 / 16), 10-22 −8.9% (155 / 20)
  - 10-23 −1.1% (539 / 23), 10-24 −1.3% (508 / 83), 10-25 −18.0% (446 / 45)
  - 10-26 −3.3% (416 / 14), 10-27 −1.8% (185 / 17), 10-28 +3.7% (521 / 31)
  - 10-29 +2.0% (204 / 19), 10-30 +3.4% (645 / 19), 10-31 +1.7% (547 / 84), 11-01 +1.3% (368 / 40)
- Pooled ladder shape: 4,216 ladders from 5,353 bets, 533 of them multi-rung, the largest with 21 rungs.

## 2. By sport (regular season, Suggested vs all priced)

| sport | weekend: per bet | weekend: ladders once | weekend: All | pooled: per bet | pooled: ladders once | pooled: All |
|---|---|---|---|---|---|---|
| NBA | 541 / 11, +1.6% [−12.5, +17.2] | 377, −1.5% [−7.8, +4.7] | 46,599 / 11, −7.6% | 3,849 / 91, −2.1% [−7.0, +3.2] | 2,827, +1.4% [−2.7, +5.7] | 349,952 / 92, −6.5% |
| NFL | 127 / 12, −5.1% [−24.8, +14.8] | 124, −5.6% | 18,286 / 12, −4.9% | 340 / 40, −2.7% [−14.7, +10.3] | 324, −2.4% [−13.7, +10.2] | 68,735 / 40, −5.5% |
| NCAAF | 77 / 37, +3.2% [−27.0, +30.5] | 75, +3.2% | 14,856 / 47, −8.9% | 406 / 153, +8.1% [−2.6, +18.9] | 390, +8.7% [−1.8, +19.5] | 72,703 / 164, −10.6% |
| NHL | 38 / 13, +0.2% [−32.9, +44.4] | 38, +0.2% | 3,474 / 15, −15.4% | 405 / 104, +5.9% [−4.2, +16.3] | 405, +5.9% | 27,528 / 111, −13.8% |
| soccer | 77 / 42, −4.1% [−43.2, +46.7] | 62, −3.3% | 23,606 / 88, −38.5% | 353 / 163, −7.2% [−24.4, +11.9] | 270, −4.9% [−20.9, +12.6] | 98,361 / 357, −40.1% |

Third window (10-26..11-01), per bet: NBA +1.2% [−5.1, +7.7] (2,296 / 49), ladders once +3.0%; NFL +2.9% (147 / 14); NCAAF
+9.1% [−10.1, +29.5] (128 / 50); NHL −1.0% [−19.0, +16.9] (162 / 44); soccer +5.2% [−24.1, +36.5] (150 / 66).

## 3. Props vs game lines, pregame vs live (regular season)

| cell | weekend: per bet | weekend: ladders once | weekend: All | pooled: per bet | pooled: ladders once | pooled: All |
|---|---|---|---|---|---|---|
| props | 403 / 38, −4.6% [−12.8, +4.6] | 389, −4.5% | 55,830 / 147, −20.1% | 2,706 / 236, **+3.1% [−1.6, +7.8]** | 2,576, +3.4% [−1.0, +8.0] | 312,576 / 644, −17.5% |
| game lines | 457 / 105, +4.4% [−14.0, +21.2] | 287, +1.9% | 50,991 / 173, −8.1% | 2,647 / 479, −5.4% [−11.6, +1.0] | 1,640, −0.7% [−6.0, +5.0] | 304,703 / 764, −7.5% |
| pregame | 122 / 61, **−24.0% [−46.0, +0.8]** | 112, −18.8% [−41.1, +6.1] | 56,208 / 172, −17.6% | 958 / 370, +1.6% [−6.5, +9.8] | 869, +4.6% [−3.3, +12.5] | 331,592 / 764, −15.9% |
| live | 738 / 94, +4.2% [−9.0, +15.9] | 564, +1.6% | 50,613 / 172, −10.9% | 4,395 / 418, −1.7% [−6.2, +2.8] | 3,347, +1.1% [−2.5, +4.8] | 285,687 / 759, −8.7% |

Third window: props +3.4% [−2.8, +9.8] (1,515 / 109); game lines −0.2% [−9.2, +8.7] (1,368 / 192), ladders once +1.4%;
pregame +2.5% (446 / 164); live +1.5% (2,437 / 165), ladders once +3.0%.

Cells with an interval excluding 0, in any window:
- **NCAAF live, pooled:** **+13.1% [+1.1, +25.6]** per bet (276 / 128), **+14.7% [+2.5, +27.1]** ladders once. On the
  third window: +12.5% [−8.8, +33.2] (75 / 39), ladders once +13.3% [−8.2, +33.8]. **That spans 0.**
- **NFL pregame, weekend:** −46.0% [−79.1, −15.1] (21 / 10). Pooled NFL pregame is not separated out, and NFL Suggested is
  −2.7% pooled.
- **Weekend pregame, EV 2–3:** −33.8% [−60.1, −4.2] (48 / 37). Weekend pregame EV 3–5.26: −17.5% [−50.3, +20.6].
- NCAAF props: 3 to 6 bets (−38% to −69%), too few to read.
- **No cell's interval excludes 0 on the third window** except NCAAF props (3 bets / 2 games).

## 4. EV at the Shin close, pregame Suggested (10-19 §2 method, unchanged)

| window | EV at Shin close [95% by game] | n / games (graded) | beat close | power / mult close |
|---|---|---|---|---|
| **weekend 10-31/11-01** | **+1.29% [−0.03, +2.67]** | 110 / 56 (122 / 61) | 65 / 110 | +0.06% / +3.26% |
| **third window 10-26..11-01** | **−0.61% [−1.49, +0.24]**, median +0.28 | 374 / 156 (446 / 164) | 192 / 374 | −1.49% [−2.54, −0.54] / +0.68% |
| **pooled 10-17..11-01** | **+0.45% [−0.20, +1.07]**, median +0.62 | 839 / 352 (958 / 370) | 457 / 839 | −0.38% / — |
| pooled, 10-17..10-25 slice | +1.44% [+0.54, +2.40] | 460 / 192 | | |
| pooled, 10-26..10-30 slice | −0.78% [−1.91, +0.35] | 220 / 81 | | |
| pooled, 10-31..11-01 slice | −0.69% [−2.10, +0.66] | 159 / 79 | | |

**By sport, third window (Shin):**
- **soccer −4.86% [−7.30, −2.44]** (61 / 34), beat the close 18 / 61
- NHL −0.89% [−1.94, +0.21] (146 / 43); NHL props −0.94% [−2.01, +0.17] (142 / 43)
- NBA +0.94% [−0.97, +2.55] (103 / 41)
- NCAAF +1.86% [+0.40, +3.05] (39 / 28)
- NFL +1.20% [−1.08, +3.56] (25 / 10)

**By kind, third window:** game lines −2.19% [−3.71, −0.71] (132 / 84); props +0.25% [−0.75, +1.17] (242 / 90).

**Leave-one-sport-out, third window:**
- Without soccer: **+0.22% [−0.64, +1.02]** (313 / 122).
- Without NHL: −0.43%. Without NBA: −1.19%.
- Soccer by slice: 10-26..10-30 −5.73% [−8.04, −3.05] (22 / 14); 10-31..11-01 −4.41% [−8.31, −0.77] (37 / 19).
- Pooled without soccer: +0.69% [+0.07, +1.35] (696 / 270).

**By sport, pooled (Shin):** NBA +2.29% [+0.69, +3.78] (187 / 64); NCAAF +1.04%; NFL +1.03%; NHL −0.32% [−0.97, +0.32]
(351 / 98); soccer −0.69% [−2.81, +1.45] (143 / 82).

**Weekend by sport:** NBA +1.23% (24 / 9), NCAAF +2.79% [+1.02, +4.18] (19 / 15), NFL +2.07% (18 / 9), NHL −0.42% (33 / 13),
soccer +2.24% (16 / 10). By kind: game lines +1.86% [+0.13, +3.49] (47 / 33); props +0.86% (63 / 30).

**Pinnacle is EXONERATED as the cause of the drop.**
- Pinnacle entered the NBA, NFL and soccer game-line `book_quotes` on 10-25 at 11:29 AM CT (`deploys.md` 2026-10-25 16:29Z).
  A sharper book in the median-over-books close could lower EV at the close with no change in selection.
- Dropping every Pinnacle quote (189 of 404 quote groups) moves the third window from −0.61% to **−0.56% [−1.45, +0.29]**,
  soccer from −4.86% to −4.72%, and game lines from −2.19% to −2.13%.

**Engine read.**
- The board's `ev` at the sighting averages +3.28% on the third window. A Shin fair rebuilt from the quote logs at the
  same instant gives +2.29% (360 rows).
- The gap is again in game lines (board +3.21% against rebuilt +0.30%, 119 rows) and soccer (rebuilt −2.68% on the
  weekend, 13 rows).
- Props agree (+3.31% against +3.27%).
- Same pattern as 10-26 §4. It is the `fair-price-v2` H6 question, not a threshold question.

**Lead, not tested:** soccer sighted early loses the close, and soccer sighted near kickoff does not.
- The weekend run (earliest sighting within the 10-31/11-01 files) puts weekend soccer at +2.24% at the close (16 bets).
- The pooled run (earliest sighting anywhere from 10-17) puts the same slate's soccer at −4.40% (38 bets).
- The difference is the earlier sightings, of matches sighted one or more days ahead.

## 5. NHL props on the third window (the restrict criterion)

| window | NHL props, Suggested | EV at Shin close |
|---|---|---|
| pooled 10-17..10-25 (10-26 reading) | +13.8% [+0.9, +25.5] (220 / 57) | +0.10% (204 / 55) |
| **third window 10-26..11-01** | **−4.5% [−22.3, +13.4]** (147 / 44), all priced −12.5% | **−0.94% [−2.01, +0.17]** (142 / 43) |
| weekend 10-31/11-01 | −5.9% [−47.1, +42.8] (34 / 13) | −0.33% (32 / 13) |
| pooled 10-17..11-01 | +5.9% [−4.3, +16.4] (367 / 101) | NHL −0.32% (351 / 98) |

**NHL props do not clear 0 on the third window: the point estimate turned negative.**
- The 10-26 reading had already noted that the outcome edge had no closing-line backing (+0.10%).
- On the new games the close is −0.94% and the outcome −4.5%.
- The restrict criterion is **NOT MET**.

## 6. NBA re-reads

**Sim main-total lean.** The 10-23 rule, unchanged: per game, the first pregame `totals` / `full` / over row with `me`.

| games | leaned over / under / flat | went over / under | lean right | two-sided sign test |
|---|---|---|---|---|
| 10-20..10-22 (16) | 15 / 1 / 0 | 6 / 10 | 7 of 16 | p = 0.0005 |
| **10-23..11-01 (76)** | **37 / 38 / 1** | 34 / 42 | **38 of 75** | **p = 1.0** |
| pooled 10-20..11-01 (92) | 52 / 39 / 1 | 40 / 52 | 45 of 91 | p = 0.21 |

- The re-read threshold was 50 regular-season games. **There are now 92.**
- **The one-way over lean of 10-20..10-22 did not persist.** From 10-23 the sim split 37 over / 38 under (76 games). That is
  a fair coin.
- The lean was right in 38 of 75 games from 10-23, and 45 of 91 pooled: no information in either direction.
- Magnitude (`me` on the over row): mean −0.01 pts, median +0.09, range −1.81..+1.06.
- The 10-22 injury-report changes (`36eb357b`, `21b4bdb0`) remain the untested candidate for the shift. The shift itself
  is now settled: the lean is gone.

**Lead 1: NBA pregame game-line rows with a close fair won 0 of 28 against 9.69 expected (6 games).**

| games | rows with a close fair / games | won | expected at the close fair | z (ignores within-ladder correlation) |
|---|---|---|---|---|
| ≤ 10-25 (the 10-26 lead) | 28 / 6 | 0 | 9.69 | |
| **10-26..11-01 (new)** | **21 / 13** | **6** | **8.11** | −1.05 |
| pooled | 49 / 19 | 6 | 17.80 | −3.76 |

- **Does not replicate on the new games.** On 13 new games the shortfall is 2.1 wins and inside noise. The pooled
  shortfall is the first 6 games.
- 48 of the 49 rows are alt rungs.
- Coverage is the real gap: only 1 of 24 NBA pregame MAIN game-line rows after 10-25 has a close fair. 33 of 54 rows have
  none.
- Still below the ≥ 20-game re-read bar (19 pooled). Keep it as a lead.

**Lead 2: pooled pregame CLV and outcome point opposite ways by kind.**

| slice | game lines: EV at close / flat ROI | props: EV at close / flat ROI |
|---|---|---|
| ≤ 10-25 | +3.10% / −20.0% (186) | +0.31% / +12.5% (274) |
| **10-26..11-01** | **−2.50% / +6.0%** (137) | **+0.25% / −3.9%** (242) |
| pooled | +0.72% / −9.0% (323) | +0.28% / +4.8% (516) |

- The opposition holds within each slice, **but both signs flipped** on the new games.
- So outcome is not tracking CLV by kind at these sample sizes. Read it as noise, not a mechanism.
- CLV, not short-run outcome, is what the lower/abandon criterion tests.

## 7. Alt-ladder stake cap (ride-along reading): the cap is NOT holding in the ledger

**Data.** The execution ledger read under refresh-worker's state env, through `full_history_orders()`.
- The task named `execution_ledger._load()`. That is the live document, capped at **3,000 rows**, and it no longer
  holds the window: main-book rows for 10-26 and 10-27 are 470 → 0 and 417 → 0 in the document, and 11-01 is 343 → 183.
- `full_history_orders()` is `_load()` plus the disk archive the record cap moves trimmed rows into.
- Filters: main book = mode `paper`, venue `paper`, status not failed/cancelled/rejected. Ladder key =
  `pipeline/portfolio_commit.py:_alt_ladder_key` (the fleet's own). Rung = one `position_key`, staked at
  `fill_stake_dollars` (else requested), max over duplicates. Window: slate dates 10-27..11-01.

**Result.** 2,026 main-book rows, 1,460 ladders, **210 multi-rung ladders. 0 total within their largest rung; all 210
exceed it.**
- By first slate date: 10-27 64, 10-28 39, 10-29 42, 10-30 25, 10-31 13, 11-01 27.
- The largest ladder has 12 rungs. Ratios run up to 6.9× (an NBA spread ladder on 10-30: 7 rungs, $7.01 against a $1.01
  largest rung).

**Why. Most of it is one mechanism, plus two by design.**
- **107 pregame-only, 53 mixed, 50 live-only.** A rung placed at or after commence comes from an in-play plan, which
  `cap_alt_ladder_stakes` does not touch by design ("MAIN PAPER PLAN ONLY ... the live plans are built by their own
  `commit_portfolio` calls").
- Pregame rungs only (128 multi-rung pregame ladders): **111 exceed only ACROSS builds.** Each build's own rungs are
  within the cap, but the ladder accumulates over builds. **11 exceed within a single build**, the min-stake floor at
  $1.00, and **6** exceed both ways.
- **Mechanism (hypothesis, consistent with every reading here, not verified per build):**
  - The cap counts held orders from `_load()` (fleet `pipeline/portfolio_commit.py` lines 2371–2385, `held_source=ledger`), which is the
    3,000-row document.
  - The record cap moves the oldest rows to the archive. On this read, 2,571 of the document's 3,000 rows were venue or live rows. So the same
    day's earlier main-book rows can leave the document within hours.
  - So later builds see few or no held rungs, and the cap degrades to a per-build cap.
  - The cap does fire and scale: its log on 11-02 shows `staked_before=20.98 staked_after=6.21 held_rungs=1`. It just
    misses most of what is already held.
- The fix would be reading held orders through `full_history_orders()` (or the archive months the slate touches). **Not
  made: this run is read-only.**
- The flat-unit grades above are unaffected. No paper-book dollars are quoted here.

## 8. Beside the earlier readings

| reading | Suggested per bet | ladders once | all priced |
|---|---|---|---|
| 10-06..10-12 backtest (843 / 162) | −4.1% [−12.8, +7.5] | — | −16.8% |
| weekend 10-10/11, published EV ≥ 2 | +4.6% [−4.1, +14.0] | — | −10.0% |
| 10-19: weekend 10-17/18 (339 / 105) | +3.9% [−7.7, +15.4] | — | −17.3% |
| 10-23: 10-17..10-22 (973 / 176) | −0.8% [−7.9, +8.2] | +1.5% [−5.4, +8.6] | −12.5% |
| 10-26: weekend 10-24/25 (906 / 119) | −10.1% [−23.1, +2.3] | −2.2% [−12.4, +7.2] | −14.2% |
| 10-26: pooled 10-17..10-25 (2,462 / 326) | −4.2% [−10.7, +1.8] | +0.8% [−4.0, +5.7] | −13.5% |
| **11-02: weekend 10-31/11-01 (860 / 115)** | **+0.2% [−11.6, +11.2]** | **−1.8% [−9.5, +5.9]** | −14.4% |
| **11-02: third window 10-26..11-01 (2,883 / 223)** | **+1.7% [−3.8, +7.2]** | **+2.9% [−1.8, +7.8]** | −11.5% |
| **11-02: pooled 10-17..11-01 (5,353 / 551)** | **−1.1% [−5.2, +3.0]** | **+1.8% [−1.6, +5.1]** | −12.6% |

EV at the close, pregame Suggested:

| window | EV at close [95% by game] | n / games |
|---|---|---|
| 10-13 backtest (POWER close) | +1.53% | |
| 10-19: 10-17/18, Shin | +1.45% [+0.25, +2.73] | 130 / 62 |
| 10-26: 10-24/25, Shin | +1.99% [−0.12, +4.03] | 127 / 52 |
| 10-26: pooled 10-17..10-25, Shin | +1.51% [+0.63, +2.44] | 457 / 191 |
| **11-02: weekend 10-31/11-01, Shin** | **+1.29% [−0.03, +2.67]** | 110 / 56 |
| **11-02: third window 10-26..11-01, Shin** | **−0.61% [−1.49, +0.24]**; without soccer +0.22% [−0.64, +1.02] | 374 / 156 |
| **11-02: pooled 10-17..11-01, Shin** | **+0.45% [−0.20, +1.07]**; without soccer +0.69% [+0.07, +1.35] | 839 / 352 |

The lift over everything priced held in every reading: +4 to +21 points per bet. The three new readings are +11.5 to +14.6 per bet and +20.1 to +22.6 ladders once.

## 9. Against the 10-26 §7 criteria. Recommendation: KEEP 2%, with one criterion tripped on its point estimate

- **Raise** (a pooled difference with its interval above 0): **NOT MET; it reversed.**
  - EV 3–5.26 minus EV 2–3, pooled: **−1.1 pts [−7.3, +5.7]** per bet (551 games), −2.1 [−8.5, +4.9] ladders once.
  - Pregame +4.9 [−11.2, +20.2] (370 games); live −2.4 [−9.2, +4.7] (418 games).
  - The 10-26 pooled difference was +2.6. The higher band no longer leads.
- **Restrict to cells** (a cell clear of 0 on the third window, excluding 10-17..10-25): **NOT MET.**
  - NHL props −4.5% [−22.3, +13.4] (147 / 44). The 10-26 candidate turned negative, with no CLV behind it either way.
  - NCAAF live clears 0 pooled (+13.1% [+1.1, +25.6]; +14.7% [+2.5, +27.1] ladders once), but the third window spans 0:
    +12.5% [−8.8, +33.2] (75 / 39). It is the cell to watch now. Its pregame NCAAF close is the strongest sport at
    +1.86% [+0.40, +3.05].
- **Lower or abandon** (EV at the Shin close ≤ 0 on a new window): **TRIPPED ON THE POINT ESTIMATE, not on the interval.**
  - Third window −0.61% [−1.49, +0.24] (374 / 156). Its interval spans 0. The weekend alone is +1.29% [−0.03, +2.67].
  - **It is concentrated in one sport:** soccer −4.86% [−7.30, −2.44] (61 / 34). Without soccer the window is +0.22%
    [−0.64, +1.02], and pooled without soccer is +0.69% [+0.07, +1.35].
  - It is not Pinnacle (−0.56% without it).
  - Lowering or abandoning 2% is a market-wide change, and the evidence points at one sport's fair price. It is the soccer
    fair already flagged on 10-26 (`fair-price-v2` H6, board fair above the rebuilt fair), and early sightings look worse.
  - Every line stays its own decision. **No sport or market is recommended for removal.**
- **Recommendation: keep 2%.**
  - The outcome evidence is the best so far: third window +1.7% per bet and +2.9% ladders once, against −11.5% for
    everything priced.
  - The raise test reversed, and no cell qualifies for restriction.
  - The one tripped criterion is driven by soccer's close fair, which is a fair-price question.
  - **The selection's closing-line edge is weaker than on 10-26 and is no longer clear of 0 pooled** (+0.45% against
    +1.51%). The user should weigh that.
- **What would change it:**
  - **Lower or abandon:** EV at the Shin close ≤ 0 with its interval below 0 on the next window, or ≤ 0 *without soccer*.
  - **Raise:** a pooled EV 3–5.26 minus EV 2–3 difference with its interval above 0.
  - **Restrict:** NCAAF live (or any cell) clear of 0 on a window excluding 10-17..11-01.
- **Separate from the threshold, owed to the alt-ladder cap's owner:** the cap does not hold across builds (§7). Under
  the user's 10-26 decision, the paper book still stakes each ladder at a multiple of one rung: 210 of 210 multi-rung
  ladders, 10-27..11-01. The likely fix is the held-orders read. Nothing was changed here.

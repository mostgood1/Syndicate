# FINDINGS — Suggested (`sg`) graded: weekend Sat 10-24 / Sun 10-25, and pooled Sat 10-17 → Sun 10-25

Run by hand on 2026-10-26, 10:14–10:33 AM CT. The scheduled task `layer2-suggested-grade-1026` (10:00 AM CT) did not
fire. Run by a sub-agent of session 9e18a0e7, lane `layer2-suggested-opps`. **Read-only**: no threshold, env, code or
fleet change, and no odds fetch. Times are US Central (CDT) throughout.

The threshold question is **already decided by the user** (10-26, ~8:05 AM CT): *"keep 2%, and cap paper stake per alt
ladder"*. §7 sets this grade against the findings 10-23 §5 criteria as support or not for that decision. It does not
reopen the decision.

## What every number rests on

- **Population:** the opportunity-population recorder, read from the fleet data root
  (`/home/amyn/syndicate-prod/data/reports/intelligence/opportunity_population/`). The weekend run read 233,585 records
  (recorder files 10-24..10-25). The pooled run read 728,415 records (files 10-17..10-25).
  - Grader and settlers: the fleet checkout at `6dd8a536`, through the shipped `suggested_grade.py` (local reader,
    `bs.grade_population`, `MlbPropGrader`, `build_extra_settler`). It runs under the fleet venv python; system
    `python3` has no numpy.
  - The shipped `suggested_analyze.py` reproduces the headlines below exactly. The extensions (All-priced ladder view,
    cells limited to the regular season, EV-band difference, EV at the close, NBA lean, `not_yet` census) are
    `g1026_*.py`, saved beside it in `C:\tmp\edge-analyses\suggested-grade\`. The outputs are in `out_1024_1025\` and
    `out_1017_1025\`.
- **Suggested:** the earliest `sg=true` sighting per identity per phase.
  - Weekend: 945 records, 922 graded (8 not_yet, 8 DNP void, 6 push). Regular season: **906 bets / 119 games**.
  - Pooled: 2,589 records, 2,545 graded (9 not_yet, 11 DNP void, 9 push, 4 other). Regular season: **2,462 / 326**.
- **All priced:** the earliest sighting per identity per phase over every opportunity-lane record.
  - Weekend: 146,292 records, 112,204 graded. Regular season: 108,763 / 178.
  - Pooled: 499,106 records, 329,109 graded. Regular season: 314,687 / 476.
- **`not_yet` is NOT late 10-25 games.** Every `not_yet` row is a game that kicks off 10-26 or later: future slates the
  recorder already carries.
  - Suggested, weekend: 8 (NCAAF 10-31 ×6, soccer 10-26 ×1, soccer 10-31 ×1).
  - Suggested, pooled: 9 (the same 8, plus NFL 11-01 ×1).
  - All priced: 10,166 weekend and 11,404 pooled. These are NCAAF 10-27..10-31, NFL 10-26..11-02 and soccer
    10-26..11-08.
  - Nothing that kicked off inside either window was left ungraded as `not_yet`. One pooled Suggested row is
    `game_not_final`.
- **Method:** flat 1 unit at the recorded price. **Venue fees are NOT netted.** 95% intervals: 2,000 bootstrap resamples
  over GAMES.
- **Season phases are never pooled.**
  - Regular season: NFL, NCAAF, NHL, soccer and NBA. Every NBA row is dated 10-20 or later; 0 are earlier.
  - MLB and WNBA are postseason and reported apart.
- **The two windows overlap by construction.**
  - The weekend run reads only the 10-24/25 recorder files. The pooled run also reads the earlier files. These carry
    earlier sightings of weekend soccer, NCAAF and NFL games.
  - So the pooled file's slate-date 10-24/25 slice is 949 bets, against the weekend run's 906. By sport: soccer 107 vs
    89, NCAAF 99 vs 80, NFL 97 vs 91. NBA, NHL, MLB and WNBA are identical.
  - The **independent** second window is the pooled run's slate-date **10-23..10-25** slice (1,488 / 150).
  - The pooled run's 10-17..10-22 slice reproduces findings 10-23: 974 / 176, −0.9% [−8.0, +8.0], against −0.8%
    [−7.9, +8.2]. One more bet has settled since.
- **Paper-book stake cap per alt ladder** (live 10-26 8:35 AM CT, extended 9:52 AM CT to count held orders): it changes
  paper STAKES, not which lines are Suggested, and it postdates both windows. It does not affect this flat-1-unit grade.

## 1. Headline: Suggested vs everything priced (regular season)

| window | set | bets (ladders) / games | hit % | ROI [95% by game] | units |
|---|---|---|---|---|---|
| **weekend 10-24/25** | **Suggested, per bet** | 906 / 119 | 43.9 | **−10.1% [−23.1, +2.3]** | −91.76 |
| | **Suggested, ladders once** | 711 / 119 | 48.4 | **−2.2% [−12.4, +7.2]** | −15.54 |
| | All priced, per bet | 108,763 / 178 | 43.7 | −14.2% [−17.3, −11.7] | −15,481.08 |
| | All priced, ladders once | 31,591 / 178 | 44.1 | −20.6% [−25.0, −16.7] | −6,510.85 |
| **pooled 10-17..10-25** | **Suggested, per bet** | 2,462 / 326 | 46.7 | **−4.2% [−10.7, +1.8]** | −104.16 |
| | **Suggested, ladders once** | 1,996 / 326 | 50.3 | **+0.8% [−4.0, +5.7]** | +16.10 |
| | All priced, per bet | 314,687 / 476 | 44.3 | −13.5% [−15.4, −11.9] | −42,437.25 |
| | All priced, ladders once | 86,925 / 476 | 44.4 | −20.8% [−23.2, −18.5] | −18,085.15 |
| independent 10-23..10-25 (slate dates) | Suggested, per bet / once | 1,488 / 150; 1,162 ladders | 45.6 | −6.4% [−14.8, +2.3]; once +0.4% [−6.3, +7.3] | −95.84; +4.95 |
| | All priced, per bet / once | 167,327 / 206; 43,591 | 44.4 | −14.3% [−17.0, −12.2]; once −21.9% | |

Postseason, reported apart:
- **MLB.** Weekend: Suggested 1 bet / 1 game, +16.7% (+0.17 u); all priced 807 / 1, −4.2%. Pooled: 10 / 4, −14.9%
  [−72.2, +63.0]; all priced 3,417 / 5, −11.5%.
- **WNBA.** Weekend: Suggested 15 / 1, +106.8% (+16.02 u), or 11 ladders +66.6%; all priced 2,634 / 1, −10.7%. Pooled:
  73 / 4, +16.2% [−25.4, +71.8], or 48 ladders +5.3%; all priced 11,005 / 4, −15.4%.

**Reading.** The weekend is the weakest per-bet Suggested reading so far (−10.1%), and its lift over everything priced
shrank to about 4 points. **The ladder view says most of that is correlation.**
- 906 bets were 711 ladders, and the loss falls from −91.76 u to −15.54 u.
- Pooled: per bet −4.2%, ladders once +0.8%. The lift over all priced is about 9 points per bet and about 22 points per
  ladder.
- By date (pooled run, Suggested, regular season):
  - 10-17 +1.5% (238 / 85), 10-18 +5.9% (109 / 22), 10-19 +32.7% (27 / 10)
  - 10-20 −14.3% (179 / 23), 10-21 +4.6% (266 / 16), 10-22 −8.9% (155 / 20)
  - 10-23 −1.1% (539 / 23), 10-24 −0.9% (508 / 83), **10-25 −19.3% (441 / 44)**

## 2. By sport (regular season, Suggested vs all priced)

| sport | weekend: Suggested per bet | weekend: ladders once | weekend: All | pooled: Suggested per bet | pooled: ladders once | pooled: All |
|---|---|---|---|---|---|---|
| NBA | 569 / 15, −11.0% [−29.1, +8.9] | 407, −1.0% [−15.3, +14.1] | 48,755 / 15, −7.7% | 1,553 / 42, −7.1% [−15.3, +1.2] | 1,157, −1.1% [−7.7, +5.3] | 148,678 / 43, −7.4% |
| NFL | 91 / 12, −21.4% [−40.9, +1.8] | 84, −17.3% [−37.8, +6.3] | 16,331 / 12, −5.6% | 192 / 26, −6.5% [−21.9, +10.8] | 180, −5.3% [−19.8, +10.5] | 45,711 / 26, −5.5% |
| NCAAF | 80 / 37, +15.6% [−8.3, +42.7] | 76, +17.7% [−6.8, +44.3] | 16,685 / 44, −7.8% | 274 / 102, +8.6% [−4.4, +22.2] | 263, +9.0% [−4.4, +22.4] | 47,548 / 108, −9.6% |
| NHL | 77 / 17, +4.4% [−13.0, +19.3] | 77, +4.4% (no multi-rung ladders) | 4,506 / 17, −13.9% | 243 / 60, **+11.4% [−0.4, +22.8]** | 243, +11.4% | 15,705 / 64, −15.3% |
| soccer | 89 / 38, **−28.9% [−51.6, −1.9]** | 67, −20.5% [−43.6, +8.2] | 22,486 / 90, −39.5% | 200 / 96, −16.3% [−35.8, +5.2] | 153, −8.5% [−29.0, +14.0] | 57,045 / 235, −38.5% |

## 3. Props vs game lines, pregame vs live (regular season)

| cell | weekend: Suggested per bet | weekend: ladders once | weekend: All | pooled: Suggested per bet | pooled: ladders once | pooled: All |
|---|---|---|---|---|---|---|
| props | 420 / 44, −0.1% [−13.0, +12.9] | 405, +1.3% [−11.8, +14.3] | 58,267 / 149, −19.5% | 1,191 / 127, **+2.7% [−4.0, +9.4]** | 1,142, +3.1% [−3.6, +9.4] | 163,823 / 383, −18.6% |
| game lines | 486 / 111, **−18.8% [−35.0, −1.4]** | 306, −6.8% [−19.7, +6.3] | 50,496 / 178, −8.2% | 1,271 / 285, **−10.8% [−19.9, −1.5]** | 854, −2.2% [−9.6, +5.2] | 150,864 / 476, −8.0% |
| pregame | 129 / 53, −9.4% [−33.2, +12.2] | 117, −0.8% [−22.8, +18.5] | 55,072 / 177, −18.2% | 504 / 201, +2.0% [−9.7, +14.2] | 456, +7.9% [−2.7, +19.6] | 166,998 / 476, −17.5% |
| live | 777 / 107, −10.2% [−23.5, +4.9] | 594, −2.5% [−12.1, +8.0] | 53,691 / 178, −10.1% | 1,958 / 254, −5.8% [−12.4, +0.4] | 1,540, −1.3% [−6.2, +3.5] | 147,689 / 473, −8.9% |

Sport × cell (Suggested). These are the only cells with an interval excluding 0, in either view or either window, plus
their independent halves:

- **NHL props:**
  - Pooled: **+13.8% [+0.9, +25.5]** (220 / 57).
  - Halves: 10-17..10-22 +14.0% [−0.0, +27.4] (149 / 39); 10-23..10-25 +13.2% [−10.3, +34.3] (71 / 18); weekend run +8.6%
    [−14.1, +27.0] (66 / 16).
  - NHL pregame overall, pooled: +16.0% [+3.2, +28.2] (206 / 55).
- **NCAAF live:**
  - Pooled: per bet +13.4% [−0.6, +27.8] (201 / 89); **ladders once +15.2% [+1.4, +29.5]** (192).
  - Halves: 10-17..10-22 +8.3% [−8.8, +25.9] (121 / 49), ladders once +10.5%; 10-23..10-25 +21.0% [−5.3, +47.3]
    (80 / 40), ladders once +22.6% [−3.9, +47.9].
- **NBA game lines:**
  - Pooled: per bet **−16.3% [−29.7, −1.9]** (686 / 42); ladders once −5.8% [−16.9, +5.4] (336).
  - 10-23..10-25: per bet −17.4% [−34.9, −0.1] (481 / 27); ladders once −3.5% [−17.9, +10.3] (229).
- **NFL game lines, weekend:** per bet **−36.9% [−56.1, −3.5]** (47 / 11); ladders once −30.9% [−54.8, +6.6] (40).
  Pooled: −18.1% [−38.8, +5.4] (91 / 24).
- **Soccer:**
  - Live, pooled: per bet **−21.0% [−39.9, −2.7]** (119 / 70); ladders once −16.9% [−36.4, +2.3] (99).
  - Pregame, weekend: **−55.6% [−93.8, −0.9]** (27 / 17); ladders once −37.7% [−95.4, +29.0] (18).
  - Soccer Suggested has no props.

**Reading.** Every cell whose per-bet interval sits below 0 is a game-line cell built from multi-rung ladders. **Every one
of them spans 0 in the ladder view.**
- The pooled set holds 214 multi-rung ladders, and the largest has 21 rungs.
- On the weekend, NBA live game lines were 256 bets in 112 ladders (−21.8% → −5.4%).
- Props carry the selection again (pooled +2.7% per bet, +3.1% ladders once). NHL props lead.

EV bands (Suggested, regular season, board `ev` at the sighting). The "raise" test:

| window | view | EV 2–3 | EV 3–5.26 | difference (3–5.26 minus 2–3) [95% by game] |
|---|---|---|---|---|
| pooled | per bet | 965 / 237, −5.8% [−14.4, +3.4] | 1,496 / 284, −3.2% [−10.1, +3.5] | +2.6 pts [−7.1, +12.4] (326 games) |
| pooled | ladders once (keyed within band) | 855, −1.3% | 1,278, −0.0% | +1.3 pts [−8.9, +11.2] |
| pooled | pregame, per bet | 212, +1.3% | 292, +2.5% | +1.3 pts [−23.4, +23.5] (201 games) |
| pooled | live, per bet | 753, −7.8% | 1,204, −4.5% | +3.3 pts [−6.2, +13.1] (254 games) |
| weekend | per bet | 350 / 87, −6.1% [−24.8, +12.5] | 556 / 100, −12.7% [−25.5, +0.1] | (reversed) |

One pooled bet sits above 5.26: a live bet, which lost.

## 4. EV at the Shin close: pregame Suggested (findings 10-19 §2 method)

`scripts/fair_price_eval.py`'s own loader, quote reader and evaluator (production `devig`). Each book's last pre-commence
quote is de-vigged, quotes older than 6 h before commence are dropped, and the median is taken over books. Quote logs:
`<data root>/<sport>_source/tracking/book_quotes/`.

**Weekend 10-24/25.** 129 pregame regular-season Suggested bets graded (53 games); 127 have a close fair (52 games).

| close fair | EV at close [95% by game] | beat the close |
|---|---|---|
| **Shin (the board's fair)** | **+1.99% [−0.12, +4.03]**, median +1.44 (127 / 52) | 77 / 127 |
| power | +0.98% [−1.21, +3.02] | |
| multiplicative | +3.55% [+1.19, +6.00] | |

- **By sport (Shin):**
  - NBA +4.81% [−1.91, +9.49] (28 / 9)
  - NHL +0.84% [−0.11, +1.95] (58 / 14)
  - soccer +3.00% [−2.44, +8.59] (27 / 17)
  - NCAAF +0.78% [−1.35, +3.02] (7 / 6)
  - NFL −2.39% [−6.05, +2.38] (7 / 6)
  - WNBA (postseason, apart) −1.17% (4 / 1)
- **By kind:** game lines +5.11% [−0.62, +10.81] (41 / 27); props +0.50% [−0.55, +1.43] (86 / 27).
- **Pooled 10-17..10-25, same method, for context:** **+1.51% [+0.63, +2.44]** (457 / 191; 504 / 201 graded), beat the
  close 263 / 457.
  - Power close +0.73% [−0.18, +1.67]; multiplicative close +2.73% [+1.64, +3.83].
  - By kind: game lines +3.32% [+1.48, +5.21] (183 / 110); props +0.31% [−0.40, +1.05] (274 / 88).
  - NBA close-fair coverage is the thinnest: 84 of 122 pregame rows.
- **CLV and outcome point opposite ways by kind (pooled pregame).** This is a lead, not a finding.
  - Game lines beat the close (+3.32%, interval above 0) but returned −21.5% flat on those 183.
  - Props barely beat it (+0.31%) but returned +13.3% on those 274.
  - NHL props: +0.10% [−0.66, +0.85] at the close (204 / 55) against +17.2% flat.
  - So NHL props' outcome edge has no closing-line backing yet.
- **Engine read (still open from 10-19 §2).**
  - The board's `ev` at the sighting averages +3.25% on the weekend. A Shin fair rebuilt from the quote logs at the same
    instant gives +2.13% (125 rows). Pooled: +3.35% against +2.38% (435 rows).
  - The gap sits in soccer (board +3.39% vs rebuilt −1.74%, 25 rows) and game lines (+3.23% vs −0.21%, 39 rows).
  - Props agree (+3.27% vs +3.20%).

## 5. NBA re-check (findings 10-23 §4)

NBA Suggested, regular season:

| | weekend 10-24/25 (15 games) | pooled 10-20..10-25 (42 games) |
|---|---|---|
| all, per bet | 569, −11.0% [−29.1, +8.9] | 1,553, −7.1% [−15.3, +1.2] |
| all, ladders once | 407, −1.0% [−15.3, +14.1] | 1,157, −1.1% [−7.7, +5.3] |
| **pregame**, per bet / ladders once | 29 / 9 g, −6.4% [−56.6, +52.8]; 26, +4.4% [−44.7, +52.8] | 122 / 30 g, −12.1% [−39.9, +15.4]; 103, +2.0% [−24.1, +24.4] |
| **live**, per bet / ladders once | 540 / 15 g, −11.2% [−28.7, +8.4]; 381, −1.4% [−14.7, +12.2] | 1,431 / 42 g, −6.7% [−14.7, +1.8]; 1,054, −1.4% [−6.9, +4.9] |
| pregame props | 24 / 8, +13.1% | 81 / 28, +4.4% [−19.9, +28.2] |
| pregame game lines | 5 / 2: **0 of 5, −5.00 u** (2 ladders) | 41 / 12, hit 17.1%, −44.9% [−89.2, +27.5]; 23 ladders, −1.7% [−73.3, +57.6] |
| live props | 284, −1.7%; ladders once +0.3% | 786, −0.3% [−7.9, +8.1]; 741, +0.6% |
| live game lines | 256, −21.8% [−49.6, +9.7]; 112 ladders, −5.4% [−28.8, +15.1] | 645, −14.4% [−28.2, +1.2]; 313, −6.1% [−17.8, +4.1] |

All priced NBA, pooled: −7.4% per bet (148,678 / 43); ladders once −8.3% (22,636).

- **The weekend's NBA pregame game lines repeat the opener on a small scale.**
  - Five `spreads_alt` home-favourite rungs on two games: Fanatics ×4 at +160..+280 on one game, Bovada +220 on the
    other.
  - All five were first sighted 10-24 at 12:05 AM CT.
  - All five beat the close: the Shin fair moved from 0.27–0.39 to 0.35–0.48, for EV at the close +24.86% mean.
  - All five lost.
- **Lead, not a finding.** Over the pooled window, NBA pregame game-line Suggested rows that have a close fair number 28,
  across 6 games. They won **0**, against **9.69** expected at the close fair (9.29 at the sighting). The 13 rows with
  no close fair won 7.
  - That is 6 games.
  - The 10-23 tail-calibration check (16,754 rows / 16 games) found no bias on NBA alt rungs.
  - Re-read when NBA pregame alt rows reach ≥ 20 games with a close fair.

**Sim main-total lean.** The rule is the 10-23 one: per game, the first pregame `totals` / `full` / over row with `me`;
`me > 0` means a lean over; `y` grades the result against that row's line. The rule reproduces 10-23's 15 of 16 / 9 under
exactly.

| games | leaned over / under | went over / under | lean over & went under | lean right |
|---|---|---|---|---|
| 10-20..10-22 (16) | 15 / 1 | 6 / 10 | 9 | 7 of 16 |
| **new, 10-23..10-25 (27)** | **13 / 14** | 11 / 16 | 9 | 11 of 27 |
| **pooled 10-20..10-25 (43)** | **28 / 15** | 17 / 26 | 18 | 18 of 43 |

- **Sign test** on the lean direction (two-sided, fair coin): p = 0.0005 for 10-20..10-22, 1.0 for the new games, 0.066
  pooled.
- **Magnitude** (`me` on the over row, in points): the range was −0.07..+0.81 on 10-20..10-22 and widened to
  −1.81..+1.06 from 10-23. Pooled mean +0.05, median +0.25.
- **The one-way over lean did not persist.** The 27 new games split 13 / 14.
- The lean was right in 18 of 43 games (42%), so there is no sign it carries information.
- **Candidate cause, NOT tested:** two NBA injury-report changes landed on main 10-22. `36eb357b` landed at 10:44 AM CT
  and `21b4bdb0` at 12:07 PM CT, the latter titled "SmartSim trusts the game date's own report". Whether or when they
  reached the fleet, and whether they explain the shift, is not checked.
- Re-read at ≥ 50 regular-season games (43 now): the sim's mean total vs the closing total vs the final.

## 6. Beside the earlier evidence

| reading | Suggested | ladders once | all / board |
|---|---|---|---|
| 10-06..10-12 backtest (843 / 162) | −4.1% [−12.8, +7.5] | — | −16.8% |
| weekend 10-10/11, published EV ≥ 2 | +4.6% [−4.1, +14.0] | — | −10.0% |
| weekend 10-17/18, recorded `sg` (339 / 105) | +3.9% [−7.7, +15.4] | — | −17.3% |
| 10-17..10-22, recorded `sg` (973 / 176) | −0.8% [−7.9, +8.2] | +1.5% [−5.4, +8.6] | −12.5% |
| **weekend 10-24/25 (906 / 119)** | **−10.1% [−23.1, +2.3]** | **−2.2% [−12.4, +7.2]** (711) | −14.2% |
| 10-23..10-25 slate dates (1,488 / 150) | −6.4% [−14.8, +2.3] | +0.4% [−6.3, +7.3] (1,162) | −14.3% |
| **pooled 10-17..10-25 (2,462 / 326)** | **−4.2% [−10.7, +1.8]** | **+0.8% [−4.0, +5.7]** (1,996) | −13.5% |

EV at the close, pregame Suggested:

| window | EV at close [95% by game] | n / games |
|---|---|---|
| 10-13 backtest (valued at the POWER close) | +1.53% | |
| 10-17/18, Shin close | +1.45% [+0.25, +2.73] | 130 / 62 |
| **10-24/25, Shin close** | **+1.99% [−0.12, +4.03]** | 127 / 52 |
| **pooled 10-17..10-25, Shin close** | **+1.51% [+0.63, +2.44]** | 457 / 191 |

Every outcome reading's interval spans 0. Below the population, the lift holds in every reading:
- +4 to +21 points per bet
- +18 to +22 points in the ladder view

The selection beats the close in every window. On a pooled 191 games the Shin-close interval is clear of 0.

## 7. Against the 10-23 §5 criteria: the data SUPPORTS the user's keep-2% decision

None of the three conditions that would argue for changing the threshold is met.

- **Raise** (EV 2–3 reliably below EV 3–5.26, pooled over several weekends): **NOT MET.**
  - Pooled difference +2.6 pts [−7.1, +12.4] per bet and +1.3 [−8.9, +11.2] in the ladder view (326 games).
  - The weekend reverses it: EV 2–3 −6.1% against EV 3–5.26 −12.7%.
  - A higher bar has no support.
- **Restrict to cells** (a cell clear of 0 on a second, independent window): **NOT MET.**
  - NHL props clear 0 only on the pooled window (+13.8% [+0.9, +25.5], 220 / 57), and that window contains the first.
  - Each independent half spans 0: +14.0% [−0.0, +27.4] and +13.2% [−10.3, +34.3].
  - The point estimate replicated, but NHL props do not beat the close (+0.10%).
  - NCAAF live clears 0 only pooled, in the ladder view.
  - NHL props remain the cell to watch.
- **Lower or abandon** (EV at the Shin close ≤ 0): **NOT MET.**
  - Weekend +1.99% [−0.12, +4.03]; pooled +1.51% [+0.63, +2.44].
  - The selection still beats the market's close.
- **The per-bet losses are ladder-shaped**, which is what the user's stake cap addresses.
  - Every negative-clear cell is multi-rung game lines, and each spans 0 once ladders are counted once.
  - The cap changes paper stakes, not selection. It went live after both windows (8:35 AM CT 10-26; held orders counted
    from 9:52 AM CT). So it is invisible to this flat-1-unit grade by construction. Its effect belongs to a
    paper-ledger read, not to this one.
- **Soccer is negative on all five graded windows:** −19.4%, −15.4%, −12.5%, weekend −28.9% [−51.6, −1.9] (89 / 38) and
  pooled −16.3% [−35.8, +5.2].
  - The weekend's per-bet interval is the first to exclude 0. Its ladder view spans 0: −20.5% [−43.6, +8.2].
  - EV at the close is positive (+3.00% weekend, +2.80% pooled), while the fair rebuilt at the sighting sits below the
    board's (−1.30% vs +3.29% pooled, 60 rows).
  - That pattern is the fair-price question (`fair-price-v2` H6, scored offline from 10-30), not a threshold question.
    No sport or market is recommended for removal.
- **What would change it:** the same criteria.
  - **raise:** a pooled difference with its interval above 0.
  - **restrict:** NHL props, or any cell, clear of 0 on a third window that excludes 10-17..10-25.
  - **lower or abandon:** EV at the Shin close ≤ 0 on a new window.
- **The natural next reading** (nothing scheduled by this run): weekend 10-31 / 11-01 plus pooled 10-17..11-01, in both
  views.
  - It brings NBA past 50 games for the lean re-read.
  - It gives a third independent window for NHL props.

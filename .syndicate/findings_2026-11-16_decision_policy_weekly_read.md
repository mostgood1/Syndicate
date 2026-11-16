# Decision policy v1 PAPER — weekly Monday read, 2026-11-16 `[lane decision-policy-paper, todo #738, umbrella #736]`

**Scheduled, read-only run** (task `decision-policy-paper-weekly-read`, the `#717` weekly line). It started 9:44 AM CST,
on time. Prereg `8d16ab07` (`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md`). Previous read:
`.syndicate/findings_2026-11-09_decision_policy_weekly_read.md`. Every comparison below is against it.

Nothing was changed: no rule, parameter, z, env, code, fleet job or file in the paper store. `run_decision_policy_paper.py`
was not run. The evaluator ran WITHOUT `--run`. Every fleet command ran at `nice -n 19`. All times are US Central (CST).

## 0. A LOOK WAS TAKEN: P2 `net_floor_719` L1 — FAIL

The fleet's 7:45 AM CST nightly on 2026-11-16 took P2's first registered look. Verbatim from `looks.json`
(sha256 `42ea01b4…`; it was `43c100bd…` on 11-09):

```
"net_floor_719": {
  "closed": null,
  "looks": [
   {
    "boundary": 3.935,
    "date": "2026-11-16",
    "games": 270,
    "look": "L1",
    "mean": -2.2021,
    "n": 413,
    "pass": false,
    "se": 0.3094,
    "z": -7.1163
   }
  ],
  "passed": null
 }
```

The nightly log line: `GATE_READ date=2026-11-16 strategy=net_floor_719 bets=1035 n=413 games=270 mean=-2.2021
z=-7.1163 look=look_taken`.

- **What it means under the registration.** P2's fee-net CLV against the Pinnacle close is −2.20% on 413 sharp-graded
  bets over 270 games (z −7.12, CI [−2.81, −1.63]). L1 needs z ≥ 3.935. **P2 did not pass L1.**
- **What it does not mean.** The prereg has no futility boundary (§7 defines only a PASS). A failed look does not
  close the candidate: `closed` and `passed` stay `null`, and P2 goes on to **L2 (800 / 200, boundary 2.783)** and
  L3 (1,200 / 300 or 2027-01-31, boundary 2.272). Under §8, a candidate that passes no look by its final look has not
  passed.
- **Nothing changes live.** Live capital stays at canary. Any change, including stopping P2 early on futility, is a
  NEW registration and the user's decision. This read does not recommend one.
- **P1 `ev_lb` has taken no look** (`looks: []`). It is at 133 / 101 games against L1's 400 / 100.
- **Gate verdict: `NOT_YET`, `passed_by=[]`.**

## 1. The jobs ran

- **The nightly.** The 7:45 AM CST nightly wrote `reads/2026-11-16.json` (read_at 7:45:43 AM CST). It logged
  `PAPER_GRADED` and three `GATE_READ` lines.
  - It ran on all 7 mornings since the last read (11-10 to 11-16), with one `PAPER_GRADED` line and three `GATE_READ`
    lines each morning.
  - There were no error lines. The only other line is the routine `HTTP_COMPRESSION` stat.
- **The book job.** From 11-09 9:37 AM to 11-16 9:39 AM CST:
  - There were **672 run headers** (96 a day × 7), so the job ran every 15 minutes.
  - It wrote **785 `PAPER_BOOKED` lines**, **0 `MODE_OFF`** and **0 error / `CHIPS_UNREADABLE` / `NO_BOOK` lines**.
  - There are 23 gaps of 22–45 min between `PAPER_BOOKED` lines. The run header is there every 15 min, so I read these
    as runs with no new build, as on 11-09. I did not check that in the code.
  - `builds.jsonl` has 785 builds since the last read.
- **Fleet checkout.** `09925a4b1` (11-16 7:52 AM CST). It contains both read scripts.

## 2. Gate read (prereg §7), read 11-16 7:45 AM CST

Command: `evaluate_decision_policy_paper.py --date 2026-11-16` (read-only, no `--run`). Its output matches the nightly's
`GATE_READ` lines.

- CLV is fee-net CLV against the Pinnacle close, in %. z is the game-clustered Z.
- CI is the game-clustered bootstrap 95% CI.
- ROI is flat, per unit, on full-game lines only.

| strategy | bets | sharp-graded n / games | CLV mean | z | CLV 95% CI | ROI flat n / games | ROI mean | ROI 95% CI | no sharp close | look |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 `ev_lb` | 396 | 133 / 101 | −0.30% | −0.64 | [−1.27, +0.57] | 129 / 127 | +0.051 | [−0.064, +0.166] | 260 | waiting (L1 400 / 100) |
| P2 `net_floor_719` | 1,035 | 413 / 270 | −2.20% | −7.12 | [−2.81, −1.63] | 363 / 336 | −0.007 | [−0.107, +0.090] | 611 | **L1 taken 11-16: FAIL** (next L2 800 / 200) |
| C0 `suggested_2pct` (comparator) | 2,172 | 1,132 / 426 | −7.03% | −20.57 | [−7.71, −6.40] | 451 / 371 | −0.129 | [−0.227, −0.037] | 1,011 | comparator, no look |

**Change since 11-09:**

- **P1.** n went from 96 / 74 games to 133 / 101. CLV went from −0.39% to −0.30%, z from −0.68 to −0.64.
- **P2.** n went from 284 / 199 to 413 / 270. CLV went from −1.85% to −2.20%, z from −5.14 to −7.12.
- **C0.** CLV went from −7.30% to −7.03%.

**ROI.** P1's flat-ROI CI no longer excludes zero: it was +0.169 [+0.012, +0.331] on 65 bets, and is +0.051
[−0.064, +0.166] on 129 bets / 127 games. ROI is never the gate.

Reported, never decisive (prereg §7):

- **By venue.**
  - P1: Kalshi 111 bets / 79 games, −0.51%; Polymarket 22 / 22, +0.75%.
  - P2: Kalshi 324 / 191, **−2.71%** (z −7.47); Polymarket 89 / 80, −0.34%.
  - C0: Kalshi 1,005 / 320, −7.18%; Polymarket 127 / 114, −5.90%.
- **By sport (sharp-graded bets).**
  - P1: NFL 49 / 25, −0.09%; NBA 35 / 30, −0.80%; soccer 23 / 23, −0.20%; NHL 19 / 16, −0.46%; NCAAF 7 / 7, +0.70%.
  - P2: NBA 129 / 78, **−3.56%**; NHL 88 / 55, **−3.16%**; soccer 84 / 75, −0.59%; NFL 82 / 33, −1.73%;
    NCAAF 28 / 27, +0.40%; MLB 1 / 1; WNBA 1 / 1.
  - C0: NBA 436 / 130, −5.87%; NHL 377 / 94, −9.69%; NFL 130 / 38, −5.52%; soccer 92 / 82, −6.55%; NCAAF 87 / 78,
    −2.94%; WNBA 6 / 2; MLB 4 / 2.
- **By market family.**
  - P1: props 103 / 71, −0.40%; h2h 15 / 15, −0.59%; game_other 9 / 9, −0.43%; totals 6 / 6, +2.17%.
  - P2: props 299 / 166, **−2.94%** (z −7.65); h2h 56 / 56, −0.32%; game_other 28 / 27, −0.60%; totals 21 / 21,
    −0.67%; spreads 9 / 9, +2.07%.
  - P2's deficit still sits in props (11-09: −2.73% on 176 / 101). Its game lines are within about 0.7 pts of zero.
- **By σ source.**
  - P1: S1 49 / 46, −0.17%; S2 84 / 55, −0.38%.
  - P2: S1 193 / 151, −1.46%; S2 207 / 111, −2.86%; S3 13 / 13, −2.76%.
- **Price band 0.40–0.75.** P1 118 / 89, −0.37%. P2 366 / 239, −2.15%. C0 918 / 360, −5.73%.
- **Stake-weighted (§4 sizing), CLV / ROI.** P1 +0.64% / +0.041. P2 +0.72% / +0.021. C0 −0.13% / −0.224.
- **Against C0, on the axes both booked.**
  - P1 − C0: n 55 / 46 games, +4.31 pts, CI [+1.38, +7.67] (11-09: +3.11 on 36, CI crossed zero).
  - P2 − C0: n 154 / 118, +3.03 pts, CI [+1.36, +4.70].
- **Consensus close, every graded bet.**
  - P1: 382 / 265 games, +0.15% [−0.27, +0.52].
  - P2: 961 / 544, −1.02% [−1.38, −0.66].
  - C0: 2,071 / 669, −7.23% [−7.77, −6.75].

**Season phases.** Phases are not pooled except where the registered statistic pools by design.

- **NBA, NHL, NFL and NCAAF** are in the regular season.
- **NCAAB and WNCAAB** are in the early regular season.
- **Soccer: no bet was booked by any strategy since 11-08 12:21 PM CST** (the last of 306 lifetime soccer bets). The
  11-09 funnel also had no eligible soccer line. The likely cause is the November international window (club leagues
  paused); **I did not verify that.** The check is whether soccer candidates appear in this week's decision records.
  The soccer bets in the gate are all from before 11-09. `bets.jsonl` has no competition field, so soccer cannot be
  split by competition.
- **MLB and WNBA** are over. The pooled P2 gate still carries their two old postseason bets.

## 3. Booking rate (from `bets.jsonl`, 11-09 9:37 AM to 11-16 9:39 AM CST)

1,432 bets were booked: P1 149, P2 395, C0 888. The store's lifetime total is 3,609.

- 785 builds were processed. 410 booked at least one bet: P1 on 115, P2 on 259, C0 on 318.
- **Failed gates, summed over builds:** outside the decision window 242,337; one-sided fair 47,234; not pregame 35,139;
  implausible venue price 9,193; stale quote 3,474.

| Central day | P1 all (gate-eligible* / NCAAB) | P2 all (gate-eligible* / NCAAB) | C0 all (gate-eligible* / NCAAB) |
|---|---|---|---|
| 11-09 (from 9:37 AM) | 12 (9 / 3) | 31 (19 / 12) | 92 (88 / 4) |
| 11-10 | 24 (15 / 9) | 58 (42 / 16) | 145 (131 / 14) |
| 11-11 | 17 (7 / 10) | 49 (29 / 20) | 113 (100 / 13) |
| 11-12 | 22 (13 / 9) | 49 (41 / 8) | 96 (84 / 12) |
| 11-13 | 13 (6 / 7) | 57 (35 / 22) | 136 (122 / 14) |
| 11-14 (Sat) | 26 (19 / 7) | 84 (59 / 25) | 150 (139 / 11) |
| 11-15 (Sun) | 34 (27 / 7) | 57 (50 / 7) | 123 (118 / 5) |
| 11-16 (to 9:39 AM) | 1 (0 / 1) | 10 (6 / 4) | 33 (27 / 6) |

\* In this table "gate-eligible" excludes NCAAB, MLB and WNBA but still includes WNCAAB's few bets (P1 8, P2 10, C0 16
this week). The daily rate below excludes WNCAAB too.

**Split, since 11-09:**

- **P1.** Kalshi 110, Polymarket 39. NCAAB 53, NHL 36, NBA 34, NFL 16, WNCAAB 8, NCAAF 2, **soccer 0** (11-09: 20).
  Props 84, game lines 65. σ: S2 97, S1 38, S3 14. 118 events.
- **P2.** Kalshi 293, Polymarket 102. NCAAB 114, NBA 112, NHL 108, NFL 32, NCAAF 19, WNCAAB 10, soccer 0 (11-09: 79).
  Props 239, game lines 156. 232 events.
- **C0.** Kalshi 793, Polymarket 95. NBA 439, NHL 223, NCAAF 84, NCAAB 79, NFL 47, WNCAAB 16. 267 events.
- **College basketball is now 41% of P1's bookings** (61 of 149; 11-09: 38 of 139, 27%) and 31% of P2's. None of it
  counts toward a look.

**Gate-eligible daily rate** (no NCAAB, WNCAAB, MLB or WNBA), over the six full days 11-10..11-15:

- P1: 15 + 7 + 12 + 6 + 16 + 23 = 79, **13.2 a day** (11-09: 14.3).
- P2: 41 + 28 + 39 + 35 + 57 + 47 = 247, **41.2 a day** (11-09: 46.0).
- C0: 678, **113.0 a day** (11-09: 106.3).

### Projection to the next look (PROJECTIONS, not results)

**Sharp-graded share,** on FINAL grades of gate-eligible bets booked since 11-09:

- P1 36 of 66 (**0.545**; 11-09: 0.706). By sport, including NCAAB for scale: NFL 11/12, NCAAF 1/1, NHL 11/23, NBA 13/30,
  NCAAB 0/37.
- P2 123 of 205 (**0.600**; 11-09: 0.704). NFL 20/23, NCAAF 6/6, NHL 46/77, NBA 51/99, NCAAB 0/75.
- C0 427 of 633 (0.675).
- The share fell because soccer (16 of 17 sharp-graded for P1 last week) booked nothing, and NBA and NHL props carry
  Pinnacle on only about half.

| | now n / games | sharp-graded a day (rate × share) | n to next look | days | projected first nightly with the next look | cross-check: read-to-read pace 11-09 → 11-16 | 11-09 projection |
|---|---|---|---|---|---|---|---|
| P1 → L1 (400 / 100) | 133 / 101 | 13.2 × 0.545 = 7.2 | 267 | 267 / 7.2 = 37 | **~Wed 12-23** | (133 − 96) / 7 = 5.3 a day → 50 d → ~01-05 | ~12-09..12-14 |
| P2 → L2 (800 / 200) | 413 / 270 | 41.2 × 0.600 = 24.7 | 387 | 387 / 24.7 = 16 | **~Wed 12-02** | (413 − 284) / 7 = 18.4 a day → 21 d → ~12-07 | L2 ~11-25..11-28 |
| P2 → L3 (1,200 / 300) | — | 24.7 | 787 | 32 | **~12-18** | 787 / 18.4 = 43 d → ~12-29 | ~12-07..12-13 |
| C0 | 1,132 / 426 | — | — | — | comparator, no look | — | — |

- **Games are not binding.** P1 has 101 games, past L1's 100. P2 has 270, past L2's 200, and reaches 300 for L3 well
  before its n does.
- **Both remaining looks still project before 2027-01-31.** P1's L1 has slipped by about 2–3 weeks and now has about
  4–6 weeks to spare (11-09: 7–8).
- **What would move these dates:**
  - **Soccer's return.** It was P1's highest-share sport. If the pause is the international window, it should
    return from about 11-21 and lift both the rate and the share.
  - **College basketball.** It is the fastest-growing share of P1's volume and never counts.
  - **Weekends.** P1 booked 19 and 27 gate-eligible bets on Sat/Sun against 6–15 on weekdays.
  - **Pinnacle coverage** of NBA and NHL props. The D5 swap (lane `pinnacle-coverage-d5`) would move the share.

### NCAAB (consensus close only, NOT in the gate population)

NCAAB went onto Kalshi on 2026-11-04 at 00:46Z (11-03 6:46 PM CST). NCAAB quotes carry no Pinnacle price, so every NCAAB bet
grades on the consensus close only (`no_pinnacle_close_at_this_line`). **None counts toward a look.**

The CIs below are my own game-clustered bootstrap from `grades.json` (2,000 resamples). They are FINAL grades only and
cover every NCAAB bet since 11-04.

| strategy | NCAAB bets / games | venue | graded | sharp close | consensus CLV, final (n / games) | 95% CI | 11-09 |
|---|---|---|---|---|---|---|---|
| P1 | 90 / 88 | Kalshi 42, Polymarket 48 | 87 | 0 | **+0.68%** (71 / 69) | [+0.26, +1.10] | +0.38% (27 / 27) |
| P2 | 178 / 163 | Kalshi 70, Polymarket 108 | 173 | 0 | −0.38% (122 / 114) | [−1.18, +0.44] | −0.48% (35 / 34) |
| C0 | 139 / 126 | Kalshi 65, Polymarket 74 | 133 | 0 | −9.58% (102 / 92) | [−12.13, −7.12] | −9.53% (29 / 29) |

P1's NCAAB consensus CLV CI now excludes zero (71 bets / 69 games). The consensus close is not the registered gate
statistic, and it is not a sharp reference; this is reported, not a result.

WNCAAB has the same property: lifetime P1 + P2 + C0 = 44 bets, none sharp-graded.

## 4. ev_lb funnel on the current files (post hoc, read-only; `scripts/ev_lb_funnel_read.py` on fleet `09925a4b1`)

**Input.** Only that morning's current record files:

- `2026-11-16.json.gz`: build `|1794843893`, written 9:44 AM CST. 852 candidates, 266 eligible.
- `2026-11-17.json.gz`: build `|1794839147`, written 8:25 AM CST. 552 candidates, 24 eligible.

**Gates and qualifiers.** Of the 1,404 candidates, the gates removed 1,032 outside the window, 51 one-sided fair and
31 stale quotes. The snapshots qualify P1 0, P2 4 and C0 9.

**Buckets, 290 eligible candidate-sides.** g = consensus − ask, f = fee, h = haircut, all in probability points.

| | n | A ask ≥ consensus | B fee eats | C haircut eats | D qualifies |
|---|---|---|---|---|---|
| **all, 11-16** | 290 | 74.8% (217) | 19.3% (56) | 5.9% (17) | **0 (0)** |
| all, 11-09 | 360 | 71.1 | 27.5 | 1.4 | 0 |
| all, 11-02 | 367 | 79.0 | 18.5 | 2.2 | 0.3 (1) |
| Kalshi | 216 | 77.3 | 18.5 | 4.2 | 0 |
| Polymarket | 74 | 67.6 | 21.6 | 10.8 | 0 |
| NCAAB | 93 | 68.8 | 18.3 | 12.9 | 0 |
| NHL | 75 | 81.3 | 16.0 | 2.7 | 0 |
| NBA | 51 | 78.4 | 17.6 | 3.9 | 0 |
| NCAAF | 44 | 79.5 | 20.5 | 0 | 0 |
| NFL | 25 | 60.0 | 36.0 | 4.0 | 0 |

- **No soccer line was eligible**, for the second week running.
- **g and the fee.** g has median −0.62 pts, p90 +0.98 and max +2.53 (11-09: −0.74 / +0.84 / +2.32). The fee median is
  1.71 pts. 17 of 290 lines are net-positive before the haircut, and 2 would qualify at half the haircut.
- **Haircut median by σ source:**

  | σ source | lines (of 290) | 11-16 median | 11-09 | 11-02 |
  |---|---|---|---|---|
  | all | 290 | **1.10 pts** | 1.08 | 1.33 |
  | S1 `fair_v1` | 113 | 1.28 | 1.29 | 1.40 |
  | S2 dispersion | 168 | 0.98 | 1.02 | 1.08 |
  | S3 inflated | 9 | 4.02 | 4.22 | 3.76 |

- **A + B = 94.1%** (11-09: 98.6%; 11-02: 97.5%). Bucket C grew from 1.4% to 5.9%, and 12 of its 17 lines are NCAAB
  game lines (NCAAB C = 12.9%). Those are lines where the venue ask beats consensus by more than the fee and the
  haircut takes the rest. All 17 C lines are S2 or S3. The 10-27 funnel reading (A + B dominate) stands.
- **Why D = 0 here while P1 books about 13 a day.** Each line is decided once, at the first qualifying build, out of
  96 builds a day, while the funnel sees one snapshot per file (prereg §9).
- Scratch output: `C:\tmp\phase2_read_1116\funnel\report.json` and `candidates.csv`.

## 5. Grading health

**Nightly grading has run.** There were seven `PAPER_GRADED` lines since 11-09, all at about 7:45 AM CST:

| read | bets graded | with a sharp close | with an outcome |
|---|---|---|---|
| 11-10 | 383 | 70 | 143 |
| 11-11 | 408 | 92 | 105 |
| 11-12 | 412 | 74 | 125 |
| 11-13 | 413 | 82 | 147 |
| 11-14 | 351 | 64 | 145 |
| 11-15 | 457 | 92 | 228 |
| 11-16 | 528 | 134 | 183 |

**`grades.json` holds 3,560 graded bets** of the 3,609 in the store (3,261 final).

- 1,678 have a sharp close.
- **1,882 (52.9%) have none.** Every one gives the reason `no_pinnacle_close_at_this_line`. On 11-09 it was 1,062 of
  2,132 (49.8%).
- 3,414 have a consensus close.

**Where the sharp close is missing,** as final bets without one / all final bets, by sport and kind:

| sport and kind | without / final | share missing |
|---|---|---|
| NCAAB games | 328 / 328 | 100%, by design |
| WNCAAB games | 23 / 23 | 100% |
| NHL games | 35 / 35 | 100% (no Pinnacle NHL game lines, prereg §9) |
| MLB | 119 / 124 | about all, season over |
| WNBA | 41 / 48 | about all, season over |
| NBA props | 577 / 1,177 | 49% |
| NCAAF games | 104 / 226 | 46% |
| soccer games | 107 / 306 | 35% |
| NHL props | 216 / 700 | 31% |
| NFL props | 33 / 294 | 11% |

**Selection check on moved lines (prereg §9)**, from the read: bets without a sharp close, against the consensus close,
NCAAB included.

- P1's 260 show **+0.46%** (249 / 185 games, CI [+0.03, +0.89]). 11-09: +0.69%.
- P2's 611 show −0.63% (548 / 375, CI [−1.04, −0.24]). 11-09: −0.76%.
- P1's no-sharp bets still beat consensus while its sharp-graded bets sit at −0.30% against Pinnacle. This is the
  selection effect the prereg said to watch, and NCAAB is now most of it.

**Outcome grades.** 943 bets have an outcome grade. 2,482 are props with no outcome grader, 125 are `game_other`, 7 are
`no_chip_match` (11-09: 1) and 3 are not final. As registered, ROI covers full-game lines only.

**No `CHIPS_UNREADABLE`, `NO_BOOK` or error line appeared in either log.**

## 6. What this does and does not say

- **P2 took L1 on 11-16 and failed it** (z −7.12 against 3.935, 413 / 270). It continues to L2 under the registration.
  Live is unchanged: canary stays.
- **P1 has not reached L1.** `NOT_YET` is its status. Its L1 is projected for about 12-23 (pace cross-check ~01-05),
  later than last week's ~12-09..12-14. Both are projections.
- **Evidence that could motivate a NEW registration** (named, not recommended; the user's decision):
  - **P2's L1 z of −7.12.** No futility rule was registered, so P2 runs on to L2 and L3. Stopping it early is a new
    decision. Under O'Brien–Fleming, reaching +2.783 at L2 from −7.12 at n = 413 would need the next ~390 bets to average
    far above anything P2 has shown.
  - **P2's deficit is Kalshi props.** Props −2.94% (299 / 166); Kalshi −2.71% (324 / 191) against Polymarket −0.34%
    (89 / 80); NBA −3.56% and NHL −3.16%. Its game lines are near zero. A per-family or per-venue rule would be a new
    registration.
  - **NCAAB has no sharp close at all**, and P1's NCAAB consensus CLV is +0.68% [+0.26, +1.10] on 71 bets / 69 games. A
    consensus-close gate for it would be a new registration, with the caveat that consensus is not a sharp reference.
  - **Bucket A + B = 94.1%.** The taker side is still efficient after fees. The maker-side lead remains the one that
    changes both terms.
  - **The z-on-sharp-close refit** stays the first lever if a candidate reaches a look and misses it on CLV. P2 now has.
- **Next registered read: Mon 2026-11-23.**

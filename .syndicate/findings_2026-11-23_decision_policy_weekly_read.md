# Decision policy v1 PAPER — weekly Monday read, 2026-11-23 `[lane decision-policy-paper, todo #738, umbrella #736]`

**Scheduled, read-only run** (task `decision-policy-paper-weekly-read`, the `#717` weekly line). It started about 9:44 AM CST,
on time. Prereg `8d16ab07` (`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md`). Previous read:
`.syndicate/findings_2026-11-16_decision_policy_weekly_read.md`. Every comparison below is against it.

Nothing was changed: no rule, parameter, z, env, code, fleet job or file in the paper store. `run_decision_policy_paper.py`
was not run. The evaluator ran WITHOUT `--run`. Every fleet command ran at `nice -n 19`. All times are US Central (CST).

## 0. Looks: NONE taken since 11-16

`looks.json` is byte-identical to the 11-16 read (sha256 `42ea01b4…`). It still holds exactly one look, P2's L1 from
11-16 (n 413 / 270 games, z −7.1163 against 3.935, `pass: false`). `closed` and `passed` are `null` for both candidates.
P1 `ev_lb` has `looks: []`.

- **Gate verdict: `NOT_YET`, `passed_by=[]`.** NOT_YET is the expected status until a registered count is reached. It is
  not a result.
- P1 waits for L1 (400 / 100). P2 waits for L2 (800 / 200, boundary 2.783).
- Live capital stays at canary. Nothing here changes it.

## 1. The jobs ran

- **The nightly.** The 7:45 AM CST nightly wrote `reads/2026-11-23.json` (read_at 7:45:56 AM CST). It logged one
  `PAPER_GRADED` line and three `GATE_READ` lines.
  - It ran on all 7 mornings since the last read (11-17 to 11-23), with one `PAPER_GRADED` and three `GATE_READ` lines each
    morning. The 11-18 and 11-19 runs logged at 7:49 and 7:47 AM. The others logged at 7:45–7:46.
  - There were 0 error or traceback lines in the nightly log.
- **The book job.** From 11-16 9:39 AM to 11-23 9:35 AM CST:
  - There were **672 run headers** (96 a day × 7), with **no gap over 20 min**, so the job ran every 15 minutes.
  - It wrote **762 `PAPER_BOOKED` lines**, **0 `MODE_OFF`** and **0 error / traceback / `CHIPS_UNREADABLE` / `NO_BOOK` lines**.
  - `builds.jsonl` has 762 builds since the last read. Lifetime: 2,837 builds and 4,996 bets.
- **Fleet checkout.** `05a2ce65e`. It contains both read scripts.

## 2. Gate read (prereg §7), read 11-23 7:45 AM CST

Command: `evaluate_decision_policy_paper.py --date 2026-11-23` (read-only, no `--run`). Its output matches the nightly's
`GATE_READ` lines and `reads/2026-11-23.json`.

- CLV is fee-net CLV against the Pinnacle close, in %. z is the game-clustered Z.
- CI is the game-clustered bootstrap 95% CI.
- ROI is flat, per unit, on full-game lines only.

| strategy | bets | sharp-graded n / games | CLV mean | z | CLV 95% CI | ROI flat n / games | ROI mean | ROI 95% CI | no sharp close | look |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 `ev_lb` | 532 | 188 / 142 | −0.18% | −0.48 | [−0.91, +0.53] | 175 / 173 | +0.076 | [−0.020, +0.175] | 343 | waiting (L1 400 / 100) |
| P2 `net_floor_719` | 1,387 | 563 / 375 | −2.04% | −7.71 | [−2.55, −1.52] | 519 / 482 | +0.004 | [−0.079, +0.085] | 820 | waiting (L2 800 / 200); L1 failed 11-16 |
| C0 `suggested_2pct` (comparator) | 3,040 | 1,599 / 590 | −6.88% | −26.87 | [−7.39, −6.41] | 674 / 555 | −0.118 | [−0.197, −0.035] | 1,408 | comparator, no look |

**Change since 11-16:**

- **P1.** n went from 133 / 101 games to 188 / 142. CLV went from −0.30% to −0.18%, z from −0.64 to −0.48.
- **P2.** n went from 413 / 270 to 563 / 375. CLV went from −2.20% to −2.04%, z from −7.12 to −7.71.
- **C0.** CLV went from −7.03% to −6.88%.
- P1's daily `GATE_READ` mean moved within −0.42..−0.18% all week. P2's moved within −2.26..−2.04%.

Reported, never decisive (prereg §7):

- **By venue.**
  - P1: Kalshi 158 bets / 112 games, −0.38%; Polymarket 30 / 30, +0.88% (z 1.47).
  - P2: Kalshi 446 / 271, **−2.46%** (z −7.86); Polymarket 117 / 105, −0.45%.
  - C0: Kalshi 1,413 / 437, −6.95%; Polymarket 186 / 165, −6.30%.
- **By sport (sharp-graded bets).**
  - P1: NFL 67 / 33, +0.05%; NBA 45 / 39, −0.71%; NHL 35 / 29, −0.36%; soccer 29 / 29, −0.30%; NCAAF 12 / 12, +1.34%.
  - P2: NBA 171 / 108, **−3.21%**; NHL 125 / 84, **−3.07%**; NFL 116 / 45, −1.24%; soccer 111 / 99, −0.83%;
    NCAAF 38 / 37, +0.34%; MLB 1 / 1; WNBA 1 / 1.
  - C0: NBA 615 / 176, −5.99%; NHL 544 / 136, −8.96%; NFL 174 / 51, −5.15%; soccer 133 / 115, −7.38%; NCAAF 123 / 108,
    −3.11%; WNBA 6 / 2; MLB 4 / 2.
- **By market family.**
  - P1: props 147 / 101, −0.28%; h2h 20 / 20, −0.44%; game_other 11 / 11, −0.31%; totals 9 / 9, +1.42%; spreads 1 / 1.
  - P2: props 412 / 237, **−2.62%** (z −7.86); h2h 75 / 75, −0.79%; game_other 36 / 35, −0.47%; totals 28 / 28, −0.58%;
    spreads 12 / 12, +1.80%.
  - P2's deficit still sits in Kalshi props (11-16: props −2.94% on 299 / 166). Its game lines are within about 0.8 pts of
    zero.
- **By σ source.**
  - P1: S1 76 / 70, −0.07%; S2 112 / 72, −0.25%.
  - P2: S1 265 / 213, −1.64%; S2 280 / 152, −2.42%; S3 18 / 18, −2.07%.
- **Price band 0.40–0.75.** P1 166 / 124, −0.22%. P2 493 / 328, −1.96%. C0 1,304 / 504, −5.81%.
- **Stake-weighted (§4 sizing), CLV / ROI.** P1 +0.71% / +0.056. P2 +1.04% / +0.047. C0 +0.41% / −0.311.
- **Against C0, on the axes both booked.**
  - P1 − C0: n 75 / 64 games, +4.17 pts, CI [+1.72, +6.74] (11-16: +4.31 on 55 / 46).
  - P2 − C0: n 206 / 166, +3.17 pts, CI [+1.82, +4.53] (11-16: +3.03 on 154 / 118).
- **Consensus close, every graded bet.**
  - P1: 518 / 366 games, +0.10% [−0.24, +0.42].
  - P2: 1,300 / 771, −0.97% [−1.26, −0.68].
  - C0: 2,909 / 964, −6.98% [−7.37, −6.64].

**Season phases.** Phases are not pooled except where the registered statistic pools by design.

- **NBA, NHL, NFL and NCAAF** are in the regular season.
- **NCAAB and WNCAAB** are in the early regular season.
- **Soccer is back.** The first soccer bet since 11-08 was booked 11-18 10:45 PM CST. This fits the November international
  window ending, but **I did not verify the calendar.** Since 11-16, soccer booked P1 7, P2 34, C0 54. `bets.jsonl` has no
  competition field, so soccer cannot be split by competition.
- **MLB and WNBA** are over. The pooled P2 gate still carries their two old postseason bets.

## 3. Booking rate (from `bets.jsonl`, 11-16 9:39 AM to 11-23 9:35 AM CST)

1,389 bets were booked: P1 139, P2 362, C0 888 (11-16 week: 149 / 395 / 888).

- 762 builds were processed. 423 booked at least one bet: P1 on 105, P2 on 238, C0 on 340.
- **Failed gates, summed over builds:** outside the decision window 292,029; one-sided fair 47,359; not pregame 37,336;
  implausible venue price 10,893; stale quote 4,475.

| Central day | P1 all (gate-eligible* / NCAAB / WNCAAB) | P2 all (gate-eligible* / NCAAB / WNCAAB) | C0 all (gate-eligible* / NCAAB / WNCAAB) |
|---|---|---|---|
| 11-16 (from 9:39 AM) | 15 (8 / 7 / 0) | 24 (19 / 5 / 0) | 66 (59 / 6 / 1) |
| 11-17 | 11 (8 / 2 / 1) | 35 (22 / 12 / 1) | 119 (104 / 12 / 3) |
| 11-18 | 20 (14 / 5 / 1) | 49 (25 / 23 / 1) | 125 (111 / 14 / 0) |
| 11-19 | 24 (18 / 6 / 0) | 49 (37 / 11 / 1) | 102 (89 / 11 / 2) |
| 11-20 | 10 (6 / 3 / 1) | 42 (25 / 16 / 1) | 128 (110 / 17 / 1) |
| 11-21 (Sat) | 24 (24 / 0 / 0) | 85 (64 / 21 / 0) | 159 (137 / 21 / 1) |
| 11-22 (Sun) | 31 (29 / 2 / 0) | 63 (52 / 9 / 2) | 139 (124 / 11 / 4) |
| 11-23 (to 9:35 AM) | 4 (3 / 0 / 1) | 15 (7 / 7 / 1) | 50 (46 / 3 / 1) |

\* "Gate-eligible" here excludes NCAAB, WNCAAB, MLB and WNBA (none of which can be sharp-graded or are in season).

**Split, since 11-16:**

- **P1.** Kalshi 111, Polymarket 28. NHL 44, NBA 31, NCAAB 25, NFL 22, soccer 7, NCAAF 6, WNCAAB 4. Props 93, game lines 46.
  σ: S2 78, S1 55, S3 6. 103 events.
- **P2.** Kalshi 246, Polymarket 116. NCAAB 104, NHL 85, NBA 76, NFL 38, soccer 34, NCAAF 18, WNCAAB 7. Props 187, game
  lines 175. σ: S2 210, S1 121, S3 31. 249 events.
- **C0.** Kalshi 732, Polymarket 156. NBA 336, NHL 255, NCAAB 95, NCAAF 87, soccer 54, NFL 48, WNCAAB 13. 321 events.
- **College basketball** is 21% of P1's bookings this week (29 of 139; 11-16 week: 41%) and 31% of P2's (111 of 362).

**Gate-eligible daily rate**, over the six full days 11-17..11-22:

- P1: 8 + 14 + 18 + 6 + 24 + 29 = 99, **16.5 a day** (11-16: 13.2).
- P2: 22 + 25 + 37 + 25 + 64 + 52 = 225, **37.5 a day** (11-16: 41.2).
- C0: 104 + 111 + 89 + 110 + 137 + 124 = 675, **112.5 a day** (11-16: 113.0).

### Projection to the next look (PROJECTIONS, not results)

**Sharp-graded share,** on FINAL grades of gate-eligible bets booked since 11-16:

- P1 55 of 87 (**0.632**; 11-16: 0.545). By sport, NCAAB included for scale: NFL 18/20, NCAAF 5/5, soccer 6/7, NHL 16/31,
  NBA 10/24, NCAAB 0/23, WNCAAB 0/3.
- P2 147 of 200 (**0.735**; 11-16: 0.600). NFL 32/34, NCAAF 10/10, soccer 26/27, NBA 42/64, NHL 37/65, NCAAB 0/63, WNCAAB 0/4.
- C0 455 of 622 (0.732).
- The share rose mainly because soccer came back (32 of 34 sharp-graded across P1 + P2).

| | now n / games | sharp-graded a day (rate × share) | n to next look | days | projected first nightly with the next look | cross-check: read-to-read pace 11-16 → 11-23 | 11-16 projection |
|---|---|---|---|---|---|---|---|
| P1 → L1 (400 / 100) | 188 / 142 | 16.5 × 0.632 = 10.4 | 212 | 212 / 10.4 = 20 | **~Sun 12-13** | (188 − 133) / 7 = 7.9 a day → 27 d → ~12-20 | ~12-23 (pace ~01-05) |
| P2 → L2 (800 / 200) | 563 / 375 | 37.5 × 0.735 = 27.6 | 237 | 237 / 27.6 = 9 | **~Wed 12-02** | (563 − 413) / 7 = 21.4 a day → 11 d → ~12-04 | ~12-02 (pace ~12-07) |
| P2 → L3 (1,200 / 300) | — | 27.6 | 637 | 637 / 27.6 = 23 | **~12-16** | 637 / 21.4 = 30 d → ~12-23 | ~12-18 (pace ~12-29) |
| C0 | 1,599 / 590 | — | — | — | comparator, no look | — | — |

- **Games are not binding.** P1 has 142 games, past L1's 100. P2 has 375, past L3's 300.
- **Every remaining look still projects before 2027-01-31.** P1's L1 has moved earlier by about 10 days and now has about
  6–7 weeks to spare. (The 11-02 projection was P1 L1 ~12-21; it is now ~12-13..12-20.)
- **What would move these dates:** college basketball (it never counts), weekends (P1 booked 24 and 29 gate-eligible
  bets on Sat/Sun against 6–18 on weekdays), soccer's run of fixtures and holiday breaks, and Pinnacle coverage of NBA
  and NHL props (about half of them carry no sharp close).

### NCAAB (consensus close only, NOT in the gate population)

NCAAB went onto Kalshi on 2026-11-04 at 00:46Z (11-03 6:46 PM CST). NCAAB quotes carry no Pinnacle price, so every NCAAB bet
grades on the consensus close only (`no_pinnacle_close_at_this_line`). **None counts toward a look.**

The CIs below are my own game-clustered bootstrap from `grades.json` (2,000 resamples). They are FINAL grades only and
cover every NCAAB bet since 11-04.

| strategy | NCAAB bets / games | venue | graded | sharp close | consensus CLV, final (n / games) | 95% CI | 11-16 |
|---|---|---|---|---|---|---|---|
| P1 | 115 / 113 | Kalshi 55, Polymarket 60 | 115 | 0 | **+0.45%** (108 / 106) | [+0.07, +0.79] | +0.68% (71 / 69) |
| P2 | 282 / 259 | Kalshi 111, Polymarket 171 | 275 | 0 | −0.60% (213 / 198) | [−1.31, +0.03] | −0.38% (122 / 114) |
| C0 | 234 / 214 | Kalshi 111, Polymarket 123 | 231 | 0 | −7.93% (176 / 162) | [−9.68, −6.24] | −9.58% (102 / 92) |

P1's NCAAB consensus CLV CI still excludes zero but has narrowed toward it (+0.68% → +0.45%). The consensus close is not the
registered gate statistic and is not a sharp reference; this is reported, not a result.

WNCAAB has the same property: lifetime P1 13 / 13 games (+1.23% consensus), P2 19 / 19 (+2.14%), C0 36 / 34 (−6.10%); none
sharp-graded, none counted.

## 4. ev_lb funnel on the current files (post hoc, read-only; `scripts/ev_lb_funnel_read.py` on fleet `05a2ce65e`)

**Input.** Only that morning's current record files:

- `2026-11-23.json.gz`: build `|1795448621`, written 9:43 AM CST. 1,259 candidates, 556 eligible.
- `2026-11-24.json.gz`: build `|1795448224`, written 9:37 AM CST. 678 candidates, 79 eligible.

**Gates and qualifiers.** Of the 1,937 candidates, the gates removed 1,182 outside the window, 114 one-sided fair and 6
stale quotes. The snapshots qualify P1 1, P2 1 and C0 28.

**Buckets, 635 eligible candidate-sides.** g = consensus − ask, f = fee, h = haircut, all in probability points.

| | n | A ask ≥ consensus | B fee eats | C haircut eats | D qualifies |
|---|---|---|---|---|---|
| **all, 11-23** | 635 | 78.9% (501) | 19.1% (121) | 1.9% (12) | **0.2% (1)** |
| all, 11-16 | 290 | 74.8 | 19.3 | 5.9 | 0 |
| all, 11-09 | 360 | 71.1 | 27.5 | 1.4 | 0 |
| all, 11-02 | 367 | 79.0 | 18.5 | 2.2 | 0.3 |
| Kalshi | 408 | 76.7 | 21.3 | 1.7 | 0.2 (1) |
| Polymarket | 227 | 82.8 | 15.0 | 2.2 | 0 |
| NHL | 247 | 81.0 | 17.4 | 1.6 | 0 |
| NCAAB | 147 | 74.8 | 21.1 | 4.1 | 0 |
| soccer | 114 | 78.9 | 20.2 | 0.9 | 0 |
| NBA | 48 | 83.3 | 14.6 | 2.1 | 0 |
| NCAAF | 32 | 62.5 | 37.5 | 0 | 0 |
| WNCAAB | 25 | 96.0 | 4.0 | 0 | 0 |
| NFL | 22 | 77.3 | 18.2 | 0 | 4.5 (1) |

- The one D line is an NFL Kalshi prop on S2.
- **g and the fee.** g has median −1.11 pts, p90 +0.68 and max +2.83 (11-16: −0.62 / +0.98 / +2.53). The fee median is
  1.69 pts. 13 of 635 lines are net-positive before the haircut, and 2 would qualify at half the haircut.
- **Haircut median by σ source:**

  | σ source | lines (of 635) | 11-23 median | 11-16 | 11-09 | 11-02 |
  |---|---|---|---|---|---|
  | all | 635 | **1.29 pts** | 1.10 | 1.08 | 1.33 |
  | S1 `fair_v1` | 373 | 1.43 | 1.28 | 1.29 | 1.40 |
  | S2 dispersion | 225 | 0.91 | 0.98 | 1.02 | 1.08 |
  | S3 inflated | 37 | 4.05 | 4.02 | 4.22 | 3.76 |

- **A + B = 98.0%** (11-16: 94.1%; 11-09: 98.6%; 11-02: 97.5%). Last week's bucket C bump (5.9%, mostly NCAAB game lines)
  did not repeat: C is 1.9%, NCAAB C 4.1%. The 10-27 funnel reading (A + B dominate; the taker side is efficient after
  fees) stands.
- **Why D is about 0 here while P1 books about 16 a day.** Each line is decided once, at the first qualifying build, out of
  96 builds a day, while the funnel sees one snapshot per file (prereg §9).
- Scratch output: `C:\tmp\phase2_read_1123\funnel\report.json` and `candidates.csv`.

## 5. Grading health

**Nightly grading has run.** There were seven `PAPER_GRADED` lines since 11-16:

| read | bets graded | with a sharp close | with an outcome |
|---|---|---|---|
| 11-17 | 433 | 56 | 159 |
| 11-18 | 385 | 83 | 108 |
| 11-19 | 375 | 68 | 125 |
| 11-20 | 396 | 95 | 130 |
| 11-21 | 346 | 66 | 131 |
| 11-22 | 450 | 142 | 243 |
| 11-23 | 495 | 167 | 188 |

**`grades.json` holds 4,921 graded bets** of the 4,996 in the store (4,671 final).

- 2,350 have a sharp close.
- **2,571 (52.2%) have none.** Every one gives the reason `no_pinnacle_close_at_this_line`. On 11-16 it was 1,882 of 3,560
  (52.9%).
- 4,727 have a consensus close.

**Where the sharp close is missing,** as final bets without one / all final bets, by sport and kind:

| sport and kind | without / final | share missing |
|---|---|---|
| NCAAB games | 548 / 548 | 100%, by design |
| WNCAAB games | 58 / 58 | 100% |
| NHL games | 57 / 57 | 100% (no Pinnacle NHL game lines, prereg §9) |
| MLB props / games | 114 / 114, 5 / 10 | season over |
| WNBA props / games | 37 / 43, 4 / 5 | season over |
| NBA props | 822 / 1,653 | 50% |
| NCAAF games | 167 / 340 | 49% |
| NHL props | 340 / 1,044 | 33% |
| soccer games | 110 / 381 | 29% |
| NFL props | 61 / 418 | 15% |

**Selection check on moved lines (prereg §9)**, from the read: bets without a sharp close, against the consensus close,
NCAAB included.

- P1's 343 show **+0.32%** (330 / 256 games, CI [−0.06, +0.69]). 11-16: +0.46% [+0.03, +0.89]. The CI now crosses zero.
- P2's 820 show −0.67% (738 / 537, CI [−1.02, −0.33]). 11-16: −0.63%.

**Outcome grades.** 1,368 bets have an outcome grade. 3,525 have no outcome grader (props and `game_other`), 25 are
`no_chip_match` (11-16: 7) and 3 are not final. As registered, ROI covers full-game lines only. The `no_chip_match` rise
(7 → 25) is small but is the one grading count that grew faster than the store; I did not trace it.

**No `CHIPS_UNREADABLE`, `NO_BOOK` or error line appeared in either log.**

## 6. What this does and does not say

- **No look was taken this week.** P1 has not reached L1; `NOT_YET` is its status. P2 failed L1 on 11-16 and waits for L2.
  Live is unchanged: canary stays.
- **Projections:** P2's L2 ~12-02..12-04; P1's L1 ~12-13..12-20; P2's L3 ~12-16..12-23. All before 2027-01-31.
- **Evidence that could motivate a NEW registration** (named, not recommended; the user's decision):
  - **P2 is still about −2% against Pinnacle** (z −7.71 at 563 / 375). Reaching +2.783 at L2 (800) would need the next ~237
    sharp-graded bets to average far above anything P2 has shown. No futility rule was registered; stopping early is a new
    decision.
  - **P2's deficit is Kalshi props, NBA and NHL** (props −2.62% on 412 / 237; Kalshi −2.46% vs Polymarket −0.45%; NBA −3.21%,
    NHL −3.07%). Its game lines are near zero.
  - **P1 is near zero against Pinnacle** (−0.18% [−0.91, +0.53] on 188 / 142) while beating C0 by +4.17 pts [+1.72, +6.74]
    on shared axes. Its stake-weighted CLV is +0.71%. None of these is the gate.
  - **NCAAB has no sharp close at all.** P1's NCAAB consensus CLV is +0.45% [+0.07, +0.79] on 108 / 106 games, narrower
    than last week.
  - **Bucket A + B = 98.0%.** The taker side is still efficient after fees.
- **Next registered read: Mon 2026-11-30.**

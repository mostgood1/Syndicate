# Decision policy v1 PAPER — weekly Monday read, 2026-11-09 `[lane decision-policy-paper, todo #738, umbrella #736]`

**Scheduled, read-only run** (task `decision-policy-paper-weekly-read`, the `#717` weekly line). It started 9:40 AM CST,
on time. Prereg `8d16ab07` (`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md`). Previous read:
`.syndicate/findings_2026-11-02_decision_policy_first_read.md`. Every comparison below is against it.

Nothing was changed: no rule, parameter, z, env, code, fleet job or file in the paper store. `run_decision_policy_paper.py`
was not run. The evaluator ran WITHOUT `--run`. Every fleet command ran at `nice -n 19`. All times are US Central (CST).

**No look has been taken by either candidate.** `looks.json` is unchanged: `ev_lb` and `net_floor_719` both have
`looks: []`, `closed: null`, `passed: null` (sha256 `43c100bd…`).

**Verdict: `NOT_YET`.** L1 needs 400 sharp-graded bets on 100 games. P2 has 284 on 199 games and P1 has 96 on 74. The
gate has not been read, and nothing below is a result of it.

## 1. The jobs ran

- **The nightly.** The 7:45 AM CST nightly wrote `reads/2026-11-09.json` (read_at 7:45:39 AM CST). It logged
  `PAPER_GRADED` and three `GATE_READ` lines.
  - The nightly ran on all 7 mornings since the last read (11-03 to 11-09). There was one `PAPER_GRADED` line and three
    `GATE_READ` lines each morning.
  - There were no error lines. The only other line is the routine `HTTP_COMPRESSION` stat.
- **The book job.** `job-decision-policy-paper.log` covers 11-02 9:28 AM to 11-09 9:37 AM. Over that span:
  - There were 673 run headers, so the job ran every 15 minutes.
  - It wrote **676 `PAPER_BOOKED` lines**, **0 `MODE_OFF`** and **0 error / `CHIPS_UNREADABLE` / `NO_BOOK` lines**.
  - Some runs logged no line. These are the visible 30–75 min gaps between `PAPER_BOOKED` lines, densest on the 11-07
    and 11-08 evenings. The run header is still there each 15 min, so the job ran on schedule. I read these as
    runs with no new build. I did not check that in the code.
  - Other runs logged two lines, one each for D and D+1. `builds.jsonl` has 676 builds since the last read.
- **Fleet checkout.** `8fc72076d` (11-09 8:20 AM CST ff, `#772`). It contains both read scripts.

## 2. Gate read (prereg §7), read 11-09 7:45 AM CST

Command: `evaluate_decision_policy_paper.py --date 2026-11-09` (read-only, no `--run`).

- CLV is fee-net CLV against the Pinnacle close, in %. z is the game-clustered Z.
- CI is the game-clustered bootstrap 95% CI.
- ROI is flat, per unit, on full-game lines only.

| strategy | bets | sharp-graded n / games | CLV mean | z | CLV 95% CI | ROI flat n / games | ROI mean | ROI 95% CI | no sharp close | look |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 `ev_lb` | 246 | 96 / 74 | −0.39% | −0.68 | [−1.57, +0.66] | 65 / 65 | +0.169 | [+0.012, +0.331] | 146 | waiting (L1 400 / 100) |
| P2 `net_floor_719` | 638 | 284 / 199 | −1.85% | −5.14 | [−2.58, −1.13] | 213 / 198 | +0.069 | [−0.059, +0.197] | 345 | waiting (L1 400 / 100) |
| C0 `suggested_2pct` (comparator) | 1,281 | 690 / 291 | −7.30% | −15.08 | [−8.28, −6.38] | 272 / 227 | −0.160 | [−0.276, −0.039] | 571 | comparator, no look |

**Change since 11-02:**

- **P1.** n went from 36 / 30 games to 96 / 74. CLV went from +0.11% to −0.39%, and z from +0.15 to −0.68.
- **P2.** n went from 95 / 67 games to 284 / 199. CLV went from −2.33% to −1.85%, and z from −3.69 to −5.14.
- **C0.** CLV went from −6.96% to −7.30%.

These are interim figures. Under the registered design they decide nothing.

**ROI.** P1's flat-ROI CI excludes zero (65 bets / 65 games). ROI is never the gate (§7: "Then ROI" applies at a pass
only), and 65 outcomes is a small sample.

**The L1 boundary for comparison.** It is **Z ≥ 3.935**. P2's interim z is −5.14. This is stated for scale only; no look
has been taken.

Reported, never decisive (prereg §7):

- **By venue.**
  - P1: Kalshi 74 bets / 52 games, −0.73%; Polymarket 22 / 22, +0.75%.
  - P2: Kalshi 199 / 124, −2.43%; Polymarket 85 / 76, −0.50%.
  - C0: Kalshi 587 / 206, −7.45%; Polymarket 103 / 92, −6.47%.
- **By sport (sharp-graded bets).**
  - P1:
    - NFL 37 / 19, −0.55%
    - soccer 23 / 23, −0.20%
    - NBA 22 / 20, −0.62%
    - NHL 8 / 6, −0.39%
    - NCAAF 6 / 6, +0.65%
  - P2:
    - soccer 84 / 75, −0.59%
    - NBA 77 / 50, −2.92%
    - NFL 57 / 23, −2.37%
    - NHL 42 / 28, −2.85%
    - NCAAF 22 / 21, −0.24%
    - MLB 1 / 1
    - WNBA 1 / 1
  - C0:
    - NBA 236 / 81, −6.06%
    - NHL 207 / 51, −10.68%
    - NFL 94 / 27, −5.04%
    - soccer 92 / 82, −6.55%
    - NCAAF 51 / 46, −2.84%
    - WNBA 6 / 2
    - MLB 4 / 2
- **By market family.**
  - P1: props 67 / 45, −0.55%; h2h 15 / 15, −0.59%; game_other 9 / 9, −0.43%; totals 5 / 5, +2.40%.
  - P2: props 176 / 101, **−2.73%** (z −5.52); h2h 54 / 54, −0.40%; game_other 28 / 27, −0.60%; totals 20 / 20,
    −0.76%; spreads 6 / 6, +1.14%.
  - P2's negative mean sits in props. Its game lines are within about half a point of zero.
- **By σ source.**
  - P1: S1 37 / 35, −0.10%; S2 59 / 39, −0.57%.
  - P2: S1 141 / 118, −0.99%; S2 131 / 74, −2.75%; S3 12 / 12, −2.24%.
- **Price band 0.40–0.75.** P1 83 / 63, −0.51%. P2 248 / 175, −1.84%. C0 556 / 233, −5.65%.
- **Stake-weighted (§4 sizing), CLV / ROI.**
  - P1: +0.68% / +0.080.
  - P2: +0.82% / +0.107.
  - C0: −0.13% / −0.011.
- **Against C0, on the axes both booked.**
  - P1 − C0: n 36 / 31 games, +3.11 pts, CI [−0.21, +6.69]. On 11-02 it was +9.10 on 8 bets.
  - P2 − C0: n 99 / 79, +3.57 pts, CI [+1.81, +5.48].
- **Consensus close, every graded bet.**
  - P1: 234 / 150 games, +0.09% [−0.52, +0.65].
  - P2: 585 / 332, −1.14% [−1.59, −0.70].
  - C0: 1,217 / 426, −8.04% [−8.81, −7.34].

**Season phases.** Phases are not pooled except where the registered statistic pools by design.

- **NBA, NHL, NFL and NCAAF** are in the regular season.
- **NCAAB and WNCAAB** are in the early regular season. Their tip-off was the week of 11-03.
- **Soccer.** `bets.jsonl` has no competition field, so soccer cannot be split by competition here. I did not
  reconstruct it from event ids.
- **MLB and WNBA** are over. Neither booked a bet since 11-02. The pooled gate still carries their two old P2 bets
  (1 MLB, 1 WNBA, both postseason). P1 has none.

## 3. Booking rate (from `bets.jsonl`, 11-02 9:28 AM to 11-09 9:37 AM CST)

1,328 bets were booked: P1 139, P2 380, C0 809. The store's lifetime total is 2,181.

- 676 builds were processed. 366 of them booked at least one bet: P1 on 101, P2 on 230, C0 on 286.
- **Failed gates, summed over builds:**
  - outside the decision window 236,065
  - one-sided fair 39,817
  - not pregame 18,848
  - implausible venue price 4,262
  - stale quote 2,326
  - wrong-date contract 155

| Central day | P1 all (gate-eligible / NCAAB) | P2 all (gate-eligible / NCAAB) | C0 all (gate-eligible / NCAAB) |
|---|---|---|---|
| 11-02 (from 9:28 AM) | 13 (13 / 0) | 32 (32 / 0) | 80 (80 / 0) |
| 11-03 | 15 (15 / 0) | 33 (33 / 0) | 76 (76 / 0) |
| 11-04 | 9 (5 / 4) | 40 (33 / 7) | 120 (117 / 3) |
| 11-05 | 31 (14 / 17) | 65 (43 / 22) | 143 (125 / 18) |
| 11-06 | 15 (7 / 8) | 60 (46 / 14) | 121 (109 / 12) |
| 11-07 (Sat) | 22 (18 / 4) | 76 (67 / 9) | 120 (108 / 12) |
| 11-08 (Sun) | 29 (28 / 1) | 65 (56 / 9) | 119 (110 / 9) |
| 11-09 (to 9:37 AM) | 5 (2 / 3) | 9 (6 / 3) | 30 (24 / 6) |

"Gate-eligible" here means every sport except NCAAB, WNCAAB, MLB and WNBA. WNCAAB's handful of bets (P1 1, P2 2, C0 7)
sit in "all" only.

**Split, since 11-02:**

- **P1.**
  - Venue: Kalshi 98, Polymarket 41.
  - Sport: NCAAB 37, NHL 29, NFL 26, NBA 22, soccer 20, NCAAF 4, WNCAAB 1.
  - Kind: 72 props, 67 game lines.
  - σ source: S2 74, S1 51, S3 14.
  - 112 events.
- **P2.**
  - Venue: Kalshi 250, Polymarket 130.
  - Sport: NHL 97, soccer 79, NBA 69, NCAAB 64, NFL 43, NCAAF 26, WNCAAB 2.
  - Kind: 195 props, 185 game lines.
  - 242 events.
- **C0.**
  - Venue: Kalshi 671, Polymarket 138.
  - Sport: NHL 276, NBA 263, soccer 80, NCAAF 66, NCAAB 60, NFL 57, WNCAAB 7.
  - 299 events.
- **The shape has changed since 11-02.** MLB carried P1 then (35 of 108). Now P1's volume is NFL, NHL, NBA and soccer, plus
  NCAAB, and P1 books about half game lines (11-02: 15 of 108).

**Gate-eligible daily rate,** over the six full days 11-03..11-08:

- P1: 15 + 5 + 14 + 7 + 18 + 28 = 87, less 1 WNCAAB = 86 bets, **14.3 a day**. On 11-02 it was 10.8.
- P2: 276, **46.0 a day**. On 11-02 it was 30.7.
- C0: 638, **106.3 a day**. On 11-02 it was 62.8.

### Projection to the next look (PROJECTIONS, not results)

**Sharp-graded share,** on FINAL grades of bets booked since 11-02, NCAAB and WNCAAB excluded:

- P1 60 of 85 (0.706). By sport: NFL 24/25, soccer 16/17, NBA 9/15, NHL 8/25, NCAAF 3/3.
- P2 178 of 253 (0.704). By sport: NFL 34/34, soccer 57/64, NBA 36/57, NHL 37/81, NCAAF 14/17.
- C0 447 of 621 (0.720).

The all-time share outside MLB and WNBA, again without NCAAB, is lower: P1 0.632, P2 0.627, C0 0.653. That is because
it includes the earlier NBA props.

| | now n / games | sharp-graded a day (rate × share) | n to next look | days | projected first nightly with the next look | cross-check: read-to-read pace 11-02 → 11-09 | 11-02 projection |
|---|---|---|---|---|---|---|---|
| P1 (L1 400 / 100) | 96 / 74 | 14.3 × 0.706 = 10.1 | 304 | 304 / 10.1 = 30 | **~Wed 12-09** | (96 − 36) / 7 = 8.6 a day → 35 d → ~12-14 | ~12-21 |
| P2 (L1 400 / 100) | 284 / 199 | 46.0 × 0.704 = 32.4 | 116 | 116 / 32.4 = 3.6 | **~Fri 11-13** (the look is the first 7:45 AM nightly with n ≥ 400; grading lags the game by ~1 day) | (284 − 95) / 7 = 27.0 a day → 4.3 d → ~11-14 | ~11-17 |
| C0 | 690 / 291 | — | — | — | comparator, no look | — | — |

- **Games are not binding.**
  - P1 has 74 games and grows (74 − 30) / 7 = 6.3 a day, so it reaches 100 near 11-13.
  - P2 already has 199.
- **P2 beyond L1** (same arithmetic; projections):
  - L2 (800 / 200): 516 / 32.4 = 16 d, **~11-25**. Cross-check 516 / 27.0 = 19 d, ~11-28.
  - L3 (1,200 / 300): 916 / 32.4 = 28 d, **~12-07**. Cross-check ~12-13. Games reach 300 at about 18.9 a day, near 11-15.
  - So P2's registered test is projected to reach its final count-based look well before the 2027-01-31 read.
- **Both candidates still project to L1 before 2027-01-31.** P1 has about 7–8 weeks to spare (11-02: 5–6).
- **What would move these dates:**
  - **NCAAB.** It is now 27% of P1's bets since 11-02 (37 of 139), and none count toward the gate.
  - **The weekend.** Rates are higher on weekends (P1 18 and 28 on Sat/Sun against 5–15 on weekdays).
  - **Sharp share by sport.** NHL props draw a Pinnacle close on only 8 of 25 (P1) and 37 of 81 (P2) bets. A slate tilting
    to NHL lowers the share.
  - **Pinnacle coverage.** The D5 swap (lane `pinnacle-coverage-d5`) would move the share.

### NCAAB (consensus close only, NOT in the gate population)

NCAAB went onto Kalshi on 2026-11-04 at 00:46Z (11-03 6:46 PM CST). NCAAB quotes carry no Pinnacle price, so every NCAAB bet
grades on the consensus close only (`no_pinnacle_close_at_this_line`). **None counts toward a look.**

The CIs below are my own game-clustered bootstrap from `grades.json` (2,000 resamples). They are FINAL grades only.

| strategy | NCAAB bets / games | venue | graded | sharp close | consensus CLV, final (n / games) | 95% CI |
|---|---|---|---|---|---|---|
| P1 | 37 / 37 | Kalshi 20, Polymarket 17 | 34 | 0 | +0.38% (27 / 27) | [−0.09, +0.79] |
| P2 | 64 / 59 | Kalshi 26, Polymarket 38 | 61 | 0 | −0.48% (35 / 34) | [−1.63, +0.51] |
| C0 | 60 / 55 | Kalshi 29, Polymarket 31 | 54 | 0 | −9.53% (29 / 29) | [−14.11, −5.65] |

WNCAAB (women's college basketball, also on the slate) has the same property. It has P1 1, P2 2 and C0 7 bets, none
sharp-graded.

## 4. ev_lb funnel on the current files (post hoc, read-only; `scripts/ev_lb_funnel_read.py` on fleet `8fc72076d`)

**Input.** Only that morning's current record files:

- `2026-11-09.json.gz`: build `|1794238836`, written 9:40 AM CST. 739 candidates, 328 eligible.
- `2026-11-10.json.gz`: build `|1794236434`, written 9:00 AM CST. 381 candidates, 32 eligible.

**Gates and qualifiers.** Of the 1,120 candidates, the gates removed 685 outside the window, 72 one-sided fair and
3 stale quotes. The snapshots qualify P1 0, P2 2 and C0 13.

**Buckets, 360 eligible candidate-sides.** g = consensus − ask, f = fee, h = haircut, all in probability points.

| | n | A ask ≥ consensus | B fee eats | C haircut eats | D qualifies |
|---|---|---|---|---|---|
| **all, 11-09** | 360 | 71.1% (256) | 27.5% (99) | 1.4% (5) | **0 (0)** |
| all, 11-02 | 367 | 79.0 | 18.5 | 2.2 | 0.3 (1) |
| Kalshi | 283 | 71.4 | 27.2 | 1.4 | 0 |
| Polymarket | 77 | 70.1 | 28.6 | 1.3 | 0 |
| NCAAB | 126 | 70.6 | 27.8 | 1.6 | 0 |
| NHL | 92 | 69.6 | 29.3 | 1.1 | 0 |
| NBA | 81 | 82.7 | 16.0 | 1.2 | 0 |
| NCAAF | 38 | 60.5 | 39.5 | 0 | 0 |
| NFL | 23 | 56.5 | 39.1 | 4.3 | 0 |

- **No soccer line was eligible** in either snapshot. The 360 are NCAAB, NHL, NBA, NCAAF and NFL only.
- **g and the fee.**
  - g has median −0.74 pts, p90 +0.84 and max +2.32. On 11-02 these were −0.89 / +0.64 / +3.12.
  - The fee median is 1.71 pts.
  - 5 of 360 lines are net-positive before the haircut, and 3 would qualify at half the haircut.
- **Haircut median by σ source:**

  | σ source | lines (of 360) | 11-09 median | 11-02 |
  |---|---|---|---|
  | all | 360 | **1.08 pts** | 1.33 |
  | S1 `fair_v1` | 128 | 1.29 | 1.40 |
  | S2 dispersion | 217 | 1.02 | 1.08 |
  | S3 inflated | 15 | 4.22 | 3.76 |

  - **S1's share fell** from 269 of 367 (73%) to 128 of 360 (36%).
  - The new NCAAB lines (126) go mostly to S2. NCAAB game lines have the lowest haircut median, 0.76 pts.
- **A + B = 98.6%** (11-02: 97.5%; 10-27: 97.9%). The mass moved from A to B: more lines sit just under consensus and are
  eaten by the fee, rather than priced above consensus outright. Neither bucket depends on σ. The 10-27 funnel reading
  stands.
- **Why D = 0 here while P1 still books 14 a day.** Each line is decided once, at the first qualifying build, out of
  96 builds a day, while the funnel sees one snapshot per file. P1's bets come from that transient tail (prereg §9).
- Scratch output: `C:\tmp\phase2_read_1109\funnel\report.json` and `candidates.csv`.

## 5. Grading health

**Nightly grading has run.** There were seven `PAPER_GRADED` lines since 11-02, all at about 7:45 AM CST:

| read | bets graded | with a sharp close | with an outcome |
|---|---|---|---|
| 11-03 | 312 | 116 | 53 |
| 11-04 | 235 | 70 | 26 |
| 11-05 | 278 | 84 | 40 |
| 11-06 | 363 | 132 | 106 |
| 11-07 | 339 | 56 | 136 |
| 11-08 | 451 | 114 | 257 |
| 11-09 | 484 | 161 | 191 |

**`grades.json` holds 2,132 graded bets** of the 2,181 in the store (1,917 final).

- 1,070 have a sharp close.
- **1,062 (50%) have none.** Every one gives the reason `no_pinnacle_close_at_this_line`. On 11-02 it was 455 of 796 (57%).
- 2,036 have a consensus close.

**Where the sharp close is missing,** as final bets without one / all final bets, by sport and kind:

| sport and kind | without / final | share missing |
|---|---|---|
| NCAAB games | 101 / 101 | 100%, by design |
| WNCAAB games | 4 / 4 | 100% |
| MLB | 119 / 124 | about all, season over |
| WNBA | 41 / 48 | about all, season over |
| NBA props | 290 / 625 | 46% |
| NCAAF games | 53 / 132 | 40% |
| NHL props | 123 / 380 | 32% |
| soccer games | 81 / 280 | 29% |
| NFL props | 23 / 211 | 11% |

**Selection check on moved lines (prereg §9).** This compares bets without a sharp close against the consensus close.
NCAAB is included.

- P1's 146 bets show **+0.69%** (138 / 90 games, CI [+0.07, +1.29]).
- P2's 345 show −0.76% (301 / 196, CI [−1.37, −0.21]).
- On 11-02 these were +0.90% and −0.49%.
- P1's no-sharp bets still do better against consensus than its sharp-graded bets do against Pinnacle. This is the
  selection effect the prereg said to watch.

**Outcome grades.**

- 550 bets have an outcome grade.
- 1,456 are props with no outcome grader.
- 125 are `game_other`.
- 1 is `no_chip_match`.

As registered, ROI covers full-game lines only.

**No `CHIPS_UNREADABLE`, `NO_BOOK` or error line appeared in either log.**

## 6. What this does and does not say

- **The gate has not been read.** `NOT_YET` is the verdict. `looks.json` and every rule are unchanged.
- **P2 is projected to take its first registered look (L1, boundary 3.935) at about the 11-13 or 11-14 nightly.** P1's is
  projected for about 12-09 to 12-14. Both are projections.
  - The nightly takes the look, not this read.
  - A pass would not change live: canary stays, and any promotion is the user's decision (§7).
- **The volume risk has receded further.** The gate-eligible rate rose: P1 10.8 → 14.3 a day, P2 30.7 → 46.0. NCAAB adds
  volume that does not count.
- **Evidence that could motivate a NEW registration** (named, not recommended; the user's decision):
  - **P2's deficit is in props** (−2.73%, 176 bets / 101 games). Its game lines are near zero. A per-family rule would be
    a new registration, not a change to this one.
  - **NCAAB has no sharp close at all**, so NCAAB edge cannot reach this gate. A consensus-close gate for it would be a
    new registration.
  - **Bucket A + B = 98.6%.** The taker side is efficient after fees. The maker-side lead remains the one that changes
    both terms.
  - **The z-on-sharp-close refit** stays the first lever only if a candidate reaches a look and misses it on CLV.
- **Next registered read: Mon 2026-11-16.** P2's L1 is projected to have been taken by the nightly before then. If it
  has, that read puts the look first, verbatim from `looks.json`.

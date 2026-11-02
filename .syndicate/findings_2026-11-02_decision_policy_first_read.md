# Decision policy v1 PAPER — first registered Monday read, 2026-11-02 `[lane decision-policy-paper, todo #738, umbrella #736]`

**Scheduled, read-only run** (task `decision-policy-paper-first-read-1102`, the first `#717` Monday line). Prereg `8d16ab07`
(`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md`). Nothing was changed: no rule, parameter, z, env,
code, fleet job or file under the paper store. `run_decision_policy_paper.py` was not run; the evaluator ran WITHOUT `--run`.
Every fleet command ran at `nice -n 19`. All times are US Central (CDT to 11-01 02:00, CST after).

**Verdict: `NOT_YET`. No look has been taken by either candidate.** That is the expected state at this volume: L1 needs
400 sharp-graded bets on 100 games, and the best candidate has 95 on 67. Nothing below is a result of the gate.

## 1. The nightly ran

- The 7:45 AM CST nightly wrote `reads/2026-11-02.json` (read_at 7:45:51 AM CST) and logged one `PAPER_GRADED` and three
  `GATE_READ` lines in `logs/job-decision-policy-paper-nightly.log`. `looks.json`: both candidates `looks: []`, not closed.
- The book job (`job-decision-policy-paper.log`) has run every 15 min since 10-27 00:20 AM CDT: 617 `PAPER_BOOKED`,
  0 `MODE_OFF`, no error line.
- Fleet checkout `6c22ebfaa`; it contains `149936fe` (the funnel script).

## 2. Gate read (prereg §7), read 11-02 7:45 AM CST

`evaluate_decision_policy_paper.py --date 2026-11-02` (read-only). CLV = fee-net CLV vs the Pinnacle close, %; z is the
game-clustered Z; CI = game-clustered bootstrap 95%. ROI = flat, per unit, full-game lines only.

| strategy | bets | sharp-graded n / games | CLV mean | z | CLV 95% CI | ROI flat n / games | ROI mean | ROI 95% CI | no sharp close | look |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 `ev_lb` | 107 | 36 / 30 | +0.11% | +0.15 | [−1.46, +1.40] | 9 / 9 | +0.157 | [−0.31, +0.62] | 71 | waiting (L1: 400 / 100) |
| P2 `net_floor_719` | 255 | 95 / 67 | −2.33% | −3.69 | [−3.55, −1.18] | 54 / 50 | +0.141 | [−0.15, +0.42] | 154 | waiting (L1: 400 / 100) |
| C0 `suggested_2pct` (comparator) | 473 | 210 / 103 | −6.96% | −10.74 | [−8.31, −5.74] | 88 / 72 | −0.178 | [−0.38, +0.04] | 230 | comparator, no look |

Reported, never decisive (prereg §7):

- **By venue.** P1: Kalshi n 28 / 22 games, −0.25%; Polymarket 8 / 8, +1.38%.
  P2: Kalshi 68 / 42, −3.10%; Polymarket 27 / 26, −0.40%. C0: Kalshi 168 / 67, −6.45%; Polymarket 42 / 39, −8.98%.
- **By sport** (each sport is one season phase; MLB and WNBA are postseason, see below).
  - P1: NBA 13 / 13 games, −2.32%; NFL 13 / 7, +1.67%; soccer 7 / 7, +1.83%; NCAAF 3 / 3, −0.12%.
  - P2: NBA 38 / 24, −3.90%; NFL 23 / 11, −2.77%; soccer 23 / 21, −0.62%; NCAAF 7 / 7, +0.63%; NHL 2 / 2, −4.15%;
    MLB 1 / 1; WNBA 1 / 1.
  - C0: NBA 108 / 35, −7.07%; NFL 38 / 12, −5.95%; soccer 29 / 28, −6.34%; NCAAF 22 / 21, −4.39%; WNBA 6 / 2, −27.4%;
    MLB 4 / 2, −2.07%; NHL 3 / 3, −5.80%.
- **By σ source.** P1: S1 10 / 10, +1.25%; S2 26 / 20, −0.33%. P2: S1 31 / 29, −0.10%; S2 60 / 36, −3.29%;
  S3 4 / 4, −5.32%.
- **Price band 0.40–0.75.** P1 31 / 25, −0.01%; P2 86 / 58, −2.57%; C0 180 / 80, −6.10%.
- **Stake-weighted (§4 sizing).** CLV / ROI: P1 +1.79% / +0.223; P2 +1.46% / +0.260; C0 +2.33% / n.a.
- **Against C0 on axes both booked.** P1 − C0: n 8 / 7 games, +9.10 pts, CI [+0.79, +21.20].
  P2 − C0: n 31 / 24 games, +4.27 pts, CI [+1.02, +8.27].
- **Consensus close, every graded bet.** P1 103 / 47 games, +0.68% [−0.19, +1.57]; P2 223 / 102, −0.99% [−1.95, −0.17];
  C0 415 / 146, −7.91% [−9.16, −6.74].

**Season phases.** The registered statistic pools sports by design. MLB (124 bets, all World Series Rays–Brewers, last
booked 10-28) and WNBA (48 bets, all Dream–Valkyries, last game 10-31) are postseason. P1 has 0 sharp-graded bets from either.
P2 has 2 (1 MLB, 1 WNBA). Without them, recomputed from `grades.json` with the same clustered SE (no bootstrap CI):
P1 is unchanged; P2 n 93 / 65 games, −2.47%, z −3.91; C0 200 / 99, −6.44%, z −13.21. Neither sport books any more, so
the pooled figure becomes regular-season-only (NBA, NFL, NCAAF, NHL, soccer) from here on.

## 3. Booking rate (bets booked, from `bets.jsonl`, 10-27 00:20 AM CDT to 11-02 9:28 AM CST)

854 bets: P1 108, P2 262, C0 484. The rows added after the 7:45 AM read are why these counts exceed the read's.
617 builds were processed; 301 booked at least one bet (P1 on 76 builds, P2 on 181, C0 on 221).

| Central day | P1 `ev_lb` | P2 `net_floor_719` | C0 `suggested_2pct` |
|---|---|---|---|
| 10-27 (from 00:20) | 28 | 49 | 71 |
| 10-28 | 23 | 49 | 108 |
| 10-29 | 12 | 31 | 52 |
| 10-30 | 8 | 21 | 82 |
| 10-31 (Sat) | 15 | 53 | 68 |
| 11-01 (Sun) | 21 | 46 | 61 |
| 11-02 (to 9:28 AM) | 1 | 13 | 42 |

**Split.**

- **P1:** Kalshi 95, Polymarket 13. MLB 35, NBA 34, NFL 17, soccer 8, WNBA 7, NCAAF 5, NHL 2. 93 props, 15 game lines.
  σ: S2 90, S1 14, S3 4. 49 events.
- **P2:** Kalshi 199, Polymarket 63. NBA 83, soccer 55, MLB 45, NFL 34, WNBA 20, NCAAF 17, NHL 8. 185 props, 77 game lines.
  113 events.
- **C0:** Kalshi 379, Polymarket 105. NBA 220, soccer 64, NCAAF 55, NFL 48, MLB 44, NHL 32, WNBA 21. 484 bets, 170 events.

**Without MLB and WNBA** (both seasons over), the six full days 10-27..11-01 give:

- P1: 8 + 8 + 7 + 8 + 13 + 21 = 65 bets, **10.8 a day**.
- P2: 24 + 28 + 21 + 21 + 44 + 46 = 184, **30.7 a day**.
- C0: 377, **62.8 a day**.

### Projection to L1 (PROJECTIONS, not results)

Sharp-graded share, measured on FINAL grades outside MLB and WNBA:

- P1 36 of 53 (0.679): NBA 13/28, NFL 13/14, soccer 7/8, NCAAF 3/3.
- P2 93 of 138 (0.674).
- C0 200 of 308 (0.649).

The sharp count is the binding condition for all three. Games accrue faster than the 1:4 ratio L1 needs.

| | now n / games | sharp-graded a day (rate × share) | n still needed | days | projected first read with n ≥ 400 | cross-check: read-to-read pace 10-28 → 11-02 |
|---|---|---|---|---|---|---|
| P1 | 36 / 30 | 10.8 × 0.679 = 7.4 | 364 | 364 / 7.4 = 49 | **~Mon 12-21** | (36 − 2) / 5 = 6.8 a day → 54 d → ~12-26 |
| P2 | 95 / 67 | 30.7 × 0.674 = 20.7 | 305 | 305 / 20.7 = 15 | **~Tue 11-17** | (95 − 11) / 5 = 16.8 a day → 18 d → ~11-20 |
| C0 | 210 / 103 | 62.8 × 0.649 = 40.8 | 190 | 190 / 40.8 = 5 | ~11-07 (comparator, no look) | — |

- Games: P1 has 30 and grows about 5.6 a day (read-to-read), so it reaches 100 near 11-15. P2 has 67 and grows about
  12.4 a day, so it reaches 100 near 11-05.
- **Both candidates project to L1 before the 2027-01-31 final read.** P1 has about 5–6 weeks to spare, which is earlier
  than the 10-30 clock estimate of ~3 a day (log 10-30 23:15Z). The weekend days (31 and 46 for P2; 15 and 21 for P1)
  carry the rate.
- **What would move these dates:**
  - A bet is graded only after its game, so each date lags by about a day.
  - The weekday rate is lower than the weekend rate.
  - A change in Pinnacle coverage would move the sharp share (lane `pinnacle-coverage-d5`'s swap).
  - Six days is one weekly cycle, no more.

## 4. ev_lb funnel on the current files (post hoc, read-only; `scripts/ev_lb_funnel_read.py` on fleet `6c22ebfaa`)

- **Input.** Only that morning's current record files:
  - `2026-11-02.json.gz`: build `|1793633280`, written 9:28 AM CST; 938 candidates, 334 eligible.
  - `2026-11-03.json.gz`: build `|1793630334`, written 8:38 AM CST; 672 candidates, 33 eligible.
- **Candidates that failed a gate** (1,610 in all): 1,137 outside the 36 h window, 99 one-sided fair, 7 stale quote,
  2 wrong-date contract.
- **Qualifying in these two snapshots:** P1 1 / P2 6 / C0 12.

**Buckets, 367 eligible candidate-sides** (g = consensus − ask, f = fee, h = haircut; probability points):

| | n | A ask ≥ consensus | B fee eats | C haircut eats | D qualifies |
|---|---|---|---|---|---|
| **all, 11-02** | 367 | 79.0% (290) | 18.5% (68) | 2.2% (8) | **0.3% (1)** |
| all, 10-27 (6 snapshots) | 1,312 | 74.0 | 23.9 | 2.1 | 0 |
| current files, 10-27 | 373 | 75.6 | 21.2 | 3.2 | 0 |
| Kalshi | 301 | 78.7 | 18.3 | 2.7 | 0.3 (1) |
| Polymarket | 66 | 80.3 | 19.7 | 0 | 0 |
| NHL | 170 | 77.6 | 20.6 | 1.2 | 0.6 (1) |
| soccer | 72 | 75.0 | 25.0 | 0 | 0 |
| NBA | 62 | 80.6 | 12.9 | 6.5 | 0 |
| NCAAF | 36 | 91.7 | 5.6 | 2.8 | 0 |
| NFL | 27 | 77.8 | 18.5 | 3.7 | 0 |

- **g and the fee.** g has median −0.89 pts, p90 +0.64 and max +3.12. The fee median is 1.68 pts. 9 of 367 lines are
  net-positive before the haircut; 5 would qualify at half the haircut.
- **Haircut median by σ source.**

  | σ source | lines (of 367) | 11-02 median | 10-27 (current files) |
  |---|---|---|---|
  | all | 367 | **1.33 pts** | 1.43 |
  | S1 `fair_v1` | 269 | 1.40 | 2.18 |
  | S2 dispersion | 89 | 1.08 | 1.05 |
  | S3 inflated | 9 | 3.76 | 3.74 |

  S1 now covers 73% of eligible lines. On 10-27 it was a minority: the writer had not yet loaded `636ba4ff`.
- **The one D line** is an NHL Kalshi prop under S1, with g +3.12 pts.
- **No MLB this time.** On 10-27 its x0.5 fee carried P1's bets; MLB has now left the slate. Today's eligible set is
  NHL-heavy (170 of 367 eligible lines).
- **Overall: A + B = 97.5% (10-27: 97.9%).** Neither bucket depends on σ. The funnel's 10-27 reading stands.
- Scratch output: `C:\tmp\phase2_read_1102\funnel\report.json` and `candidates.csv`.

**Why the funnel's ~0.3% D share and P1's 10.8 bets a day are compatible.** Each line is decided once, at the first
qualifying build, out of 96 builds a day. The funnel is one snapshot per file. P1's bets come from the transient tail.
That selection is the edge hypothesis itself (prereg §9), and the sharp close is what grades it.

## 5. Grading health

- **Nightly grading runs.** Six `PAPER_GRADED` lines since 10-28, all at 7:45 AM Central:

  | read | bets graded | with a sharp close | with an outcome |
  |---|---|---|---|
  | 10-28 | 140 | 37 | 8 |
  | 10-29 | 281 | 64 | 23 |
  | 10-30 | 313 | 34 | 19 |
  | 10-31 | 243 | 34 | 20 |
  | 11-01 | 247 | 62 | 97 |
  | 11-02 | 288 | 112 | 60 |

- **`grades.json` holds 796 graded bets** of the 835 the read covers (653 final, 143 not yet final).
  - 341 have a sharp close; that is the read's 36 + 95 + 210.
  - **455 (57%) have none.** Every one gives the reason `no_pinnacle_close_at_this_line`.
  - 741 have a consensus close.
- **Where the sharp close is missing** (final bets): almost every MLB bet (P1 0 of 35, P2 1 of 45) and every WNBA bet (P1 0 of 5).
  NBA is about half (P1 13 of 28; P2 38 of 64; C0 108 of 187). NFL is near-complete (P1 13 of 14; C0 38 of 42).
- **Selection check on moved lines** (prereg §9). P1's 71 bets without a sharp close show +0.90% CLV against the
  consensus close (67 bets / 25 games, CI [−0.28, +2.24]). P2's 154 show −0.49% (128 / 61, CI [−1.62, +0.33]).
- **Outcome grades.** 151 graded, 583 props without an outcome grader, 62 `game_other`. As registered: ROI covers full-game
  lines only. That is why the ROI n is small (P1 9, P2 54).
- **No `CHIPS_UNREADABLE`, `NO_BOOK` or error line in either log.**

## 6. What this does and does not say

- **The gate has not been read.** NOT_YET is the verdict, and no look is due before about 11-17 (P2) / 12-21 (P1),
  both projections. Current means and z values are interim. Under the registered design they decide nothing, and
  neither looks.json nor any rule changed.
- **The volume risk stated on 10-26 / 10-27 has not materialised at this measured rate.** P1 books about 11 a day outside
  MLB, and about two thirds get a sharp close.
- **Evidence that could motivate a NEW registration** (named, not recommended; the user's decision):
  - **Bucket A + B = 97.5%** says the taker side is efficient after fees. The maker-side lead in the 10-27 funnel is
    still the one that changes both terms.
  - **The sharp-close gap on NBA props and on MLB/WNBA** removes about a third of bets from the gate population.
    D5's swap is the lever there, not the rule.
  - **The z-on-sharp-close refit** stays the first lever only if a candidate reaches a look and misses it on CLV.
- **Next registered read: Mon 2026-11-09** (the `#717` weekly line), then weekly until L1, final 2027-01-31.

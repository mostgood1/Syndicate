# ev_lb funnel: why Phase 2's primary rule books so few paper bets `[2026-10-27, lane syndicate-decision-engine]`

**User, verbatim (2026-10-27):** "Yes: run the read-only ev_lb funnel diagnostic now (where eligible lines fail:
uncertainty width vs edge vs fee, by sport and venue) so the 11-02 read has the facts. Don't change the registered
rule."

**What this is.** This is a POST-HOC, read-only diagnostic of `decision-policy-paper`'s registered primary rule
(prereg `8d16ab07`, todo `#738`).
- It is not a gate look. It changes no rule, no parameter and no fleet setting.
- The registered 11-02 read decides.

## Method

`scripts/ev_lb_funnel_read.py` re-runs the paper job's own candidate path: expand, `load_grid`, `sigma_for_record`,
`decision_policy_v1.evaluate`. That is `book_build` minus the writes. It ran on the 6 record files on the fleet disk,
the last build per selected date from 10-23 to 10-28.

Every eligible candidate is split in probability points. With g = consensus p - venue ask, f = taker fee and
h = p - p_lb (the uncertainty haircut):

    EV_lb > 0  <=>  g > f + h
    A  g <= 0          the ask is at or above the consensus fair
    B  0 < g <= f      a raw edge the taker fee eats
    C  f < g <= f + h  net EV > 0, eaten by the haircut
    D  g > f + h       qualifies

Checks:
- **The D bucket is the rule's own test.** `tests/test_ev_lb_funnel_read.py` checks that D <=> the policy's own
  `EV_lb > 0` on a grid of p, ask, fee and sigma.
- **The replay is faithful.** Build `|1793076311` reproduces the job's own logged summary exactly: 551 candidates, 34
  eligible, and qualifying counts ev_lb 0 / net_floor_719 1 / suggested_2pct 0.
- **The code is the same.** The policy, record, fair-runtime and fee modules and the params file are identical on
  fleet HEAD `06378fa9` and on main.

**Coverage.** 6 snapshots, 3,417 candidates, 1,312 eligible. 2,050 candidates fail only on `outside_decision_window`.
These are snapshots, not every booking: the record file for a date is overwritten by each build, so the 45 bookings
on 10-27 cannot be replayed one by one.

## Result: 1,312 eligible candidate-sides

| bucket | n | % |
|---|---|---|
| A: ask at or above consensus | 971 | 74.0 |
| B: fee eats the raw edge | 313 | 23.9 |
| C: haircut eats a net edge | 28 | 2.1 |
| D: qualifies | 0 | 0 |

- g: median -0.72 pts, p90 +0.79, max +3.32. The fee median is 1.71 pts.
- **A + B = 97.9%, and neither depends on sigma.**
- With NO haircut, 28 of 1,312 (2.1%) would be net-positive. At half the haircut, 3 would.

**Sigma caveat.** Replaying an older file is only faithful for A and B.
- The book grid has moved on since that build, so sigma falls back to S3 (961 of 1,312). The haircut then reads too
  wide: median 4.03 pts overall.
- On the two CURRENT files (10-27, build 14:55Z; 10-28, build 15:01Z; 373 eligible), the haircut median is 1.43 pts:
  S2 1.05, S1 (fair_v1) 2.18, S3 3.74.
- Buckets there: A 75.6 / B 21.2 / C 3.2 / D 0. All 12 net-positive lines in them are S2.

**By venue:** Kalshi (808) A 70.5 / B 26.9 / C 2.6; Polymarket (504) A 79.6 / B 19.0 / C 1.4.

**By sport x venue x kind, the largest cells:**

| cell | n | A | B | C | g median |
|---|---|---|---|---|---|
| NFL Kalshi props | 361 | 75.9 | 22.7 | 1.4 | -0.90 pts |
| soccer Polymarket games | 326 | 88.3 | 11.0 | 0.6 | -3.26 pts |
| NCAAF Kalshi games | 166 | 67.5 | 30.7 | 1.8 | -0.23 pts |
| soccer Kalshi games | 141 | 58.9 | 40.4 | 0.7 | -0.35 pts |
| NCAAF Polymarket games | 137 | 56.2 | 40.1 | 3.6 | -0.12 pts |
| NBA Kalshi props | 70 | 67.1 | 24.3 | 8.6 | -0.66 pts |
| MLB Kalshi props | 47 | 70.2 | 19.1 | 10.6 | -1.01 pts |

## The fee bound is the true fee

- **Most Kalshi fees here are an assumption.** 733 of 808 Kalshi eligible quotes (91%) carry `fee_is_bound`: the
  series is unknown, so it is priced at the full rate. Most of these records (1,642 of 1,849 such quotes) carry no
  Kalshi ticker at all.
- **The assumption is correct.** Kalshi's own `GET /series/<ticker>` was read at 15:0xZ with
  `scripts/read_kalshi_fee_params.py`: 42 series, plus 2 tickers that returned 404. Every NFL, NCAAF, soccer and NBA
  series read returns x1.0, so the full-rate fee is correct there and bucket B is real.
- **MLB is the exception.** Its `KXMLB*` batter and game series are x0.5; the Kalshi MLB fee median is 0.82 pts. That
  is why all 3 ev_lb bets booked on 10-27 are MLB World Series props.

## What this says for the 11-02 read (interpretation, not a decision)

1. **The haircut is not the main reason.** On about 98% of eligible lines, the venue's ask plus its taker fee is at
   or above the sharp consensus, haircut or not. Shrinking z or sigma could add at most 2-3% of lines, and those are
   exactly the lines the haircut exists to refuse.
2. **It is the same finding as E3 and E5.** E3 found Kalshi's mid beats our derived fair. E5 found Kalshi moves before
   our collector sees the news. At the taker price, these venues are efficient against the consensus after fees. A
   rule that waits for p_lb > ask + fee will book rarely, and mostly in low-fee series.
3. **Why the comparators book more.**
   - `net_floor_719` applies no haircut; it needs EV_net >= 1% on Kalshi or 0.5% on Polymarket.
   - `suggested_2pct` does not use the venue price at all.
   - Their CLV read will say whether those lines were real.
4. **The rate will likely fall further.** MLB ends with the World Series. After that, ev_lb's bets likely come only
   from S2 lines such as NBA props: 6 net-positive in these snapshots, and still 0 qualifying.

## Lead for Phase 3 (not followed)

The maker side changes both terms that kill the taker:
- A resting bid pays the bid, not the ask. That is bucket A.
- On `quadratic` fee-type series a maker pays no fee. That is bucket B.

This read found these series are all `quadratic`:
- NFL player props: KXNFLREC, KXNFLRECYDS, KXNFLPASSYDS, KXNFLPASSTDS. KXNFLANYTD is the exception,
  `quadratic_with_maker_fees`.
- NBA player props: KXNBAPTS / REB / AST / 3PT / STL.
- Soccer totals and spreads.

`kalshi-maker-shadow-paper` covers soccer totals and spreads and NCAAF segment totals. Whether to widen it to NFL and
NBA player props is that lane's call, after its 200-order look.

## Re-run on 11-02

From a checkout containing the script (fleet HEAD after its next fast-forward, or any worktree on main), at Idle:

    nice -n 19 python scripts/ev_lb_funnel_read.py --data-root ~/syndicate-prod/data --out <dir>

Read C and D on that morning's current files only. Scratch output from this run: `C:\tmp\funnel\out2\report.json`
and `candidates.csv`.

# Kalshi maker pilot -- early-results review `[read 2026-10-31 ~15:40Z, fleet, READ-ONLY, lane maker-pilot-review]`

Asked by the user in session 684b1d: one keep / adjust / pause recommendation, with evidence. No live setting was
touched. Updates `findings_2026-10-24_live_cell_scorecard.md` s10 (12 posts / 9 fills / 6 settled at the time).

## Sources (all read-only)

- Ledger: `execution_ledger.full_history_orders()` (25,107 rows), filtered to `execution_style == maker_pilot`.
  Read with only the three documented store settings (keyvalue backend, `redis://127.0.0.1:6379/0`, the fleet reports
  root). No process environment was read.
- Fill times: the first `MAKER_PILOT FILL ... submitted->filled` line per order in `~/syndicate-prod/logs/live-odds-worker.log*`.
  These are DETECTION times, so they are an upper bound on the real fill time. 7 of the 10 fills have one. Pollard's
  16:53:55Z comes from `state_kalshi.md`. The lines for PHXOKC and both MIL@TB fills had rotated out of the log.
- Price paths: `data/<sport>_source/tracking/book_quotes/*.jsonl[.gz]`, streamed and filtered by event id.
  - **Consensus fair** = the median, across books, of a two-way Shin de-vig at the same line. Only quotes up to 6 h
    old count. Kalshi and Polymarket are excluded.
  - **Kalshi mid** comes from Kalshi's own quotes. These exist only for main lines: there are 0 Kalshi rows for the
    alt-total / alt-spread tickers (PHXOKC, GSW@MIN, CHA@WAS, DET@BKN).
- Scripts: `C:\tmp\maker_review\{dump_rows,paths3,summarize}.py`. Output: `table.json`, `paths3.json`.

## Population

- **14 posts.** 10 filled; 4 were not (ILL@MD, killed by the old stale-cancel bug, plus MIN-Murray, MIN@CLE and
  BMU@BVB, which expired at kickoff).
- **Fill rate 10/14 = 71%.** The shadow study saw ~45%, but the pilot posts at bid+1c or on the bid, inside a 1-3c
  spread.
- **Every FILL line in the log window says `filled_as=maker`.** The taker stop rule is not triggered.
- **8 settled:** 2 won, 6 lost. 2 pending: FLA@UGA o55.5 and ACM@INT o2.5, both kick off 10-31.

## Q1 + Q2 -- per fill (prob units; edge = fair - price paid)

| fill | price | plan fair | cons @post | cons @fill | d +30m | d close | CLV vs cons close | outcome | held $ | realised $ |
|---|---|---|---|---|---|---|---|---|---|---|
| Pollard u1.5 rec | 0.44 | 0.462 | 0.477 | 0.477 (fill) | +0.001 | -0.019 | +0.018 | lost | -5.28 | +1.39 (exit 0.573) |
| PHXOKC u228.5 | 0.67 | 0.700 | 0.719 | (no fill time) | 0 | -0.069 | -0.020 | lost | -5.39 | +0.84 (exit 0.79) |
| MIL@TB 10-27 TB | 0.43 | 0.446 | 0.445 | (no fill time) | -0.003 | +0.032 | +0.047 | won | +6.81 | +6.81 |
| MIL@TB 10-28 TB | 0.42 | 0.436 | 0.447 | (no fill time) | 0 | -0.011 | +0.016 | lost | -5.07 | -5.07 |
| GSW@MIN o219.5 | 0.65 | 0.679 | 0.700 | **0.668** | +0.004 | +0.004 | +0.021 | won | +2.77 | +0.83 (exit 0.77) |
| FLA@UGA o55.5 | 0.47 | 0.492 | 0.490 | 0.491 | 0 | 0 | +0.021 | pending | | |
| Hubbard u2.5 rec | 0.53 | 0.558 | 0.567 | **0.511** | -0.032 | -0.033 | -0.052 | lost | -5.30 | -5.30 |
| CHA@WAS o217.5 | 0.56 | 0.586 | 0.567 | **0.540** (1 book) | 0 | -0.013 | -0.033 | lost | -5.08 | -5.08 |
| DET@BKN NO DET-13.5 | 0.68 | 0.703 | 0.723 | **0.668** | +0.005 | +0.013 | +0.000 | lost | -5.47 | +0.84 (exit 0.80) |
| ACM@INT o2.5 | 0.55 | 0.574 | 0.583 | **0.556** | -0.002 | -0.002 | +0.004 | pending | | |

**Reading -- the adverse selection is BEFORE the fill, not after it.**

- **After the fill, the fair barely moves.**
  - Over all 10 fills, mean drift is +0.0005 at +5m, -0.0026 at +30m and -0.0098 at close; 6 of 10 are negative at
    close.
  - The +5m read is mostly flat because of capture cadence, not because nothing happened.
  - Mean CLV against the consensus close is +0.2pp. Per learnings 2592, CLV is blind for passive fills.
- **Between post and fill, the fair falls toward our price.** Of the 7 fills with a fill time, 5 saw the consensus
  fall by 2.7-5.6pp before the fill was detected: Hubbard -5.6, DET@BKN -5.5, GSW@MIN -3.2, CHA@WAS -2.7,
  ACM@INT -2.7.
- **Mean edge (consensus fair minus price):**
  - at post: **+3.2pp**, matching the plan's EV of 3.4-5.2%;
  - at fill: **+1.2pp**;
  - **3 of 10 filled at NEGATIVE edge** (Hubbard -1.9, CHA@WAS -2.0, DET@BKN -1.2), and all 3 lost when held.
- **Mechanism:** one post per position, no re-price, resting up to ~40 h (FLA@UGA was posted 10-29 for 10-31). The
  resting bid is a stale quote. It fills when the world has moved toward the taker's side. This is the 10-19 shadow
  finding (fills won 5.37pp below the close) seen live.

## Q3 -- is the loss within what the EV predicts?

- **Held:** -$22.00 on $41.82 staked (-52.6%). **Realised:** -$4.73, because the exit lane rescued 3 of the 6 losers.
- **Fill-time fair (or post-time fair where there is no fill time):**
  - E[wins] = 4.47 ± 1.37 against 2 observed. Exact Poisson-binomial P(wins <= 2) = **0.075**.
  - E[held] = +$0.82 ± $13.91. Observed -$22.00, **z = -1.64**.
- **Plan fair:** P = 0.065, z = -1.71.
- **Bootstrap 95% CI on held ROI:** [-100%, +14%].
- **So:** the loss is in the low tail, but not outside what noise gives at n = 8. P&L cannot judge this pilot.
  - Detecting a 4% edge at 2 sd needs ~2,100 settled fills (~1,400 for 5%).
  - At the canary's ~1.5 fills/day, that is years.
  - Judge on the MECHANISM instead: edge at fill, and filled-vs-unfilled wins minus fair.
    - Edge at fill has a per-fill sd of ~2.5pp, so 30 timed fills give a SE of ~0.45pp. That is enough to tell
      +1pp from 0.

## Q4 -- exit lane

There were 4 in-play sales. All 4 sold ABOVE entry, so **no exit sale locked in a loss.**

- 3 sales sold losers at a profit: Pollard +$6.67, PHXOKC +$6.23 and DET@BKN +$6.31 against holding.
- 1 sale sold a winner early: GSW@MIN, **-$1.94** against holding.
- Net, the exit lane is **+$17.27** against hold-to-settle. That is a sample of 4, and it belongs to the exit lane's
  own exit-vs-hold study.

## Recommendation -- ADJUST: add a fair-move cancel; keep canary size; do not tighten the band

- **Change:** each tick, re-price every resting pilot post against the CURRENT consensus fair. Cancel it when
  (fair - post price) falls below an edge floor (proposed +1.0pp).
  - This is fair-based, NOT the old market-based stale rule that killed every post on 10-25 (learnings 2890).
  - It is the cancel-protection plumbing that plan #736 Phase 4 already names.
- **Expected effect (on these 10 fills):**
  - It cancels the 3 negative-edge fills.
  - Mean edge at fill rises from +1.2pp to **+2.5pp**.
  - Fill rate drops from ~71% to ~50%.
  - No P&L claim: the 3 happened to lose, but that is n = 3.
- **Why not the alternatives:**
  - Tightening the 40-75c band: fills span 0.42-0.68 and the negative-edge ones sit at 0.53-0.68, so the band does
    not select on staleness.
  - Reducing size: it is already the canary.
  - Pause: exposure is <= $10/day and realised P&L is -$4.73; the information is the point. The only argument for a
    pause is that every day without the cancel adds stale-quote fills we already understand.
- **Interim, no code:** none of the existing knobs (band, $5 min, $50/game, exit 0.10, exit caps, 50% day cap,
  #704 staking) addresses staleness. Keep running as is until the cancel ships.
- **Pre-registered re-judge: 2026-11-14,** or at 30 timed fills, whichever comes later.
  - Pass if mean edge at FILL is >= +1.5pp with a 90% CI lower bound > 0, AND filled-order wins minus fair is not
    below -3pp.
  - Otherwise pause.
  - Hold-to-settle P&L is reported but is not the criterion.
- **Measurement debt:**
  - The FILL log rotates in ~1 day. Record the fill timestamp on the ledger row (`venue_filled_at`); today the row
    carries only the order's `venue_resolved_at`, ~1 s after submit.
  - Kalshi alt-line quotes are not captured in `book_quotes`.

## Re-check 2026-10-31 ~20:50Z: matcher fixes (signed spread lines, segment = full, an extra shard date)

The profitability session (d57baa09) noted that the matcher compared spread lines by absolute value and did not match segment. Re-run (`paths4.py`):

- **Unchanged:** edge +3.2pp at post and +1.2pp at fill; 3/10 fills at negative edge; DET@BKN fair at fill 0.668; held -$22.00; z -1.64.
- **Moved:** a few CLOSE reads only (FLA@UGA CLV +0.047, ACM@INT -0.016, DET@BKN d+5m +0.021).
- **The recommendation stands.**

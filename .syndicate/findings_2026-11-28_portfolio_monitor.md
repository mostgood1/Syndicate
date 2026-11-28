# Portfolio monitor findings, 2026-11-28 (lane `portfolio-monitor`)

Public repo: counts and percentages only. No dollars, balances, order ids or row-level live trades.

## Lane `clv-fair-close` -- first coverage reading after the load (read 9:50 AM CST)

One GET of `/api/portfolio/live` at 15:50:04Z (9:50 AM CST), via `C:\tmp\pfmon\clvload\marks_reading.py` (local
scratch, never committed). It counts closing marks whose `checked_at` is at or after the load, 2026-11-27T23:02:03Z
(5:02 PM CST 11-27). The newest mark was checked at 08:42:19Z (2:42 AM CST).

- **Every mark stamped since the load carries the fair-close key: 21 of 21** (Kalshi 17 of 17, Polymarket 4 of 4).
  So the board child stamps it on every path, not just the same-book one.
- **Resolved since the load: 9** (Kalshi 6, Polymarket 3).
  - Kalshi: 2 same-book. **Both carry a fair CLV value (2 of 2).**
  - Polymarket: 0 same-book. All 3 resolved closes are `different_book_close`, so there is no fair close to take.
  - No same-book mark is missing its fair value, so there are no `close_fair_reason` counts to report.
- **The Polymarket bar (>= 60%) cannot be read yet: its denominator is 0.** The Kalshi 2 of 2 is a denominator of 2.
  This is a check that the path runs, not a coverage share.

**Rate, so the owed readings can be dated.** Resolved same-book marks per Central day, 11-24..11-27: Kalshi 2, 4, 5,
5; Polymarket 2, 1, 0, 2. That is about 4 a day for Kalshi and about 1.25 a day for Polymarket. Marks stamped per day
(all reasons, both venues): 7, 16, 13, 24. The 21 since the load are in line with that, so the change did not slow
stamping.

- A Polymarket share on at least 10 same-book marks: about 8 days out, around 12-06.
- The falsification test on at least 100 covered forward marks: about 19 days at about 5.25 a day, around 12-17.
  The 11-27 replay already measured the gap at +0.82 pp [+0.67, +0.98] on the 30 d book, outside [-0.3, +0.3]. So
  the forward test is a confirmation, not the first read.

**Owed:** the Polymarket share at n >= 10 (around 12-06); the forward falsification test at n >= 100 (around 12-17);
the readout half (fair CLV in `scripts/live_book_edge_readout.py`, under lane `portfolio-monitor`).

## What moved the 30-day ROI from -5.09% (11-23) to -9.59% (11-27) -- asked by the fleet-watcher (written 9:59 AM CST)

The NCAAF backtesting session asked on the user's behalf (user 11-28 ~9:05 AM CT, "yes, ask the portfolio session
about the ROI"). Its candidates: (1) good late-October days rolling out, (2) bets placed since CHANGE P (BC-071, 0%
live EV floor OFF, 11-24 08:30:37Z) grading badly, (3) something else (the 11-26 Wi-Fi outage day, a sport or market
cluster).

**Hypothesis (written before computing):** (1) carries nearly all of it. CHANGE P cut volume about 5x, so each day
that leaves the window carries several times the stake of each day that enters, and the window drifts toward the
book's 10-29..11-23 core whatever the new days do. Falsified if the days-in contribution is below -1 pp, or if the
post-P bets' ROI range excludes 0 on the low side.

**Data:** one GET of `/api/portfolio/live` at 15:58Z (9:58 AM CST), saved locally to
`C:\tmp\pfmon\roi_slide\live_all.json`, read through `live_book_edge_readout.bets_from_orders` and `summarize`
(dollar ROI, event-clustered 95% range). These are the page tile's windows: 10-25..11-23 for 11-23 and 10-29..11-27
for 11-27. Scripts: `C:\tmp\pfmon\roi_slide\split.py` and `next_out.py` (local scratch).

### RESULT: (1) CONFIRMED. The four days that left the window carry the whole slide; the days that entered and the post-P bets are positive

| window | bets | events | ROI [95%] | pre-fee |
|---|---|---|---|---|
| 10-25..11-23 (the 11-23 tile, read today) | 1,718 | 768 | -5.20% [-10.62, +0.21] | -1.22% |
| 10-29..11-23 (the core both share) | 1,510 | 683 | -10.22% [-16.03, -4.42] | -6.31% |
| 10-29..11-27 (the 11-27 tile) | 1,559 | 707 | -9.59% [-15.31, -3.87] | -5.74% |

- **Total move -4.39 pp.** Read on 11-24, the 11-23 tile was -5.09% on 1,703 bets. Fifteen bets in that window graded
  since then, moving it -0.11 pp. That is the only part of the move outside the window's ends.
- **Days out (10-25..10-28): -5.02 pp** if they are removed first, -4.75 pp if they are removed last. They were 208
  bets on 97 events at +12.55% [-0.71, +25.80], won 58.7% against a 52.2% breakeven, and carried **22.1% of the old
  window's stake**. Per day: +14.3%, +16.8%, +15.8%, +7.1%. By sport: NFL +29.4% (41 bets), NCAAF +34.6% (27), NHL
  +24.4% (13), MLB +12.1% (15), NBA -1.8% (103).
- **Days in (11-24..11-27): +0.63 pp** if added after the removal, +0.36 pp if added first. They were 49 bets on 29
  events at +8.35% [-23.84, +40.54], and carry **only 3.4% of the new window's stake**. Per day: 11-24 -23.5% (14 bets),
  11-25 +54.8% (12), 11-26 +8.0% (6, the Wi-Fi outage day), 11-27 +3.0% (17).
- **Post-P bets (submitted at or after 08:30:37Z 11-24): 43 bets on 26 events, ROI +16.26% [-14.17, +46.69]**, won
  60.5% against a 61.1% breakeven, fees 2.3% of stake. They are all of the days-in bets except 6 submitted before P.
  By venue: Kalshi 33 bets +18.2%, Polymarket 10 bets -26.0%. By sport: NBA 21 bets -10.3%, NCAAF 9 +21.2%, NFL 7
  +41.2%, NHL 5 +33.7%. They grade well, not badly, but 26 events cannot separate +16% from 0. Candidate (2) is
  rejected as the driver, though not shown to be an edge.
- **Candidate (3): no.** The outage day added 6 bets at +8.0%. No day or cluster that entered the window is negative
  enough to move it.
- **7 d (11-21..11-27): 203 bets on 117 events, -1.09% [-15.44, +13.27]**, pre-fee +1.69%, fees 2.77%. The prior 7 d
  (11-14..11-20): 411 bets on 207 events, -3.16% [-12.69, +6.37].

**What comes next mechanically.** 10-29..11-04 leaves over the next seven days. It is 332 bets at -19.32% and carries
**44.7% of the current window's stake** (per day: -45.8%, -21.2%, -19.5%, -12.8%, -15.0%, -18.7%, -17.9%). The rest of
the window, 11-05..11-27, is 1,227 bets on 566 events at -1.75% [-7.85, +4.35]. So the same mechanism that pulled the
30-day ROI down will lift it over 11-28..12-04 if new days come in near flat. It would drift toward about -2%, and its
range would widen as the stake behind it shrinks. **Neither direction is news about the bets placed now.** The 30-day
ROI is mostly a reading of late October and early November at the old volume. For what P is doing, the 7-day ROI and
the post-P line are the readings, and both are too small to read yet.

**Reading, for the user.** The slide is the window's composition, not the current book. The 10-29..11-04 week, the
book's worst, is now 45% of the window's stake. Since 11-05 the book is -1.75% with a range spanning 0. This does not
make the 30-day loss less real: 10-29..11-23 lost -10.22% beyond noise, and -6.31% of it before fees.

## The 11-26 shrunk-EV sizing study, run 2026-11-28 -- RULE RESTATED BEFORE COMPUTING (written 10:03 AM CST)

User 11-28 ~10:00 AM CST: "Yes, run it". The design is frozen as written in `findings_2026-11-26_portfolio_monitor.md`
("One optimization lead"):
- fit one k in [0, 1] on bets selected 10-28..11-17;
- recompute each bet's stake from k x claimed EV, and drop bets whose shrunk stake falls below the venue minimum;
- compare stake-weighted ROI against the actual stakes on bets selected 11-18..11-26, as a paired difference
  clustered by game;
- GO iff the held-out lower bound > 0 AND a forward copy (bets from 11-27, at 150 games) is > 0. Otherwise KILL.

**What the ledger can and cannot reproduce.** The ledger has no Kelly fraction or band stamp per order. It carries
`ev_pct`, the requested and filled stake, the fill price and fees. So each bet's shrunk stake is modelled from its
ACTUAL stake, following the sizer that was live when it was placed:
- **Band era** (submitted before 2026-11-02 18:23:01Z, when the live stake band went OFF): stake = floor + width x
  Kelly / kelly_at_max, capped at the top. Shrinking Kelly by k gives `floor + k x (stake - floor)` for a stake inside
  the band. A capped bet's Kelly is unknown, so it gets `floor + k x width`, the most it could shrink. A stake under
  the floor (trimmed to cash) keeps `k x stake`.
- **After the band** (proportional compounding Kelly): shrunk stake = `k x stake`.
- **Venue minimum.** Kalshi: one contract at the fill price (a smaller stake is the named refusal
  `stake_below_one_contract`). Polymarket: 1 dollar notional (assumed). A bet whose shrunk stake is below it drops out.
- Fees are taken as proportional to stake. That understates the drag on small Kalshi orders, whose fee rounds up per
  order.
- k is picked on a grid of 0.05 to 1.00 in steps of 0.05, as the fit window's best stake-weighted ROI. A tie goes to
  the larger k. The 95% range on the held-out paired difference comes from 2,000 bootstrap resamples of games, with a
  fixed seed.

**Prediction from the sizer's shape, written before computing.** Under proportional Kelly, multiplying every stake by
k leaves ROI on stake EXACTLY unchanged. So after 11-02 the shrink can move ROI only through bets that drop below the
venue minimum, which means the smallest stakes, the Q1 tail. It cannot touch the Q4 tail, which loses as much. In the
band era it pulls stakes toward the floor, which is a move toward flat staking. So the held-out difference should be
near 0, with a range spanning 0 (**KILL**), unless the dropped small stakes are a strongly losing group.

# PRE-REGISTRATION -- FanDuel-led stale-book bets, FORWARD (lane `fanduel-lead-forward`, 2026-11-17)

User 2026-11-17: "Pre-register it". The lead came from `momentum-lag-study`
(`findings_2026-11-17_momentum_lag_study.md`). There, the pooled OddsJam-Momentum signal was KILLED at -2.60% vs
the close. Its leader = FanDuel secondary cell read +0.85% [+0.38, +1.32] (3,187 bets / 525 events), but it was 1
of about 40 cells.

This registration decides whether that cell is real, on data it never saw, and whether a person could act on it.

OFFLINE and read-only on the fleet data root. No code path, capture, env, deploy or restart is touched.

## What counts as forward

- **Forward means detected later.** Only detections at or after **2026-11-18T06:00:00Z** (midnight CST) count.
  This file is committed before that instant.
- **Earlier detections are skipped.** A detection before it is not counted, and it does not consume the bet's
  "first detection", so a later detection of the same bet can count.
- **The control** uses events that start after the instant.
- **Everything before the instant is in-sample.** The 10-25..11-17 data is the in-sample, already analysed
  below. Nothing after the instant has been read.

## Instrument (pinned)

The instrument is `scripts/momentum_lag_study.py` at the commit that adds this file, with `--theta 0.02 --e-min
0.01`. The bet definition is UNCHANGED from the momentum-lag-study primary: a sportsbook leader and laggard, the
same fetch (heartbeat), the key alive, the laggard at or past the leader's pre-move decimal, predicted EV >= 1%,
entry decimal in [1.25, 5.0], and a consensus close of >= 3 non-exchange books. Only the leader is restricted.

The rerun with this code reproduced the original primary exactly: -2.60% [-2.71, -2.47], n 31,345.

**Bug fixes before a read are allowed only as a dated amendment to this file**, committed before that read and
stating the reason and the effect on the in-sample numbers. A change to the bet definition is not a bug fix.

## The two arms

- **Arm A, replication (decision-bearing).** The in-sample FanDuel cell's exact definition: leader == `fanduel`,
  EV vs the consensus close at B's price at the move's fetch.
- **Arm B, still there (decision-bearing for PROCEED only).** The same bets, entered only if B still quotes the
  entry price or better at the first fetch it answered for the event 5..30 min after the move, before the
  start. EV is at that re-read price. "moved", "gone" and "no fetch" are no bet.
  - **Why 5 min.** We cannot read the books themselves, and the laggard price is OddsAPI's copy. OddsAPI's copy
    of a book is at most 4.7 min old (p99 by book: Bovada 4.73, William Hill 3.98, Hard Rock 3.88, BetMGM 3.44,
    DraftKings 2.59, FanDuel 1.84; NBA 11-12 and 11-15, NFL and NHL 11-15). A re-read at >= 5 min that still
    shows the old price is a fresh read of the book.
  - **Why 30 min.** It is how long a person acting on an alert might take. With 5..15 min, 70% of in-sample bets
    had no re-read at all.
  - **Fixed before forward data.** The window was widened from 5..15 to 5..30 for coverage, on in-sample data
    only, before any forward data existed.

## Looks, boundaries and verdict (as coded in `forward_read`)

Statistic: mean EV vs close. z = mean / bootstrap SE (event clusters, 2,000 resamples, seed 20261117).
O'Brien-Fleming boundaries for two looks, two-sided alpha 0.05: **z >= 2.797 at look 1, z >= 1.977 at look 2**.

| look | command flags | events included |
|---|---|---|
| 1 | `--detected-after 2026-11-18T06:00:00Z --now 2026-12-16T12:00:00Z --forward-look 1` | started by 12-16 06:00Z |
| 2 | `--detected-after 2026-11-18T06:00:00Z --now 2027-01-13T12:00:00Z --forward-look 2` | started by 01-13 06:00Z |

Run each on or after its `--now` date. Retention keeps `book_quotes` for 120 days, and the heartbeat matches no
rule, so it is kept.

- **Look 1 needs at least 200 arm-A events.** With fewer, it is skipped and only look 2 counts.
- **A crosses its boundary:** arm A is REAL, and stops.
- **A's 95% CI upper bound is below 0 at either look:** KILL (the FanDuel lead was chance).
- **PROCEED** needs A REAL and B crossing the boundary at the same or a later look (an intersection-union test,
  so no extra correction). PROCEED means designing an outcome-graded feed test, NOT a build.
- **REAL_NOT_ACTIONABLE:** A real, B not by look 2. No feed. The result becomes a prior for the decision
  engine's owed steam expert.
- **KILL at look 2:** A misses 1.977.

No other analysis of forward data is done before look 1. The look-1 output reports both arms and the verdict, and
nothing else is looked at to choose what happens next.

## In-sample prior (detections 10-25..11-17, `--now 2026-11-18T01:00:00Z`)

| cell | n | events | mean | 95% CI | z |
|---|---|---|---|---|---|
| arm A | 3,187 | 525 | +0.85% | [+0.38, +1.32] | 3.53 |
| arm B (5..30 min) | 1,014 | 291 | +0.07% | [-0.70, +1.01] | 0.16 |
| arm B's bets, at the move's fetch | 1,014 | 291 | -0.01% | [-0.78, +0.91] | -0.02 |

Arm B status (in-sample), the share of arm-A bets:

| status | arm-A bets | events | arm A's EV at the move's fetch | 95% CI |
|---|---|---|---|---|
| confirmed (still there 5..30 min later) | 1,014 | 291 | -0.01% | [-0.78, +0.91] |
| moved (B's price worse by the re-read) | 338 | 139 | **+2.86%** | [+1.32, +4.44] |
| gone (key no longer quoted) | 12 | 8 | -2.24% | [-3.22, -1.18] |
| no fetch (no re-read inside 30 min) | 1,823 | 317 | +0.97% | [+0.51, +1.45] |

**This is adverse selection, in-sample.**

- When the slow book follows FanDuel within 30 min, the stale price was worth +2.86%, but only to someone who
  took it before it moved.
- When the stale price is still there 5..30 min later, FanDuel's move was not confirmed by the market: -0.01%.
- The no-re-read bets are 86% props with a median lead of 240 min; confirmed bets have a median lead of 1,391 min
  and are 40% props.

So arm B is expected to fail and PROCEED is unlikely. That is the honest prior, not a reason to change arm B: arm
B is exactly the question a manual feed has to pass. The forward output also prints arm A by these statuses
(`arm_A_by_confirm_status`, descriptive only).

By sport, arm A: nba +1.10% (z 4.73, 165 events), nfl +1.72% (z 3.17, 43), nhl +0.67% (z 1.51, 96), ncaaf +0.08%
(z 0.10, 119), soccer -0.34% (59), ncaab +1.37% (38).

**Read this prior with the winner's curse in mind.** The cell was chosen as the best of about 40 cells, so the
true effect is probably below +0.85%.

## Power (arm A)

- **Rate:** 525 events over about 22 days in-sample, roughly 23.5 a day. Look 1 should have about 660 events (SE
  about 0.21%) and look 2 about 1,315 (SE about 0.15%). Season mix will move these: NCAAF's regular season ends in
  December, while the NBA, NHL and NCAAB fill in.
- **If the true effect is +0.85%:** about 88% to stop at look 1, and about 100% by look 2.
- **If it is +0.40%:** about 75% by look 2.
- **If it is +0.20%:** about 25%.
- **If it is 0:** at most 2.5% to call it real (one-sided).
- **Arm B is weaker on two counts.** Its population is smaller, and its in-sample prior is lower. PROCEED is
  therefore the unlikely outcome even if A replicates.

## Known limits

1. **CLV only.** These are taker entries, for which CLV is a fair proxy. Results are not graded, and PROCEED leads
   to an outcome-graded test first.
2. **Arm B is a proxy.** It confirms the price on a later OddsAPI read, not at the book's own site.
3. **The definitions are inherited.** Fixed-line price moves only, same-fetch verification, "alive" from the
   final last-observed time, and the consensus close includes B (see the momentum-lag-study registration).
4. **Capture changes over the window are not controlled.** Changes in the book list, cadence or OddsAPI plan only
   change n. Each read prints coverage by sport and date.
5. **Limits and stakes are not modelled.**

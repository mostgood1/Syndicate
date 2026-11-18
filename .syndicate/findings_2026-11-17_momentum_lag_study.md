# Momentum lag study -- RESULT: **KILL** (as registered) -- 2026-11-17 (lane `momentum-lag-study`)

Pre-registration: `findings_2026-11-17_momentum_lag_study_preregistration.md` (on main `827b5d533`, committed 7:49 PM
CST, before the outcome pass started at about 7:50 PM). Instrument: `scripts/momentum_lag_study.py` (same commit).
Read-only on the fleet data root at nice 19 / ionice idle. Nothing in production was changed.

**Question.** OddsJam's Momentum says: when one sportsbook moves a price, bet a book that is still on the number
the mover just left. Does that stale price beat the close?

**Answer: no, not as a feed.** A sportsbook left on the pre-move price, bet at the fetch where the move appears,
lost **2.60%** against the de-vigged consensus close: CI **[-2.71%, -2.47%]**, 31,345 bets, 1,051 events, all
sports pooled, shards 2026-10-25..11-17 (events finished by 11-17 19:00Z). The CI's upper bound is below 0, so the
registered verdict is **KILL**. Do not build a Momentum-style feed on this signal.

## What the data says (read from `summary_outcome.json`, run 01:49:50Z..01:57:58Z 11-18)

| cell | n | events | mean EV vs close | 95% CI |
|---|---|---|---|---|
| **PRIMARY** (sportsbook leader + laggard, move >= 2pp, same fetch) | 31,345 | 1,051 | **-2.60%** | [-2.71, -2.47] |
| control: every sportsbook price 2 h before start | 932,913 | 2,365 | -5.82% | [-5.84, -5.79] |
| Pinnacle close instead of consensus | 17,118 | 723 | -1.70% | [-1.90, -1.49] |
| delayed entry (B's price at its next fetch <= 10 min) | 9,787 | 809 | -2.68% | [-2.90, -2.46] |
| props | 24,984 | 442 | -2.78% | [-2.91, -2.65] |
| game lines | 6,361 | 915 | -1.87% | [-2.21, -1.52] |
| move >= 1 / 3 / 5 pp | 63,189 / 17,776 / 4,836 | | -2.28 / -2.68 / -2.61% | all < 0 |
| leader alone (no book yet at its new price) | 22,831 | 952 | -3.44% | [-3.56, -3.32] |
| another book already followed | 8,514 | 793 | -0.34% | [-0.57, -0.12] |
| laggard = exchange (Kalshi, Polymarket, ...), BEFORE fees | 1,708 | 332 | -0.76% | [-1.11, -0.40] |
| leader = exchange, laggard = sportsbook | 2,798 | 238 | -4.05% | [-4.63, -3.48] |

Every sport is negative (nba -3.15, nhl -1.94, nfl -2.24, ncaaf -2.01, ncaab -2.56, soccer -1.31; mlb and wnba
have 3 events each). Every lead-time bucket is negative.

**Why it fails although the lag is real.**
- The laggards DO follow: 76% of laggards whose price changed again before the start moved toward the leader.
- The stale price is better than a random one: -2.60% against -5.82% for any sportsbook price 2 h out.
- But the gap is smaller than the vig. The leader's new single-book fair promised +4.16% on average; the close
  gave -2.60% (capture -0.62). The mover's new number overshoots where the market closes.

**The leaders differ a lot.** Bovada leads 29% of the primary at **-4.59%**; its moves are mostly noise. FanDuel
leads 10% at **+0.85% [+0.38, +1.32]**, which is OddsJam's own example. Other leaders: DraftKings -1.44, ESPN BET
-0.93, BetMGM -3.22, Hard Rock -2.45, Pinnacle -3.25. Without Bovada, the pool is still -1.77% [-1.92, -1.62].

## The FanDuel cell is a LEAD, not a finding

It is one of about 40 secondary cells. At 87% family-wise odds, at least one would exclude 0 by chance. The
breakdown below is EXPLORATORY (`C:\tmp\momentum_lag_study\explore_fanduel*.py`, not registered).

| FanDuel-led subset | n | events | mean | 95% CI |
|---|---|---|---|---|
| all | 3,187 | 525 | +0.85% | [+0.38, +1.32] |
| NBA | 1,600 | 165 | +1.10% | [+0.67, +1.55] |
| NFL | 379 | 43 | +1.72% | [+0.69, +2.83] |
| props | 2,125 | 307 | +1.19% | [+0.80, +1.58] |
| shards before 11-05 | 1,232 | 209 | +1.13% | [+0.40, +2.02] |
| shards 11-05 on | 1,955 | 316 | +0.67% | [+0.10, +1.25] |
| against Pinnacle's close | 1,955 | 432 | +0.83% | [+0.20, +1.50] |
| **bets with a later fetch <= 10 min, entered at the move** | 1,131 | 301 | **+0.18%** | [-0.71, +1.18] |
| the same bets, entered one fetch later (median 2.5 min) | 1,131 | 301 | -0.33% | [-1.16, +0.61] |

Two things stop it from being actionable now.
1. Where speed can be measured, the edge is not distinguishable from zero.
2. **The laggard's price is OddsAPI's copy of the book, not the book's board.** If OddsAPI refreshes FanDuel
   faster than DraftKings, a "laggard" price may already be gone at DraftKings. That bias inflates EV. It cannot
   explain the KILL, which runs the other way, but it can manufacture a small positive cell like this one.

A forward test would have to confirm the price at the book itself at entry.

## Corrections to what I told the user earlier the same evening

- **`book_updated_at` is not a book-side clock.** It equals OddsAPI's snapshot time on 441,068 of 441,068 rows
  (E5 pre-registration, 2026-10-26). That equality holds by construction (both fields come from OddsAPI's
  `last_update`), so it was re-measured: NBA 11-15 pregame, `captured_at - book_updated_at` has p50 0.8 min and
  p99 3.1 min even on the 51,475 FIRST sightings of a key, with 0 over 30 min. A book-side change clock would
  show hours on stable markets. A "behind for N minutes" timer would come from our own fetch history, not
  from that field (`C:\tmp\momentum_lag_study\bu_semantics.py`).
- **Prop capture is not hourly.** NBA props had a price-changing fetch about every 3.5 min (median, 11-15). The
  "hourly" figure came from the 10-16 MLB postseason reading.

## Limits (as registered; they bound the conclusion)

- **Price moves at a fixed line only.** Line moves (7.5 -> 8.5) are not tested, and they are a large share of
  what a stale-book tool shows on props.
- **CLV only.** These are taker entries, for which CLV is a fair proxy. Nothing was graded against results.
- **Same-fetch verification exists only from 2026-10-25.** These detections were dropped for lack of a heartbeat:
  174,320 (pre-10-25), 39,468 for pulled-market keys, and 45,954 because B moved in the same fetch.
- **"Alive" uses each key's final last-observed time.** A key pulled and re-posted at the same price looks alive
  throughout.
- **Sportsbook limits are not modelled.**

## What it means for the platform

- **Momentum feed:** no build. The pooled signal is negative at every threshold and in every sport.
- **Kalshi / Polymarket:** as laggards, exchanges are -0.76% BEFORE the taker fee. This agrees with E5
  (`findings_2026-10-26_e5_venue_news_lag.md`) and with the in-play finding `[kalshi-in-play-efficiency]`: chasing a
  sportsbook move onto a venue does not pay.
- **Decision engine:** its owed "steam" expert (M1 slice 2, `docs/ai_context/todo.md` 2026-11-10 entries) should
  start from this result. A steam term that reads "books moved, the price we can take did not" points the WRONG way
  pooled (-2.60%). It is plausibly positive only when FanDuel leads, or when another book has already followed
  (-0.34%, near zero). That is a prior for a registered test, not a weight.

## Reproduce

```
wsl -d Ubuntu-24.04 -- nice -n 19 ionice -c3 python3 scripts/momentum_lag_study.py --pass outcome \
  --sports nba,nhl,nfl,ncaaf,ncaab,soccer,mlb,wnba --now 2026-11-18T01:00:00Z --theta 0.02 --e-min 0.01 --out <dir>
```

488 s, max RSS 451 MB. It writes `summary_outcome.json` and `instances.jsonl` (61 MB; kept on the fleet at
`~/momentum_lag_study_out/outcome/`, not in git).

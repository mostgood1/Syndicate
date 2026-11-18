# PRE-REGISTRATION -- does a book left on the pre-move price beat the close? (lane `momentum-lag-study`, 2026-11-17)

User 2026-11-17, after asking what an OddsJam-Momentum-style feature would take: "Run the study". OddsJam's
Momentum (https://oddsjam.com/betting-tools/momentum, read 2026-11-17) is a feed of +EV plays built on "the first
book to move is the smartest": FanDuel moves a prop -122 -> -154, DraftKings is still at -115, bet DraftKings.

OFFLINE and read-only on production (fleet `~/syndicate-prod/data`, run at nice 19 / ionice idle inside WSL). No
code path, capture, env, deploy or restart is touched. Instrument: `scripts/momentum_lag_study.py` (stdlib only).

**Committed before any outcome was computed.** What was looked at before this commit, and only this: shard
listings and sizes per sport; one shard's row SHAPE per sport (fields, kinds, books, markets, distinct capture
times); the `.state.json` and heartbeat SHAPES; and `momentum_lag_study.py --pass population`, which prints
coverage, detection counts by exclusion reason, counts by threshold, and the primary population's shape
(predicted EV, move size, lead time, leader/laggard books). The population pass never computes a price at the
close against an entry: no EV vs close, no Pinnacle-close EV, no control-arm EV.

## Facts the design rests on (read before registering)

- `book_quotes` is a CHANGE log: a row only when a key's (line, price) changes. The key carries the line, so a
  line move mints a new key and the old key simply stops (`odds_book_quotes._KEY_FIELDS`).
- The `.state.json` sidecar's third slot is the last time the key was OBSERVED (final value for the shard). It is
  the only way to tell "price unchanged" from "market pulled", so every price used below must have its key last
  observed at or after the instant it is used.
- The heartbeat (`tracking/book_quotes_heartbeat/`, from 2026-10-25) is one line per fetch: which events and which
  books answered. It is what lets "B was on the old number" be checked in the SAME fetch as L's move, which
  removes the 2026-10-16 artefact (`findings_2026-10-16_one_book_staleness.md`): books captured on different
  clocks look stale against each other although all are posting.
- `book_updated_at` equals OddsAPI's snapshot time on 441,068 of 441,068 rows (E5 pre-registration, 2026-10-26),
  so it is NOT a book-side change clock and is not used. A move is known only to lie between two of our fetches.
- `kalshi`, `polymarket`, `novig`, `prophetx`, `betfair_ex_*`, `matchbook` are exchanges/venues. They are kept out
  of the primary cell on both sides of the trade and out of the consensus close, and reported as their own cells.

## Definitions (as coded)

- **Population:** every shard of nba, nhl, nfl, ncaaf, ncaab, soccer, mlb, wnba; rows with `captured_at <=
  commence_time` (pregame) for events whose `commence_time` is at least 6 h before `--now 2026-11-18T01:00:00Z`.
  Markets whose name contains `alt` are excluded. Groups = (event, segment, market, player, |line|); a side =
  (selection, line).
- **A book's fair at t:** proportional de-vig across the group's selections, only when the book prices exactly one
  line per selection, each decimal is in [1.02, 51], the overround is in [0.98, 1.25], and every key was last
  observed at or after t.
- **Move:** book L changes a price at fetch t and L's fair on side s rises by `move >= theta` (s got shorter).
- **Laggard instance:** another book B with (i) B in the same fetch's heartbeat books and the event in its events,
  (ii) no change on s at t, (iii) its key last observed at or after t, (iv) `dec_B >= L's pre-move decimal` on s,
  (v) predicted EV = `fair_L_new(s) * dec_B - 1 >= E_min`, (vi) `dec_B` in [1.25, 5.0]. One instance per
  (event, group, side, B), the first qualifying detection.
- **Close:** each non-exchange book's last pregame price with its key last observed at or after commence - 30 min,
  de-vigged; consensus close = median across >= 3 such books. **EV vs close = fair_close(s) * dec_B - 1.**
- **Entry:** B's price at the fetch where L's move appears (a poller like ours would see it then).

## PRIMARY (the only decision-bearing cell)

Leader L a sportsbook, laggard B a sportsbook, all sports pooled, `theta = 0.02`, `E_min = 0.01`, entry at the
move's fetch, consensus close. Statistic: mean EV vs close; 95% CI by event-clustered bootstrap (2,000 resamples,
seed 20261117, percentile).

- **PROCEED** (to an outcome-graded forward test, NOT to a build): CI lower bound > 0.
- **KILL:** CI upper bound < 0.
- **NOT SHOWN:** CI spans 0. Build decision is the same as KILL (do not build); the record says the data could not
  separate it from zero, with the n it rests on.

## Secondary cells (descriptive; hypothesis-generating only)

Per sport (with the same sport's control), game vs prop, theta >= 0.01 / 0.02 / 0.03 / 0.05, delayed entry (B's
price at the next fetch it answered within 10 min; share of bets gone by then), Pinnacle close instead of the
consensus, leader alone (no other book already at L's new price) vs not, lead time [0,30) / [30,120) / [120,600) /
600+ min, the six most frequent leaders and the six most frequent laggards (plus leader = Pinnacle), laggard =
exchange (Kalshi/Polymarket/...), leader = exchange with a sportsbook laggard. Also: control arm (every sportsbook
price 2 h before start, against the same close), predicted-EV capture (mean EV vs close / mean predicted EV), and
the share of laggards whose next change moved toward the leader.

About 40 cells. At alpha 0.05 two-sided, the chance that at least one of 40 null cells has a CI excluding 0 is
1 - 0.95^40 = 87%. No secondary cell can flip the verdict; a striking one is a lead for its own pre-registration.

## Population pass (run 2026-11-17 ~20:25 CST, `--now 2026-11-18T01:00:00Z`, 617 s, max RSS 335 MB)

The qualifying population exists and is not thin. Coverage (shards with completed pregame rows / with a
heartbeat / intersection, which is what the primary can use):

| sport | shards | heartbeat | usable (first..last) | events | moves >= 2pp (any venue) |
|---|---|---|---|---|---|
| nba | 41 | 22 | 22 (10-25..11-16) | 271 | 162,712 |
| nhl | 48 | 23 | 23 (10-25..11-16) | 327 | 50,935 |
| nfl | 55 | 27 | 27 (10-25..wk9 shard) | 102 | 73,578 |
| ncaaf | 42 | 19 | 19 (10-27..wk9 shard) | 421 | 46,028 |
| ncaab | 19 | 19 | 19 (11-01..11-19) | 669 | 10,999 |
| soccer | 40 | 15 | 15 (10-25..11-08) | 675 | 20,149 |
| mlb | 23 | 3 | 3 (10-26..10-28) | 36 | 8,548 |
| wnba | 13 | 3 | 3 (10-26..10-31) | 19 | 6,961 |

(`events` counts every completed event with pregame rows, heartbeat or not.)

Primary-like population (sportsbook leader and laggard, all exclusions applied) with a consensus close:

| theta | instances | events |
|---|---|---|
| 0.01 | 63,189 | 1,214 |
| **0.02 (primary)** | **31,345** | **1,051** |
| 0.03 | 17,776 | 810 |
| 0.05 | 4,836 | 412 |

At theta 0.02: nba 16,759, nhl 6,199, nfl 2,817, ncaaf 2,276, soccer 1,987, ncaab 1,153, mlb 137, wnba 17;
props 24,984, game lines 6,361. **The pooled primary is mostly NBA props** (53%). Shape: predicted EV p10/p50/p90
1.3% / 3.0% / 8.2%; move 2.1 / 3.2 / 5.5 pp; lead time before start 25 / 294 / 1,854 min. Leaders: Bovada 9,212,
DraftKings 3,242, FanDuel 3,187, ESPN BET 2,768, BetMGM 2,308, Hard Rock 2,112, BetRivers 2,088, Pinnacle 1,815.
Laggards: DraftKings 4,854, Hard Rock 4,209, FanDuel 3,607, BetMGM 3,597, ESPN BET 3,053, Pinnacle 2,480. In 73%
no other book was already at the leader's new price; 57% of laggards changed again before the start.
Exchange-leader / sportsbook-laggard: 2,798 instances, 238 events.

Detections dropped by the same-fetch and liveness rules (sportsbook laggards, all thetas, counted per detection):
no heartbeat for the fetch 174,320 (pre-10-25 shards); B changed in the same fetch 45,954; B's key not alive
39,468 (a pulled market that a change log would otherwise show as "stale"); B not in the same fetch 8,961; entry
price outside [1.25, 5.0] 19,529. Kept: 77,865 first detections.

## Known limits, stated before the run

1. Price moves at a fixed line only. A line move (7.5 -> 8.5) is not detected, and that is a large part of what a
   stale-book tool would show on props.
2. Detection resolution is our fetch cadence. A move, and B's catch-up, happen somewhere between two fetches.
3. CLV is the proxy. These are taker entries, for which CLV is a fair proxy (learnings 2026-10-19), but nothing
   is graded against results. PROCEED requires an outcome-graded test before any build.
4. Same-fetch verification needs the heartbeat, so only shards from 2026-10-25 on can contribute to the primary.
5. "Alive" uses the key's FINAL last-observed time. A key pulled and re-posted at the same price looks alive
   throughout.
6. Sportsbook limits and max stakes are not modelled. A positive result would be an upper bound on what an
   account can extract.
7. The consensus close includes book B itself.

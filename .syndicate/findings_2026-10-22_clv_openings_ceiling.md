# The CLV openings ledger cut off busy days at 32 MiB, for every sport at once

Lane `clv-openings-ceiling`, session 366eb355 (side session of local_25799b04), 2026-10-22.
Residual "the ceiling itself" of `#729` / `.syndicate/findings_2026-10-22_venue_order_opening_gap.md`.
Todo `#732`. Fix on origin/main (commit in the lane block). **NOT on the fleet.**

## Question

`clv_opening_ledger.record_openings` writes one file per date for all sports
(`reports/intelligence/clv_openings/<date>.jsonl`). It stopped writing at `_MAX_LEDGER_BYTES` =
32 MiB. How many openings did that lose, per day and per sport? What fix keeps every reader working?

## Substrate

- **Where:** the fleet, WSL, `~/syndicate-prod/data`. Read 2026-10-22 ~19:25-20:10Z.
- **How:** refresh-worker's derived env (`local_production.derive_role_env`), at `nice -n 19`.
  Read-only. The replay wrote only to a temp dir, with publish stubbed.
- **Openings:** `clv_openings/2026-09-30..2026-10-23.jsonl`, 24 files.
- **Price trail:** `clv_price_trail/<date>T<hh>.jsonl`.
  - It covers only 10-19..10-23, because `_RETAIN_DAYS` = 4.
  - It has one point per published row whenever (line, price, book) changed, so every new
    (movement key, line, book) leaves a point.
  - (movement key, line, book) is exactly the opening key.
- **Population:** `opportunity_population/<date>__<sport>__part*.jsonl`, 09-30..10-23. These are
  the pre-publication candidates, first sighting per (event, market, player, segment, side, line),
  with no book.

## Instrument check: the trail reproduces the openings key for key

On every non-full date the trail covers, the trail's (mk, line, book) set equals the openings key
set in both directions:

| date | openings | trail combos | in both | only in openings |
|---|---|---|---|---|
| 10-19 | 22,322 | 22,322 | 22,322 | 0 |
| 10-20 | 29,553 | 29,553 | 29,553 | 0 |
| 10-22 | 21,687 | 21,687 | 21,687 | 0 |
| 10-23 (partial) | 10,442 | 10,442 | 10,442 | 0 |

So on a full date, a trail combo that is absent from the openings is a lost opening, and the count is
exact.

## Before

**File sizes.** 6 of 24 dates were full, ending within 1 KB of 33,554,432 bytes:

| date | records | last write | largest sports at the cut (MiB) |
|---|---|---|---|
| 10-04 Sun | 32,670 | 10-04 23:25Z | nfl 21.2, wnba 4.8 |
| 10-10 Sat | 32,193 | 10-10 23:46Z | ncaaf 15.3, soccer 6.4, nfl 4.9 |
| 10-11 Sun | 33,145 | **10-11 19:03Z** | nfl 20.0, soccer 8.6 |
| 10-17 Sat | 32,372 | 10-17 22:37Z | ncaaf 12.8, soccer 6.9, nfl 5.3 |
| 10-18 Sun | 33,127 | 10-18 19:50Z | nfl 20.4, soccer 9.5 |
| 10-21 Wed | 32,771 | 10-22 03:24Z | nba 12.1, soccer 7.7, nfl 5.3 |

The next largest was 10-03 (30.7 MB, 29,399 records). The cap was **cross-sport**: NFL's Sunday props
filled the file, and every other sport lost its evening with it. That includes MLB's LCS night on
10-11, which is why `#729`'s MLB orders cluster there.

### Lost openings per full day

- **10-21:** exact, from the trail.
- **The other five:** the trail is pruned. The figures are a **lower bound** from the population: per
  sport, identities first sighted after the cut times that date's own ratio of openings to
  population identities before the cut.
- **The estimator undercounts.** It cannot see a new best book on an identity it already has.
  - On 10-21 it says 1,009 where the trail says 3,939, so the truth was 3.9x the bound.
  - On pseudo-cuts of the 18 non-full dates (cut at the 70th percentile of write times, truth known),
    truth / estimate had a median of 1.34 and a range of 0.74-1.85.

| date | lost openings | by sport |
|---|---|---|
| 10-04 | >= 2,701 | nfl 1,540, ncaaf 456, nba 339, mlb 248, nhl 98, soccer 20 |
| 10-10 | >= 6,336 | ncaaf 2,903, nfl 1,551, nba 1,263, mlb 234, soccer 225, nhl 160 |
| 10-11 | >= 10,401 | **nfl 8,631**, nba 735, ncaaf 586, mlb 239, soccer 122, nhl 88 |
| 10-17 | >= 5,113 | ncaaf 4,195, nfl 461, nhl 185, mlb 172, soccer 100 |
| 10-18 | >= 7,738 | **nfl 6,859**, ncaaf 483, mlb 292, soccer 75, nhl 29 |
| 10-21 | **3,939 (exact)** | nba 3,185, ncaaf 379, nfl 216, soccer 159 |
| **6 days** | **>= 36,228** | about 47k at the median calibration |

10-21 uncapped would have been 36,710 openings. The lost 3,939 are 10.7% of that day.

## Cost of the old dedup (why a larger single file needed more than a constant change)

- **What `record_openings` did.** It called `load_openings` on every build, to collect the keys
  already recorded.
- **Measured on the fleet, 10-11's file (33,145 records), nice 19:**
  - `load_openings`: 9.9 s, peak 155 MiB (tracemalloc).
  - A keys-only stream: 9.2 s, 8 MiB.
- **Consequence.** A larger file on the old code would cost more CPU and memory on every build.

## Fix

**Shape.** Still one file per date, so no reader changes. The alternative was per-sport files. It
would have changed the path that 8 readers build from a template, and `daily_optimizer.py`, held by
two other lanes, is one of them. Those readers are `load_openings`, `clv_join`,
`clv_position_join`, the layer2 movement term, `bucket_search`, `layer2_live_scorecard`,
`run_weekly_backtests` and `daily_optimizer`. The `HOT_ARTIFACT_PATTERNS` entry is unchanged.

**Per-(date, sport) ceiling, `_MAX_SPORT_BYTES` = 64 MiB.**
- A sport over its ceiling loses only its own rows. The old loop `break`s at the first oversized
  row, refusing every later row in the batch for every sport.
- The largest measured sport-day is NFL on 10-11: 20.0 MiB at the cut plus at least 8,631 openings.
  That is about 28-31 MiB uncapped, so 64 MiB is about 2x.

**Per-date ceiling, `_MAX_LEDGER_BYTES` = 128 MiB.**
- The largest measured day is 10-11: at least 43.5k openings, about 46 MiB at the median calibration.
  128 MiB is about 2.75x that.
- It still bounds a dedup failure to one file.

**Loud when a ceiling fires.**
- `[clv_opening_ledger] OPENINGS_CEILING_HIT date= scope=sport|day sport= dropped= bytes_on_disk= ceiling=`
  prints on every build that refuses a row.
- The report gains `dropped_at_ceiling`, `dropped_by_sport` and `bytes_on_disk`.
- The summary line gains `dropped=` and `bytes=`.
- A refused row is not marked seen. It is retried on the next build.

**Incremental dedup index (`_LedgerIndex`).**
- Per file and per process, it keeps the keys and per-sport bytes.
- It reads only the bytes appended since the last call, whether this process wrote them or another
  one did.
- It is trusted only while the device, inode and size hold, and the 64 bytes before the consumed
  offset are unchanged. Anything else re-reads from byte 0.
- It holds at most 4 files.
- The rows are written in one `write` per build.
- A torn final line is closed off with a newline, so it no longer swallows the next opening.

**First-sighting-only is unchanged.** The key, the record shape and the publish call are the same.

## After

**Fleet replay of 10-21, old against new code.**
- **Input:** a copy of the real openings file, and the 3,939 lost combos rebuilt from the trail as
  rows.
- **Replay:** run in their first-seen order, one `record_openings` call per trail build (25 builds).

| code | written | builds truncated | final file |
|---|---|---|---|
| origin/main (old) | **0 of 3,939** | 25 of 25 | 33,553,793 B |
| this fix | **3,939 of 3,939** | 0 | 36,842,802 B (nba 15,577, soccer 8,285, nfl 5,690, ncaaf 4,162, wnba 2,265, nhl 731) |

The rebuilt rows carry fewer fields than real openings, so the final file is slightly under what a
real 10-21 would be.

**Projected lost per full day after the fix: 0 on all six.**
- The largest projected day (10-11, about 46 MiB) is under 128 MiB.
- The largest projected sport-day (NFL 10-11, about 31 MiB) is under 64 MiB.

**Tests.** `tests/test_clv_opening_ledger_ceiling.py`, 10 tests.
- 7 fail on origin/main's `clv_opening_ledger.py`, each on behaviour, not on a missing attribute:
  - the 10-11 shape (NFL fills 32 MiB, then 20 MLB rows): `0 == 20`;
  - one sport's ceiling refusing another sport's rows;
  - a fired ceiling being loud and counted;
  - a refused row being retried;
  - a torn final line swallowing the next opening;
  - a one-line append re-parsing 2,041 lines;
  - the sizing pin.
- The 3 that pass both ways are guards:
  - the day ceiling still bounds a dedup failure;
  - first-sighting-only across builds and a second writer;
  - a replaced file is re-indexed.
- 505 passed across the readers' suites: clv_opening_ledger, clv_join (x3), clv_position_join,
  departure, close timing, price trail, layer2 movement, shortlist clv join and persist ceiling,
  publish append-only, both sides, game chips, order_clv (x2), bucket_search, run_weekly_backtests,
  daily_optimizer, game_line_bet, disk_inventory.

## Owed

- **Fleet load: a user decision.** A fleet ff to the fix plus a refresh-worker restart. Until then
  the fleet keeps the 32 MiB cut.
- **Forward reading after load.**
  - On the next busy day (Sat 10-24 NCAAF / Sun 10-25 NFL), the file passes 33,554,432 B with
    `dropped=0`.
  - There are no `OPENINGS_CEILING_HIT` lines.
  - Trail combos equal openings keys for that date (this findings file's instrument).
- **Not recoverable.** The 6 past days' lost openings cannot be backfilled as openings: the first
  price at sighting was never written.
  - The trail holds 10-21's 3,939 first prices, but it is pruned after 4 days.
  - `order_clv` (`f5113511`) already grades opening-less orders from the quote log.
- **Sibling, not fixed here.** `clv_departure_ledger._MAX_LEDGER_BYTES` = 8 MiB. 10-17 measured
  7,938,374 B (95%) and 10-10 6,544,067 B. It is the same one-file-for-all-sports shape and is
  likely to fire on the next big Saturday.

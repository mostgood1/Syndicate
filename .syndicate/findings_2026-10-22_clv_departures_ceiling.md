# The CLV departures ledger would cut off every sport at 8 MiB, and 10-17 reached 95%

Lane `clv-departures-ceiling`, session d0d9f2f7 (side session of local_802cdcc8), 2026-10-22.
Sibling of `#732` / `.syndicate/findings_2026-10-22_clv_openings_ceiling.md` (`22e3a0aa`).
Todo `#734`. Fix on origin/main (commit in the lane block). **NOT on the fleet.**

## Question

`clv_departure_ledger.record_departures` runs on every Layer 2 build, called from
`record_openings`. It writes one file per date for all sports
(`reports/intelligence/clv_departures/<date>.jsonl`) and stops at `_MAX_LEDGER_BYTES` = 8 MiB.
Has the cap fired, how close is it, and what fix keeps the readers working?

## Substrate

- **Where:** the fleet, WSL, `~/syndicate-prod/data`. Read 2026-10-22 ~20:25-20:50Z (3:25-3:50 PM CT).
- **How:** refresh-worker's derived env (`local_production.derive_role_env`), on the fleet venv, at
  `nice -n 19`. Read-only. `reports_root()` under that env = `/home/amyn/syndicate-prod/data/reports`.
- **Files:** `clv_departures/2026-09-30..2026-10-23.jsonl`, 24 dates, with their `.state.json`.
- **Logs:** `refresh-worker.log` and `.1`-`.5`, covering DEPARTURES lines for dates 10-16..10-22
  (2,184 lines). `live-odds-worker.log*` has 12 DEPARTURES lines, all `date=` empty (the
  no-rows early return).

## Before

**The cap has not fired yet.**
- `DEPARTURES ... truncated=True`: 0 of 2,184 refresh-worker lines. That window covers dates
  10-16..10-22 only. Older logs are rotated away.
- No file has reached 8,388,608 B, so dates 09-30..10-15 cannot have fired either.

**It is close.** Per date, all sports (the 10 largest):

| date | bytes | % of 8 MiB | records | departures | returns | builds | largest sports (MiB) |
|---|---|---|---|---|---|---|---|
| 10-17 Sat | 7,938,374 | **94.6** | 20,567 | 12,223 | 8,045 | 299 | ncaaf 3.64, soccer 1.65, nfl 0.96, nhl 0.72 |
| 10-10 Sat | 6,544,067 | 78.0 | 17,368 | 10,167 | 6,761 | 440 | ncaaf 3.80, soccer 1.28, nfl 0.42, nhl 0.28 |
| 10-21 Wed | 5,282,112 | 63.0 | 13,024 | 8,337 | 4,414 | 273 | **nba 2.35**, soccer 0.91, ncaaf 0.87, nfl 0.54 |
| 10-03 Sat | 5,116,192 | 61.0 | 13,274 | 8,100 | 4,939 | 235 | ncaaf 3.14, nfl 0.77, mlb 0.75, nhl 0.19 |
| 10-11 Sun | 4,542,304 | 54.1 | 11,940 | 6,921 | 4,539 | 480 | nfl 2.49, soccer 0.93, mlb 0.39, ncaaf 0.25 |
| 10-18 Sun | 4,265,331 | 50.8 | 11,075 | 6,436 | 4,252 | 387 | nfl 2.56, soccer 0.97, mlb 0.24, ncaaf 0.17 |
| 10-20 Tue | 4,075,589 | 48.6 | 10,366 | 6,143 | 3,975 | 248 | soccer 1.16, nba 1.06, ncaaf 1.04, nhl 0.54 |
| 10-04 Sun | 3,901,840 | 46.5 | 9,656 | 6,236 | 3,227 | 193 | nfl 2.06, wnba 0.78, mlb 0.47, ncaaf 0.27 |
| 10-09 Fri | 3,669,727 | 43.7 | 9,843 | 5,457 | 4,034 | 352 | ncaaf 1.47, wnba 1.17, soccer 0.44, nfl 0.33 |
| 10-16 Fri | 3,326,504 | 39.7 | 9,077 | 4,869 | 3,752 | 456 | ncaaf 1.48, soccer 0.78, nfl 0.52, nba 0.25 |

- **Largest sport-day:** NCAAF on 10-10, 3.80 MiB. Then NCAAF 10-17 (3.64) and NFL 10-18 (2.56).
- **Heartbeats are small.** At most 59 KB/day (10-13, 497 builds). The largest single-build burst
  was 885 departure and return records (10-21, 01:53:47Z).
- **NBA changed the picture.** It started on 10-21 and wrote 2.35 MiB on a Wednesday.
  10-17 plus 10-21's NBA comes to about 9.9 MiB, about 1.2x the cap, so **the next Saturday with
  NCAAF and NBA (10-24) will probably fire it.**

**What firing would have cost.** The old write loop (origin/main before this fix):
- It `break`s at the first record over the cap. Records go in sport order, so the first sport
  to fill the file cuts every sport after it for the rest of the date.
- The build heartbeat is the last record of a build, so it is dropped as well.
- `_write_state` still runs. The departed markets leave the state, so they are never written
  on a later build either. `departed_today` keeps them, so a later return can be written for a
  departure that is not in the file.
- The only signal was `truncated=True` inside the DEPARTURES summary line.

## Readers, checked

- **`scripts/layer2_live_scorecard.py`.**
  - `fetch_departures` uses `/api/ops/artifacts/export?path=`, and the single-path branch has no
    per-file cap (`ops.py` `api_ops_artifacts_export`, `exact_path`). The 8 MB
    `SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES` applies to the bulk pattern walk only. So a file
    over 8 MiB still arrives.
  - `index_departures` reads only `build.at` and `build.sports`, and only the departure and
    return records. It ignores the new `censored` key.
  - `look_after` returns `unobserved` when a sport has no build at the sighting or none past the
    horizon. **This is why censoring is needed** (below).
- **`scripts/run_weekly_backtests.py`** reads `DEPARTURES_PATH` through
  `/api/ops/artifacts/stream`: uncapped and streamed.
- **`HOT_ARTIFACT_PATTERNS`**: `reports/intelligence/clv_departures/*.jsonl` is unchanged. The
  `.state.json` sidecar still does not match it (existing test).
- **`record_openings`** embeds the departures report under `report["departures"]`. Nothing
  reads its fields.

## Fix

Same file, path and record shape: the sibling of `22e3a0aa`.

- **Per-(date, sport) ceiling, `_MAX_SPORT_BYTES` = 16 MiB.** That is about 4x the largest sport-day
  (NCAAF 10-10, 3.80 MiB). A runaway sport loses only its own records.
- **Per-date ceiling, `_MAX_LEDGER_BYTES` 8 -> 32 MiB.** That is about 4x the largest day (10-17,
  7.57 MiB) and about 3x a projected NBA Saturday (about 10 MiB). It still bounds a state bug
  that re-fires every tracked market to one file.
- **Refused per record, never `break`.** A sport's refusal never costs a later sport its records.
- **Heartbeats are kept.** A build's heartbeat is refused only past the day ceiling plus
  `_HEARTBEAT_RESERVE_BYTES` (1 MiB, about 17x the largest day's heartbeats). The builds that ran
  stay visible after the day fills.
- **A refused sport is CENSORED for the rest of the date.** Its later heartbeats move it from
  `sports` to `censored`.
  - Without this, keeping the heartbeats would have created a new false reading. A heartbeat
    that lists a sport claims every departure of that build is in the file, and `look_after`
    reads a missing departure under a listed build as `kept`.
  - Censored, those sightings read `unobserved`, which is true.
  - The state keeps the censored set. A rescan recovers it from the heartbeats.
- **No orphan returns.** A refused departure is removed from `departed_today`.
- **Loud.** `[clv_departure_ledger] DEPARTURES_CEILING_HIT date= scope=day|sport sport= dropped=
  bytes_on_disk= ceiling=` prints on every build that refuses a record.
  - The report gains `dropped_at_ceiling`, `dropped_by_sport`, `bytes_on_disk` and
    `censored_sports`.
  - The summary line gains `dropped=`, `bytes=` and `censored=`.
- **Byte tally in the state sidecar.** `state.json` gains
  `ledger: {bytes, sport_bytes, censored}`.
  - It is trusted only while the file is exactly `bytes` long. Otherwise the file is re-read
    once: the first build after a restart onto this code, an unreadable state, or a crash
    between the append and the state write.
  - Fleet check, every real file, read-only at nice 19: the rescan's per-sport bytes sum
    exactly to the file size on all 24 dates. The worst case was 3.65 s on 10-17, streamed with
    flat memory (tracemalloc peak under 0.1 MiB).
- **One binary append per build.** A crash tears at most one line. A torn final line is closed
  with a newline so it cannot swallow the next record. Binary means the bytes counted are the
  bytes on disk. Text mode wrote CRLF on Windows, which the new tests caught.

## After

- **Projected loss on the 10-17 shape plus NBA:** 0. That is about 9.9 MiB against a 32 MiB day
  and 3.64 MiB against a 16 MiB sport.
- **Tests:** `tests/test_clv_departure_ledger_ceiling.py`, 9 tests.
  - **9 of 9 fail on origin/main's `clv_departure_ledger.py`. 7 of them fail on the defect
    itself:**
    - the 10-17 shape, NCAAF filling 8 MiB and then an NBA departure: `[] == [('nba','g1')]`;
    - one sport over its ceiling costing another sport;
    - a fired ceiling being loud and counted: `0 > 0`;
    - the heartbeat surviving a full day;
    - an orphan return for a refused departure: `returned 1 == 0`;
    - a torn final line swallowing the next departure;
    - the sizing pin: `8388608 >= 20 MiB`.
  - **2 fail on old code only because they guard mechanisms this fix adds:**
    - the scorecard reads a refused departure as `unobserved`, not `kept`. Old code has no sport
      ceiling, so it wrote the departure and read `gone`. This guard exists because per-record
      refusal plus kept heartbeats would otherwise produce a false `kept`.
    - the state sidecar's byte tally, with a recount after the file changes.
  - All 9 pass on the fix.
- **Reader suites:** 215 passed across `clv_departure_ledger` (17 existing), the new ceiling tests,
  `layer2_live_scorecard`, `clv_opening_ledger` + its ceiling tests, `run_weekly_backtests`,
  `clv_join`, `clv_position_join`, `clv_price_trail` and `shortlist_clv_join`.

## Owed

- **Fleet load: a user decision.** A fleet ff past this commit plus a refresh-worker restart.
  - The fleet checkout was at `ae2cb646` when read (lane `wnba-injury-fleet-ff`). That already
    carries `#732`'s `22e3a0aa`, which waits for the next restart, so one ff plus one restart
    loads both ceilings.
  - Until then the fleet keeps the 8 MiB cut, and 10-24 (NCAAF + NBA Saturday) is the likely
    first fire.
- **Forward reading after load.** On the next busy day:
  - the departures file passes 8,388,608 B with `dropped=0`;
  - there are no `DEPARTURES_CEILING_HIT` lines;
  - `state.json`'s `ledger.bytes` equals the file size.
- **If the fleet is NOT loaded before 10-24,** read 10-24 for the first
  `DEPARTURES ... truncated=True` line and the file at about 8,388,608 B. That would be the first
  measured loss. The heartbeat gap after it marks where the scorecard's `gone10` turns
  unobserved.

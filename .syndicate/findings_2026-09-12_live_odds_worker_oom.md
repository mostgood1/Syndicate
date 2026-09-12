# live-odds-worker OOM loop — findings, 2026-09-12 (lane `live-odds-worker-oom-loop`)

Read-only production readings plus one local mechanism measurement. Nothing was
deployed, restarted or re-configured to produce any number here.

Service `srv-d91dpertqb8s73co8lt0`, limit 2Gi, live `21c26db1` (live 2026-09-11T18:03:20Z).

## 1. The kill census — events API, not logs

    py -3 scripts/render_events.py --service live-odds-worker --since 2026-09-07T00:00:00Z --json
    READ fully paged, 3 pages, 241 events 2026-09-07T06:40Z .. 2026-09-12T21:54:44Z

- `oomKilled memoryLimit=2Gi`: **76**, first 2026-09-09T19:43:39Z, newest 21:54:43Z (still firing).
- `earlyExit` (the designed 6h recycle): 11. Zero `oomKilled` before 09-09 in the window.
- Uptime at kill (from the previous `server_available`, 56 kills with one): median 18.4 min.
  On 09-12 kill-to-kill is often 10-13 min (20:11 -> 20:21 -> 20:34 -> 20:43Z).
- `state.md`'s "live-odds-worker has NEVER been evicted / zero platform kills" was true
  through 2026-09-04 and is FALSE from 2026-09-09.

## 2. Code and env bisection

    Render deploys API, /v1/services/<id>/deploys?limit=40 (commit, trigger, finishedAt)

| live from | commit | kills during |
|---|---|---|
| 09-08 21:50Z | `b9f088de` | 0 (three clean recycles to 09-09 16:20Z) |
| 09-09 16:49Z | `13ca56c5` | first kill 19:43Z |
| 09-09 20:32Z | `2888c2f2` | kills continue |

- `52a995f2` "venue depth: stop discarding the six liquidity fields" — first deploy containing it: `13ca56c5`.
- `0b8c1e11` "kalshi: capture size at touch" (+`bid_size`/`ask_size`, 8 depth fields) — first: `2888c2f2`.
- Env changes recorded in `deploys.md` for this service in the window are all AFTER onset:
  `SYNDICATE_KALSHI_FORWARD_DATE_SPORTS` (09-10 18:03Z), `SYNDICATE_POLYMARKET_PAUSED_MARKETS=total`
  (09-11 15:05Z), `SYNDICATE_KALSHI_PRECAP_BOARD_LINES=1` (09-11 17:00Z).

## 3. Timing — which work precedes each kill

    py -3 scripts/render_logs.py --service live-odds-worker --text TRIM_SELECT --start 2026-09-08T12:00:00Z --json   (1,109 lines, 13 pages; covered from 09-10T01:22Z)
    py -3 scripts/render_logs.py --service live-odds-worker --text DAILY_BOOK  --start 2026-09-08T12:00:00Z --json   (3,504 lines, 37 pages)

- Kills since the first `TRIM_SELECT`: 69. **48 (69.6%) fall 10-45s after a `[kalshi_odds] TRIM_SELECT`.**
  Null: a random instant over the 1,023 in-life inter-TRIM gaps (p10 120s, p50 209s, p90 264s) gives **17.2%**.
- 66 of 69 fall within 180s of a TRIM. Of those, **62 hit BEFORE that tick's `[kalshi_odds] DAILY_BOOK` line printed**, 4 after.
  TRIM -> DAILY_BOOK in normal ticks: n=1,045, p10 7s, p50 14s, p90 35s, max 89s.
- Code between the two lines: `pipeline/kalshi_odds_refresh.py:2191` `_record_daily_book(full_markets)` ->
  `venue_daily_odds.record_venue_book` -> `record_daily_odds` per (sport, date), sequentially:
  `read_json_file` (whole file) -> append points -> `write_json_file` = recursive
  `normalize_timestamped_payload` copy + `json.dumps(indent=2)` string -> atomic write.
  In-process, on the parent's `syndicate-venue-poll` thread (`run_live_odds_refresh_worker.py:2583`).
- Raw logs read before 5 kills (21:54:43, 21:30:32, 20:57:05, 18:08:51, 12:24:53Z): `TRIM_SELECT` 18-31s before each, no `DAILY_BOOK` after it.

## 4. Anon vs page cache

    py -3 scripts/render_logs.py --service live-odds-worker --text ALL_PROCESS_MEMORY --start <w> --end <w> --json
    windows: 09-08 23:00-01:00Z (kill-free), 09-09 18:55-19:45Z, 09-10 09:10-15:05Z (kill-free), 09-11 17:55-21:00Z,
             09-12 05:40-12:30Z, 17:38-19:05Z, 21:25-21:56Z — 8,624 samples

- Last sample before 25 kills (11-124s prior): `container_memory_unreclaimable_mb` **1,177-1,793 MB**. No sample
  sits at the limit; the kill is a transient that lands between samples.
- `CONTAINER_MEMORY` 28s before the 12:24:53Z kill: `memory_anon_mb` 1,319.7, `memory_reclaimable_mb` 710.7.
- Parent `run_live_odds_refresh_worker.py` RSS between ticks: 1.0-1.3 GB on 09-12; 1,101-1,296 MB on kill-free 09-08.
  The resident baseline did not move. Children (`refresh_odds_sources.py` ~110-250 MB, `build_soccer_artifacts.py` ~90 MB) stack on it.
- 7 kills 06:00-12:00Z on 09-12 with no US game live: not slate-only.

## 5. Mechanism amplitude — LOCAL, real code, synthetic production-shaped file

Real `venue_daily_odds.record_daily_odds` with `SYNDICATE_REPORTS_ROOT` pointed at a scratch dir (disk backend
asserted), a file of N markets x 48 points x 8 depth fields, then one tick with 1/3 of rows moved:

| markets | file | RSS peak delta | tracemalloc peak | secs (rss run) |
|---|---|---|---|---|
| 2,000 | 34.9 MB | +316 MB | 337 MB | 5.5 |
| 4,000 | 69.9 MB | +670 MB | 674 MB | 11.2 |
| 8,000 | 139.8 MB | +1,378 MB | 1,350 MB | 22.4 |

- Linear, ~3.5 KB of transient per stored point.
- Parse alone (`read_json_file`, 8,000 x 48): **+279 MB**.
- Same tick with a compact, streamed `json.dump` and no recursive copy: **+279 MB** (file 75.7 MB). The
  write path is ~80% of the transient; the data itself is the parse.
- Production `DAILY_BOOK detail=`: `ncaaf 2026-09-12` at the 8,000-market cap (`MAX_MARKETS_PER_FILE`) every day
  09-09..09-12; `mlb 2026-09-12` 5,702 (22:13Z); `nfl 2026-09-13` 3,783. `#637` moved these files to disk, so
  `_trim_to_budget` (which only reacts to a keyvalue refusal) never fires. The files are not published and not
  readable remotely — true per-file point counts are UNKNOWN.

## 6. What is NOT explained

- The kill-free stretch 09-10 03:34Z .. 09-11 02:12Z (two clean recycles, then hourly deploys). A cumulative-`appended`
  upper bound puts `ncaaf 2026-09-12` at saturation by 09-10 12Z, but appends concentrate on active markets, so
  that bound is not the file. A lower parent/child baseline on a Thursday with no live NCAAF is plausible and NOT measured.
- 3 of 69 kills fall >180s after a TRIM; 4 of 66 after `DAILY_BOOK` printed. The Polymarket daily book follows on
  the same thread and uses the same writer; not separated.
- refresh-worker runs the SAME `[kalshi_odds] DAILY_BOOK` writer on its own disk (`files=28`, ~every 5 min,
  `render_logs.py --service refresh-worker --text DAILY_BOOK --start 2026-09-12T20:00:00Z`, 33 lines). Its
  `MEMORY_GUARD_ABORT` lead (`leads.md`) is NOT attributed to it — unmeasured.

## 7. Capture cadence — the kills already cut it (pre-fix baseline for the verification)

    render_logs.py --service live-odds-worker --text ODDS_SWEEP_LAUNCHED --start 2026-09-08T12:00:00Z --json   (869 lines, 10 pages)

| window | hours | sweeps/h | Kalshi DAILY_BOOK/h | kills |
|---|---|---|---|---|
| 09-08 12Z .. 09-09 15Z, kill-free `b9f088de` | 28 | 9.1 | 20.1 | 0 |
| 09-10 04Z .. 17Z, kill-free, no live slate | 14 | 4.9 | 18.0 | 0 |
| 09-12 13Z .. 21Z, NCAAF slate, kill regime | 9 | 8.7 | **8.4** | 24 (2.67/h) |

Live-slate hours kill-free (09-08 22Z .. 09-09 04Z): 17-23 sweeps/h; 09-12 slate hours: 8-11/h. Sweeps depend on the
slate, so compare like hours only.

## 8. The fix, measured locally (same harness as section 5, real code)

`venue_daily_odds._write_daily_file`: a disk path is streamed one market at a time through the store's own
`normalize_timestamped_payload`, compact, temp file + `os.replace`; a keyvalue-backed path still goes through
`write_json_file`. Same markets, points and depth fields.

| file | before | after, 1st tick (reads today's indented file) | after, steady state (reads compact) |
|---|---|---|---|
| 4,000 x 48 | +670 MB | +181 MB (69.8 MB read) | +150 MB (38.0 MB) |
| 8,000 x 48 | +1,378 MB | +400 MB (139.6 MB read) | +339 MB (76.0 MB) |

Parsed back after the fixed write: 8,000 markets, 48 points each, all 8 depth fields on the last point.
This is a LOCAL reading on a synthetic file shaped to production counts; the production proof is the kill census.

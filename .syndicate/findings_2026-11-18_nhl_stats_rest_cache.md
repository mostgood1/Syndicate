# Findings — the NHL generation's stats-REST reports, cached (lane `nhl-stats-rest-cache`)

Opened Wed 11-18 ~9:45 AM CST by the rail-monitor session on the user's "start the cache NHL stats calls session
too"; supersedes card `task_cd37974a`. Hypothesis H1-H3 written into the lane (`de4f95dfd`) before any test.
All fleet reads were read-only (`nice -n 19`); the replay read `~/syndicate-prod/data/nhl_source` and wrote only
to `/tmp` and the session scratchpad. Times are Central (CST) with UTC where it is the record.

## Where the calls come from (trace, file:line on `de4f95dfd`)
- `scripts/refresh_nhl_oddsapi.py:567` `_run_owned_generation` -> `collect_slate_inputs(target_date,
  root=artifact_root)` with the DEFAULT client, once per target date (today + `--days-ahead 1`).
- `ingestion/collect.py:120-144`, per slate team: `roster_full_names` (api-web), `build_team_usage`
  (`lineups.py:60`) -> `recent_finished_game_ids` -> `_finished_competitive_ids` (api-web club schedule; the
  previous season's too only when the window needs a top-up) -> `boxscore` per window game (disk-cached) ->
  `special_teams_toi(team, season)` for each season the window touches (`lineups.py:116-118`: stats REST
  `skater/timeonice`, gameType 2 and 3) -> `onice_goals(team, this season)` and `onice_goals(team, last season)`
  (`collect.py:142-143`: stats REST `skater/goalsForAgainst`, gameType 2 and 3).
- So in-season, 6 `limit=-1` stats-REST calls per team, none cached: 2 timeonice + 4 goalsForAgainst.
- The readers: `build_team_usage` reads `special_teams_toi` ONLY for the window's game ids;
  `lineups.attach_assist_share` reads EVERY `onice_goals` game dated before the slate date (`lineups.py:281-282`).

## Side finding: the generation's boxscore cache is in the CHECKOUT, not the data root
The live-odds-worker (pid 23141, read 11-18 15:3xZ) sets `SYNDICATE_DATA_ROOT=/home/amyn/syndicate-prod/data` but
NO `SYNDICATE_ARTIFACT_ROOT_NHL`, so `nhl_web._default_cache_dir()` resolves to
`~/Syndicate/data/nhl_source/data/ingestion_cache` (578 boxscores, newest 11-18 00:03:33Z) while
`~/syndicate-prod/data/nhl_source/data/ingestion_cache` holds the other producers' 1,092 files (343 boxscore /
landing / play-by-play + 63 score). Not changed here (a ride-along would move the boxscore reads); recorded as a
lead. The NEW stats cache resolves under the data root (`nhl_web._default_stats_cache_dir`).

## H1 — CONFIRMED: an unscheduled playoff report is exactly empty
Measured 11-18 15:49-15:5xZ (~9:50 AM CST), all 32 teams x 2 seasons (64 team-seasons), club schedule vs the
gameType-3 `goalsForAgainst` report:

| season | no gameType-3 game scheduled, report empty | playoff team, report = its scheduled finished playoff games | falsified |
|---|---|---|---|
| 2026-27 | 32 of 32 | 0 | 0 |
| 2025-26 | 16 of 32 | 16 of 32 | 0 |

So the 2 current-season gameType-3 calls per team are skipped whenever the schedule lists no playoff game, and
last season's are skipped for the 16 teams that missed the playoffs. The schedule must look real (it lists a
regular-season game) or the report is fetched: an empty or malformed schedule reads as UNKNOWN, never as "no
games" (learnings 2026-10-05: a swallowed miss silently ran the old engine).

## Design (on main behind `SYNDICATE_NHL_STATS_REPORT_CACHE`, absent = ON, `off` = the old transport byte for byte)
A `(report, team, season, gameType)` report is:
1. **skipped** (returns `{"data": [], "total": 0}`, what the API returns) when the team's schedule lists no
   game of that type (H1);
2. **reused from disk** (`<data root>/nhl_source/data/ingestion_cache/statsrest_<report>_<TEAM>_<season>_gt<T>.json`)
   when it holds every FINISHED game of that type dated before the slate date, none of those games is in
   progress, and it is either SETTLED (fetched >= 24 h after the newest such game started) or younger than 6 h;
3. otherwise **fetched exactly as before** and written (atomic replace). A failed fetch raises exactly as before
   and writes nothing.

The schedule used for 1-2 is the one `_finished_competitive_ids` already fetched for the usage window in the
same process (recorded, never reused for the window). A COMPLETE season's schedule (on or after Oct 1 of its end
year, every competitive game final) is kept on disk as `club_schedule_<TEAM>_<season>.json`, so last season costs
nothing after its first read.

**The one known non-identity, bounded:** an NHL scoring change to a game already in a cached copy. Within 24 h of
the game's start the copy is re-read at most every 6 h; after that one settled read covers it, and a change made
later still is picked up when the team finishes its next game. The existing boxscore cache (`nhl_web.boxscore`)
never re-reads a finished game at all.

Not allowlisted in `HOT_ARTIFACT_PATTERNS`: it is a regenerable fetch cache written and read by the same child on
the fleet's one shared disk (publish is a no-op there); a missing file costs one refetch, never wrong data. The
boxscore cache beside it is not allowlisted either.

## Tests (`tests/test_nhl_stats_report_cache.py`, 17; real TOR 2026-27 payloads trimmed to the read fields)
- off != on: the same two collections make 8 current-season stats calls switch-off, 2 switch-on (then 0).
- parity: usage rows + assist shares JSON-identical uncached, cold and warm (>= 8 skaters with real PP minutes,
  >= 18 with assist shares, so the cache served real data, not the fallbacks).
- refusals: newly finished game -> `fetch:new_game`; a LIVE game -> `fetch:in_progress`; the settle tiers;
  untrustworthy schedule (4 shapes) -> fetched, never skipped; failed fetch -> raises, nothing written; complete
  vs incomplete season schedule on disk.
- 152 of 152 pass across the 8 test files that import these modules.

## Replay — H2 CONFIRMED, H3 CONFIRMED
**What ran:** `collect_slate_inputs` for the fleet's two generation dates, 11-18 (3 games, 6 teams) and 11-19
(12 games, 24 teams) = 30 team-slates, in one process, four arms in order: OFF -> ON-cold -> ON-warm -> OFF.
- Inputs: the fleet's own scoreboard, props lines and news under `~/syndicate-prod/data/nhl_source` (read-only),
  `write=False`, availability clock pinned to 16:01:12Z for every arm.
- Caches: each arm got a `/tmp` copy of the generation's 578 boxscores, and ON-cold/ON-warm shared one empty stats
  cache.
- Run under the fleet venv at `nice -n 19`, 11-18 16:01:12-16:07:45Z (10:01-10:07 AM CST). No NHL game was in
  progress (first puck drop 6:30 PM CST).
- The stats API was healthy: 0 errors, mean 0.6-0.9 s a call, max 5.6 s.
- Harness: session scratchpad `replay_stats_cache.py`; it counts every GET by host in a `_get` wrapper,
  independent of the client's own counters.

| arm | stats-REST calls | api-web schedule calls | stats seconds | collection wall | lineup rows |
|---|---|---|---|---|---|
| OFF (first) | **180** (36 + 144) | 30 | 112.7 s | **129.3 s** | 127 + 531 |
| ON, cold cache | 100 (22 + 78) | 58 (+28 once: last season's, then on disk) | 87.4 s | 109.0 s | 127 + 531 |
| ON, warm cache | **0** | 30 | 0 s | **14.2 s** (2.4 + 11.8) | 127 + 531 |
| OFF (last) | 180 | 30 | 127.0 s | 139.1 s | 127 + 531 |

- **Calls:** 6 stats calls per team-slate with the switch off (180 / 30). ON-cold skipped 72 of 180 as empty
  (unscheduled playoffs: 60 this season + 12 last season's non-playoff teams), fetched 100, and served 8 from
  its own earlier writes. ON-warm served all 180 from the cache: 70 settled, 38 in the 6 h unsettled tier, 72
  skipped.
- **Parity (H2):** the `lineups` / `roster_snapshot` / `starting_goalies` rows are identical as sorted JSON in
  all four arms on both dates: 127 / 127 / 6 rows for 11-18, 531 / 531 / 24 for 11-19. In every arm 594 of 658
  lineup rows carry an assist share and the projected PP TOI, so the cache served real reports, not fallbacks.
  The excluded players and statuses are identical too: 12 for 11-18, 17 for 11-19. The ONE differing byte set
  is the first arm's 11-18 exclusion records:
  - `captured_at` is null on 0 of 12 there, and set on all 12 in every later arm. 11-19 has 17 of 17 in every arm.
  - The news-feed metadata of the process's first availability load differs. That file is an audit file, not a
    generation input, and it does not depend on this switch: the uncached OFF (last) arm matches the cached arms.
    Recorded as a lead.
- **Runtime (H3):** collection 129.3 / 139.1 s OFF -> 14.2 s warm, on a HEALTHY API. The stats calls were 87% and
  91% of the OFF collection time. Even on a good day that is ~115-125 s off each NHL generation, against a
  pregame full-step p50 of 218 s (odds-lane-sport-deadline, 181 runs 11-13..11-18).
- **H3's pre-registered bar** was "warm <= 12 stats calls for 11-18+11-19, runtime below OFF". Measured: 0 calls,
  14.2 s vs 129.3 / 139.1 s.

**Slow-night projection (a projection, not a measurement).** The 11-17 night's 7 sampled calls, capped at the
client's 30 s timeout, average 20.4 s.
- Switch off: 180 calls x 20.4 s ~ 3,670 s per generation. That is over the 900 s live deadline and the 1,800 s
  timeout, which is the 11-17 failure.
- Switch on, warm: a generation fetches only
  - 2 reports per team whose game finished since its copy;
  - 2 per look-ahead team while its game today is in progress;
  - 2 per team whose copy is unsettled and older than 6 h.
- Tonight that is at most a few teams per generation, plus one settling refetch per team that played yesterday,
  which falls ~noon CST with the 18 h settle.
- **A COLD cache on a slow night would still fetch ~100.** Each report is written as it arrives, so a timed-out run
  keeps its progress, but the load should go in during the day: the first pregame generation after it warms the
  cache on a healthy API.

**The settle default moved 24 h -> 18 h after the replay** (`DEFAULT_SETTLE_HOURS`). Games start at about the
same hour every night, so start + 24 h is the next evening's puck drop, when the API was slowest; start + 18 h is
~noon CST. The replay's warm run was minutes after its cold run, inside the 6 h tier either way, so its calls and
parity do not depend on the value; the tiers themselves are in `test_settle_window`.

## Leads (not followed)
- The generation's boxscore cache resolves to the fleet CHECKOUT (no `SYNDICATE_ARTIFACT_ROOT_NHL` on
  live-odds-worker), not the data root (see the side finding). Moving it is a separate, measured change.
- `lineup_availability`: the first `SlateAvailability.load` in a process wrote exclusion records with
  `captured_at` null (0 of 12), later loads 12 of 12. Same players and statuses, so metadata only; it shows up in
  `lineup_exclusions_<date>.json` for the first date of each generation child.

## Load (NOT loaded; the user's call)
- **What it takes:** a fleet ff of `~/Syndicate` to the landing SHA. No restart: `refresh_nhl_oddsapi.py` runs as a
  fresh child of `refresh_odds_sources.py` per sweep, with the worker's env (`os.environ.copy()`, so
  `SYNDICATE_DATA_ROOT` is set). It is a **betting change** (NHL generation inputs and timing): claims on
  live-odds-worker, a preflight CLEAR at the exact SHA, the ride-along check of everything on main past the
  fleet's `cdab875d5`, and `betting_change.py add --pending`, resolved at the first child.
- **Off switch:** `SYNDICATE_NHL_STATS_REPORT_CACHE=off` in `local_production.env` takes a drained `down`/`up`.
  Reverting the ff also turns it off.
- **Pre-registered reading for the load:** the first post-load NHL generation's `NHL_STATS_REPORT_CACHE` lines in
  the live-odds-worker log show `enabled=on` and `fetched` <= ~100 for the two dates (a cold cache).
  - The next generation shows `fetched` <= 2 x (teams with a newly finished or live game) and `served` ~
    6 x teams.
  - Files land in `~/syndicate-prod/data/nhl_source/data/ingestion_cache/statsrest_*` (~50 MB when full) and
    `club_schedule_*_20252026.json`.
  - That generation's `lineups_<date>.csv` row count equals the previous generation's for the same slate.
  - Falsified by `enabled=off`, files in the checkout instead of the data root, or a warm generation still
    fetching >= 6 x teams.

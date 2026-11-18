# Findings — Understat fetch failures (lane `understat-fetch-failures`, 2026-11-18)

Session 3fc36a05, started by session local_68526c0a (the user: "start a session to fix the
Understat failures"). Todo `#841`. Hypotheses H1-H4 were committed in `df0e33204` (12:33 PM CST),
before any probe. Results, the fix design and prediction P1-P5 were committed in `5637a627f`
(12:44 PM CST), before the build.

**Substrate:** `fleet` for everything below, from these sources:

- the manifests at `~/syndicate-prod/data/reports/migration_runs/*/odds_refresh_*/odds_refresh.json`, read at `nice 19`;
- the file mtimes under `~/syndicate-prod/data/soccer_source`;
- the served ESPN schedules (`<league>/api/schedule/schedule_2026.json`).

The scripts are in `C:/tmp/understat_3fc3/`.

## 1. What is wrong: Understat is down site-wide

Understat is not blocking us, and it has not changed its endpoint. Every URL answers HTTP 200
with the same page: 26,719 bytes, md5 `7942487b2c63810ef72fb43aead4a0b0`, `nginx/1.24.0 (Ubuntu)`,
`text/html`. Its visible text is only *"Understat.com We will come back soon"*, and its
`Last-Modified` is **2026-11-03 20:54:28Z (2:54 PM CST)**.

| # | from | request | result |
|---|---|---|---|
| 1 | fleet venv | `/getLeagueData/EPL/2026`, the code's own XHR headers | maintenance page |
| 2 | fleet venv | `/league/EPL/2026` (page, Session) | maintenance page; no `playersData`/`teamsData`, no scripts, no cookies |
| 3 | fleet venv | `/getLeagueData/EPL/2026`, same Session + Referer | maintenance page |
| 4 | fleet venv | `/getLeagueData/EPL/2025` | maintenance page (byte-identical) |
| 5 | fleet venv | `/` with a browser UA | maintenance page; DNS 144.31.199.53 |
| 6 | web fetcher (other network) | `/league/EPL` and `/` | the same "We will come back soon" text |
| 7 | fleet venv | the NEW fetcher, ON then OFF (section 4) | maintenance page |

Seven GETs went from the fleet host and two from the fetcher; the brief allowed about six. A web
search found no public notice and no return date.

Each hypothesis against those results:

- **H1 (contract change): FALSIFIED as framed.** The league page itself is the maintenance page;
  it is not a page that lost `playersData`.
- **H2 (host blocked): FALSIFIED.** Another network gets the same page, and it carries no challenge
  markers.
- **H3 (season key): FALSIFIED.** `/2025` is byte-identical to `/2026`.

## 2. Since when (H4 confirmed)

Last good writes on the fleet, all five leagues:

- `team_history/teams_2026.csv`: 10-31 between 7:12 and 8:47 PM CDT;
- `players/players_2026.csv`: 11-01 between 2:09 and 4:12 AM CST.

The rows in both end on 2026-10-31.

The manifests in date dirs 09-30..11-20 hold 11,884 big-5 `history_current`/`players` step
records. Their timeline:

| from (CST) | to (CST) | what the steps got | step p50 |
|---|---|---|---|
| — | 11-01 4:08 AM | last OK record (20 OK records in all since 09-30) | 1 s |
| 11-01 6:34 PM | 11-03 3:06 PM | `ConnectionError`; DNS `NameResolution` from 8:00 PM 11-01; `ConnectTimeout` from ~9 AM 11-02 | DNS 11 s, timeout 46 s |
| 11-03 3:27 PM | now (12:30 PM 11-18) | maintenance page: `JSONDecodeError` (teams), `playersData not available` (players) | 1 s |

## 3. Blast radius

**The sim prices on 10-31 data, silently.** `build_soccer_artifacts._load_team_ratings` reads
every `teams_*.csv` and keeps the last 45 rows per team. `_load_player_rows` reads every
`players_*.csv`. Neither checks freshness, so nothing in an artifact says the history stops on
10-31.

- **Missing matches:** 69 big-5 matches were played from 11-01 to 11-18 (served ESPN schedules,
  all `post`), at most 2 per team. By league: epl 12, la_liga 15, bundesliga 11, serie_a 17,
  ligue_1 14.
- **Players:** `players_2026.csv` tops out at 8-12 games per player by league (epl 9, la_liga 12,
  bundesliga 8, serie_a 10, ligue_1 9). That matches the 7-11 matches per team in `teams_2026.csv`,
  and both miss the same 2 rounds.
- **Growth:** the next round, 11-20..11-23, adds about 48 more. The ratings drift one round further
  each weekend while Understat stays down.

**Every soccer run is red because of it.** The manifests in target dirs 11-10..11-20 hold 800
soccer runs with these steps:

- 5,152 of 5,152 steps failed;
- soccer `ok: False` in 800 of 800 runs, and only because of Understat in 792;
- the other 8 runs had a real soccer failure that the standing red hid (`soccer_serie_a_props` ×2,
  `soccer_mls_artifacts` ×2, `soccer_ligue_1_props`, and 3 `_schedule` steps).

**Who runs the steps** (they are `modes=("full",)`, phases pregame and live):

| runner | runs |
|---|---|
| weekly per-league units (`--phase live --soccer-leagues X --soccer-date D`) | 356 |
| soccer-only pregame | 265 |
| refresh-worker look-ahead (all sports, future date) | 169 |
| other | 10 |

**Cost.** While the site serves the maintenance page:

- run cost: Understat seconds per run p50 11 s;
- request load: about 3 requests per league per run, because players asks `getLeagueData` and then
  the legacy page on the same host. That is about 990 requests on 11-17.

During the DNS/timeout phase the cost per run was much higher:

| errors the run hit | Understat seconds per run, p50 | max | runs |
|---|---|---|---|
| ConnectTimeout + DNS | 324 s | 538 s | 17 |
| ConnectTimeout only | 99 s | 543 s | 180 |

**Why it repeats every run.** Both steps are MTIME-gated at 1.0 day. A failed fetch leaves the file
stale, so every full soccer run re-fails them.

## 4. The fix: an outage guard (ON by default, behind a switch)

The commit is listed in section 7. Switch: `SYNDICATE_UNDERSTAT_OUTAGE_GUARD`. Absent means ON,
and `0`/`false`/`off`/`no` runs today's code exactly.

The fix touches only `player_history.py` and `fetch_soccer_history_local.py`:

- `refresh_odds_sources.py` is untouched;
- no step is added, removed or reordered;
- it makes 0 OddsAPI calls.

With the guard ON:

1. **The outage is named.** A non-JSON 200, a 5xx/403/429, or a connection error raises
   `UnderstatUnavailable`, which names the reason, status, content type, bytes and visible text.
   The step still **exits rc 1**, and its last stderr line (what the manifest keeps) is
   `UNDERSTAT_UNAVAILABLE league=.. kind=.. season=.. reason=..`. Nothing is written, and the old
   file is kept. A 404 is a wrong URL, not an outage, and raises `HTTPError` as before.
2. **Players stops asking the legacy page on the same host** after `getLeagueData` is unavailable.
   That second request is where the misleading "playersData not available" came from.
3. **The cooldown.** A host-wide marker, `<soccer_root>/_understat_status.json`, is shared by all
   roles, leagues and kinds. For 3,600 s after a failed probe, every Understat step exits rc 1 with
   `reason=cooldown no_request_sent` and states `down_since`, `last_probe_at` and `next_probe_in_s`.
   The first probe that gets JSON writes the files and flips the marker to `up`, keeping
   `last_outage`. An unreadable marker never blocks a probe, and OFF neither reads nor writes it.

**Tests:** `tests/test_understat_fetch.py`, 22 of 22.

- They fail at collection on the old code, where the names do not exist.
- The **off != on** test drives the fetcher with the REAL step's argv, from
  `_soccer_current_history_step` and `_soccer_players_step`. OFF raises the fleet's exact
  exceptions, with 2 requests for players. ON raises a named `SystemExit`, with 1 request, and
  writes the marker.
- Other tests cover the cooldown across all 5 leagues and both kinds (0 requests), recovery, a kept
  `down_since`, an unreadable marker, 404 versus 5xx versus a timeout, and the marker path.
- The neighbouring tests pass too: 225 of 225 in the files that touch `player_history` or the
  fetcher.

**Live check, 12:53 PM CST** (scratch out-dir, not the data root). Run 1 exited rc 1 with
`reason=non_json … bytes=26719 text='Understat.com We will come back soon'`. Run 2 (serie_a players)
exited rc 1 with `reason=cooldown no_request_sent … next_probe_in_s=3583`. OFF reproduced
`requests.exceptions.JSONDecodeError`.

**What the guard does NOT do.** It does not make big-5 history fresh: no code can make a site in
maintenance serve data. The soccer result stays red while Understat is down, deliberately, so the
failure stays visible.

## 5. The alternative source is the user's decision; nothing was built for it

If Understat stays down, the big-5 sim keeps drifting. The repo already has sources that cover
these leagues:

- **Players:** ESPN match-summary aggregation (`aggregate_season_player_stats`). It serves 4
  leagues in production, and `LEAGUE_ESPN_SLUGS` has all five big-5 slugs. But its `xg_per90` is
  REALISED goals per 90, a different estimator, and its ids are not `understat_<n>`.
  `test_no_league_is_served_by_two_sources` exists because one squad must never mix sources, and
  the 2024/2025 big-5 files are Understat. So a switch means re-sourcing every season of a league,
  not just 2026.
- **Team ratings:** football-data.co.uk goals-based `matches_*.csv`, the path the four
  goals-rated leagues use (window 90). The big 5 use Understat xG+PPDA (window 45). Moving them is
  a MECHANISM change that needs re-fitting and a backtest first (model engine standard), and it
  would be a betting change.

Either one is a model change, put to the user, not papered over here.

## 6. Leads (not followed)

- **The standing red masks other soccer failures.** 792 of 800 runs were red only because of
  Understat. A sport-level "upstream unavailable" class in the run summary
  (`refresh_odds_sources.py`, lane `odds-lane-sport-deadline`) would let a new failure show again.
- **No freshness signal reaches the artifact.** `build_soccer_artifacts` could record the newest
  history row's date per league, so a frozen input is visible on the board.

## 7. Prediction (pre-registered in `5637a627f`) and load

P1-P5 and the falsification rule are in the lane block. The load is a fleet ff with no restart:
the fetcher is a child script, picked up at its next run. `betting change: no`, for two reasons:

- while the site is down, the files are identical with the guard ON or OFF;
- on recovery, the first refetch lags OFF by at most 3,600 s, on a 1-day refresh cadence.

The load was put to the user; it has not happened.

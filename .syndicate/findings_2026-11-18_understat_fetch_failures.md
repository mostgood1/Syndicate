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

Seven GETs went from the fleet host for the diagnosis, and four more for the live checks in section 4 (11 in all). Two went from the fetcher. The brief allowed about six. A web
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

## 4. The fix: an outage guard with two switches

**Amended 2026-11-18 1:06 PM CST, before any load.** The first build (`09f8540a6`, 12:56 PM CST) was a
single default-ON switch that included the cooldown. The session that started this lane pointed at the
betting-change windows rule (`002a7e720`, effective 18:00Z), and it applies. The cooldown can delay a
refresh after recovery by up to 1 h. Skipping the legacy page would leave unread a page that still
carried `playersData`. Either can change the sim's inputs, so that half is a betting change. A
default-on betting change must not sit on main between windows, because the next unrelated ff would
load it. So the guard was split. The commit is listed in section 7.

The fix touches only `player_history.py` and `fetch_soccer_history_local.py`:

- `refresh_odds_sources.py` is untouched;
- no step is added, removed or reordered;
- it makes 0 OddsAPI calls.

**Switch 1, NAMING: `SYNDICATE_UNDERSTAT_OUTAGE_GUARD`.** Absent means ON; `0`/`false`/`off`/`no`
runs today's code.

- **The outage is named.** A non-JSON 200, a 5xx/403/429, or a connection error raises
  `UnderstatUnavailable`, which names the reason, status, content type, bytes and visible text.
- **The step still exits rc 1.** Its last stderr line (what the manifest keeps) is
  `UNDERSTAT_UNAVAILABLE league=.. kind=.. season=.. reason=..`. For players it adds
  `legacy_page=.. legacy_error=..`.
- **Nothing is written,** and the old file is kept. A 404 stays an `HTTPError`.
- **The outage is recorded** in the host-wide marker `<soccer_root>/_understat_status.json`: state,
  `down_since`, `last_probe_at`, and `probes` (one per failed `getLeagueData` request).
- **It sends exactly OFF's requests.** Players still asks the legacy page.
- **It writes exactly OFF's bytes**, and fails exactly when OFF fails. That holds under all 7 fixture
  responses: maintenance, connect timeout, 503, 404, healthy, a legacy page that still carries
  `playersData`, and JSON without players.

**Switch 2, COOLDOWN: `SYNDICATE_UNDERSTAT_OUTAGE_COOLDOWN`.** Absent means OFF; `1`/`true`/`on`/`yes`
turns it on, and it only works while naming is on. The rule asks for it to be switched on in a
betting-change window, or on the user's classification.

- **No request during the cooldown.** For 3,600 s after a failed probe, every Understat step exits
  rc 1 with `reason=cooldown no_request_sent`, `down_since`, `last_probe_at` and `next_probe_in_s`.
- **Players skips the legacy page.**
- **The first JSON clears it** and flips the marker to `up`, keeping `last_outage`.
- **An unreadable marker never blocks a probe.** Naming OFF neither reads nor writes the marker.
- **The effect:** about 990 requests a day become about 24. A DNS/connect-timeout phase costs one
  probe an hour instead of p50 324 s per run.

**Tests:** `tests/test_understat_fetch.py`, 46 of 46.

- They fail at collection on the old code, where the names do not exist.
- **Naming, off != on,** through the REAL step's argv (`_soccer_current_history_step`,
  `_soccer_players_step`). OFF raises the fleet's exact exceptions; naming raises a named
  `SystemExit` with the SAME request list and writes the marker.
- **`test_NAMING_writes_exactly_what_OFF_writes`:** 7 responses x 2 kinds. It checks the same
  failure outcome, the same requests and the same file bytes.
- **Cooldown, off != on:** with a fresh failed probe on the marker, OFF probes and ON sends nothing.
- **Other tests:** the cooldown across all 5 leagues and both kinds (0 requests), recovery, a kept
  `down_since`, an unreadable marker, 404 versus 5xx versus a timeout, both switches' parsing, and
  the marker path.
- **Neighbours:** 249 of 249 in the files that touch `player_history` or the fetcher.

**Live checks** (scratch out-dir, not the data root):

| when (CST) | build | run | result |
|---|---|---|---|
| 12:53 PM | first build | 1 | rc 1, `reason=non_json … bytes=26719 text='Understat.com We will come back soon'` |
| 12:53 PM | first build | 2 | rc 1, `reason=cooldown no_request_sent` |
| ~1:05 PM | split build, default switches | epl teams | rc 1, `reason=non_json` |
| ~1:05 PM | split build, default switches | serie_a players | rc 1, `reason=non_json … legacy_page=… legacy_error=ValueError`; marker `probes` 2 |
| both | either build | OFF | `requests.exceptions.JSONDecodeError` |

Those runs sent 4 more requests, so 11 GETs in all went from the fleet host.

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

## 7. Prediction and load

P1-P5 were pre-registered in `5637a627f`, and the AMENDMENT for the split is in the lane block.
Commits:

- the first build: `09f8540a6`;
- the split: listed in the lane STATUS and todo `#841`.

The load is a fleet ff with no restart: the fetcher is a child script, picked up at its next run.

**Naming (default) — `betting change: no`, tested.** It sends the same requests and writes the same
bytes as OFF under every response.

**Cooldown (default OFF) — `betting change: yes`, strictly.** Its inputs differ from OFF only on
recovery (a lag of at most 1 h on a 1-day cadence) or when a legacy page still carries `playersData`.
Switching it on would follow the windows rule:
- in the 11-24 2-7 AM CST window, as an env key (a drained down/up), or as a one-line
  default flip that is ff'd in the window;
- or now, if the user classifies it `no`.

Both decisions were put to the user; nothing is loaded.

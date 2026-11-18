# Ask the Syndicate + decision-engine build — standing monitor, 2026-11-17 (lane `ask-engine-monitor`)

Day 1. User 11-17 ~10:57 AM CST: "similar to the layer 2 game rail monitoring and the portfolio endpoint
monitoring, this session should be monitoring the build of the AI decision engine AND the "Ask the SYndicate"
endpoint and functionality overall. Right now the endpoint doesnt seem to work while the "ask the syndicate" on the
main layer 2 page DOES work".

Times are Central (CST) unless marked Z. Every request below is read-only (a page GET or an Ask POST, which only
reads the snapshot); nothing was deployed, restarted or written on the fleet.

## The two surfaces

- **`/syndicate`** (`syndicate/templates/syndicate.html`, served by `home.py` `syndicate()`): the standalone "Ask The
  Syndicate" page. It posts `{question, context: getPageContext()}` (an empty context unless the URL carries one)
  with a **45 s** client cut-off (`timeoutMs = 45000`), then shows "Timed out / Retry".
- **Layer 2 board** (`/intelligence`, `intelligence.html`): the shared `ask_bar.js` panel. A row's Ask button sends the
  row's identity (`event_id`, market, side, segment, matchup...), also with a **45 s** cut-off
  (`REQUEST_TIMEOUT_MS`).
- Both hit ONE handler, `POST /api/syndicate/query` (`ask_the_syndicate.py:611`): route the question, check a
  per-worker 10-min response cache (keyed on the question), try an artifact answer, read the latest intelligence
  snapshot (`read_latest_intelligence_state`, the combined board on the fleet), resolve the board row, build the
  answer, then collect focused evidence. `answer_source` is `snapshot` (the LLM is off by decision).

## Reading 1 (10:47-10:59 AM)

**Reproduced the report.**
- 10:48 AM: on `/syndicate`, the page's own "Spread read" example ("What do you think of this spread?") ran past
  the page's 45 s cut-off and showed "Timed out". The request was aborted client-side
  (`net::ERR_ABORTED`).
- The web log has no access line for it. Its worker (pid 4035235) was SIGKILLed by gunicorn's 60 s
  `WORKER TIMEOUT` at 10:49:49.
- 10:50 AM: the same question by curl, empty context: HTTP 200 in **26.6 s**, `ok` true, 123 KB,
  `schema_type` bet_analysis.
- 10:52 AM: a Layer 2 row's Ask (Wisconsin Badgers h2h, Marquette @ Wisconsin) answered in **21.2 s** (browser
  timing; web log 20.9 s). The Layer 2 ask "works", but it sits less than 25 s from the same cut-off.

**Then six timed asks, 10:53:41-10:54:04.** These alternated free text (the `/syndicate` request) with that board
row (the Layer 2 request). The wording varied per call so no worker's response cache answered.

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| free text (`/syndicate`) | 3.0 s | 2.6 s | 0.5 s |
| board row (Layer 2) | 7.5 s | 4.3 s | 3.7 s |

All 6 returned HTTP 200 with `ok` true. Free text was not the slow one. So the two surfaces do not differ in the
handler; both are fast on a free worker and slow on a busy one.

**Web health today (`~/syndicate-prod/logs/web.log`, 00:00Z-16:55Z):**
- **4 `WORKER TIMEOUT` SIGKILLs**: 9:23, 10:13, 10:38 and 10:49 AM. Since the log began (10-30), the most on any
  earlier day was 2 (11-06). A killed request leaves no access line, so the three before 10:48 cannot be attributed.
  They may include the user's own asks: the log holds **no** Ask POST and no `/syndicate` load before 10:48 today.
- **`WEB_WORKER_MEMORY_RECYCLE`**: workers at anon 648-956 MB against limits of 628-649 MB, recycled every 4-30
  min (8 between 9:54 and 10:54 AM). A fresh worker re-warms its caches on its first requests.
- **The combined-board overlay warmer** (`pipeline/intelligence_state.py` `_warm_combined_board_overlays_once`,
  `8bd59f958`, 09-21) is a thread inside each web worker. It rebuilds a recently viewed board whenever a newer
  in-play overlay lands. Today: 20 rebuilds over 20 s, three of them 45.1-64.5 s between 10:51 and 10:54 AM. While
  it runs it holds the worker's CPU (the GIL) against the worker's 4 request threads, and past 60 s gunicorn kills
  the worker.
- **Slow requests today, 73 over 20 s:**
  - `POST /api/intelligence/query` (the Layer 2 board query): 63
  - `GET /api/board/game-chips`: 5
  - `POST /api/syndicate/query`: 2 (both mine, 26.6 s and 20.9 s)
  - `GET /intelligence`: 2
  - `GET /wnba/api/live_player_boxscore`: 1
- **Web capacity:** gunicorn `--workers 2 --threads 4 --timeout 60`.
- **The host at 10:56 AM:** load average 7.8 / 10.4 / 11.1 on 12 cores, 6.5 GB available. CPU users:
  - refresh-worker (96%) and a soccer artifact build (100%), both nice 0;
  - the live-odds worker (41%);
  - at nice 19: this lane's F2 read runner (43%), the data backup's tar + gzip (76%) and a peer's pytest.

  Until 10:52 this session's own learner fit also ran there (nice 19, 29 min, 1.5 GB RSS). It is a contributor to
  the contention this reading measured, and is named here as such.

**Usage:** asks are rare. Since 10-30, the log holds 6 asks on 11-15 (mean 2.4 s, none over 45 s) and 8 today
(all this monitor's).

## Hypothesis (registered in the lane before the falsification reading)

Ask itself is cheap. It fails when its web worker is stalled by in-process board work (the overlay warmer, the
board query) on a CPU-saturated host, and the two surfaces are hit alike. The "Layer 2 works / `/syndicate`
doesn't" difference is which worker the ask lands on and when, not the request. Falsified by an Ask over 45 s with
no overlay warm and no request over 20 s on any web worker inside its window, or, on a quiet host, by free-text
asks taking more than twice as long as board-row asks across >= 10 pairs.

## Improvement candidates (evidence above; each needs its own lane before any change; loads are the user's call)

- **A-1, web does heavy work in-process.**
  - Evidence: the overlay warmer is 20-67 s of CPU per rebuild, per worker, on a 2-worker web.
  - Every Ask, board and portfolio request on that worker waits behind it. Past 60 s the worker and its in-flight
    requests are killed.
  - This cuts against the web/worker split (CLAUDE.md: web does no heavy computation).
  - No open lane owns the warmer: its last change was `8bd59f958`, 09-21.
  - Candidates: build the combined board in a worker and publish it; or cap or serialize the warm; or more web
    workers (memory permitting).
  - Owner: NEW lane needed. Also reported to `layer2-rail-monitor`, whose I-2 (board query triple duplication,
    80 MB) is the same query.
- **A-2, memory recycles every few minutes.**
  - Evidence: anon ~950 MB against a ~640 MB limit, so each fresh worker re-warms (cold asks).
  - Owner: the web memory work; the overlay warmer's own allocations are the obvious suspect.
- **A-3, Ask's 45 s cut-off sits below gunicorn's 60 s kill.**
  - A stalled ask shows "Timed out" while the server may still finish it into a per-worker cache that a retry
    probably will not hit.
  - This is a symptom, not the cause; it is listed so a page change is not mistaken for the fix.
- **A-4, research jobs on the fleet host.**
  - Evidence: today's 4 kills came while 2-3 nice-19 research jobs (this session's among them) shared the host with
    production's own nice-0 soccer build.
  - Measure before blaming: the next readings will log the host's top CPU users beside every kill.

## Decision-engine build, status at reading 1

- **F2 read** (`engine-live-prior-f2-read-1117`, one-time): started 10:31 AM. At 10:59 AM it was still running
  (11-15 runner done or running, 11-16 next), with no verdict yet.
- **NBA live-prop grade** (`nba-live-prop-grade-1117`): ran 9:32 AM, recorded on main `9857611d3`. 0 of 12 tests
  pass; the stat-progress expert is worse than fresh books in every prop group.
- **Learner slice 3a** (NBA prop outcomes): built locally `898e8695a` (not pushed). Dev reading 11-09..11-14, test
  11-13..11-14 (14 games):
  - live props: Δ log loss −0.0169 [−0.026, −0.0085]. The gain is all against quotes 180-900 s old (−0.024); fresh
    (<= 60 s) is +0.002 [−0.001, +0.005].
  - pregame props: +0.003, not significant.
  - Recorded under lane `engine-learner`.
- **M2 gate read** (`engine-learner-m2-gate-read-1124`): scheduled Tue 11-24 10:30 AM. The gate sha check is
  `6915bb6a5ecb80f2`.
## Reading 2 (11:11-11:15 AM): the probe, F2, and a gate consequence

**The probe.** `scripts/ask_monitor_probe.py` (local, 4 tests, not on main) ran on the fleet at nice 19. It
asks the page's three examples exactly as `/syndicate` sends them, plus rows picked from the Layer 2 shortlist
exactly as the Ask button sends them. Its first run crashed on an answer whose `as_of` had no zone: 3 asks were
made, then fixed. A date-only `as_of` is now reported as a date, with no age.

| ask | s | schema | as_of |
|---|---|---|---|
| "What do you think of this spread?" | 2.0 | bet_analysis | 15:58:10Z (the snapshot) |
| "Lakers vs Celtics" | 7.5 | matchup_analysis | 15:58:10Z |
| "top edges today" | 8.0 | market_summary (1 table) | 2026-11-17 (a date) |
| Gent (soccer pregame game line) | 8.7 | bet_analysis (5 tables) | 2026-11-17 |
| Ismael Boura Over 0.5 (soccer pregame prop) | 2.2 | bet_analysis (10 tables) | **2026-11-20** |

- **5 of 5 answered, 0 past the 45 s cut-off.** `/syndicate` loaded in 0.16 s. No game was live, so no live row
  was asked about. The shortlist itself took 24.2 s for 837 KB (reading 1).
- **The intelligence snapshot behind the free-text answers was computed at 15:58:10Z**, 74 min before the ask.
- **A-5, an answer dated in the future:** the soccer prop answer's `as_of` is 2026-11-20, three days ahead. That
  looks like the fixture's date, not when its data was read. Owner: Ask (the soccer prop-evidence provider).
  Verify the field before any change.
- **Web, 16:41Z-17:12Z:**
  - 1 kill (10:49).
  - 6 memory recycles (4 hard; anon up to 1,031 MB against a 649 MB limit).
  - 11 overlay warms: median 18.1 s, 3 over 45 s, 2 over 60 s, max 64.5 s.
  - 14 requests over 20 s: `/api/intelligence/query` 6, Ask 2 (mine), the shortlist 2, `GET /` 2,
    `/intelligence` 1, game-chips 1.
  - 5 over 45 s: `GET /` 2, `/api/intelligence/query` 2, game-chips 1.
- **Ask traffic:** all 16 Asks in the window came from this monitor.

**Decision engine: F2 did NOT pass, on reproduction.** The verdict is the F2 session's to record.

- The 11-15 runner: rc 0, every check clean.
- The 11-16 runner: rc 1, `RESULT ... alarms_plus_mismatches=4296`.
  - All 4,296 are one check: `JOIN ncaab half_point checked=9266 mismatched=4296`. Every other sport, and the
    Kalshi prior checks (`KALSHI_PRIOR ncaab checked=2132 mismatched=0`), are clean.
  - Every kept example is an NCAAB full-game total at 00:06:37Z (6:06 PM CST 11-16). That is two minutes after
    todo #816's per-line college totals calibration loaded (deploys.md 00:04:20Z, lane
    `ncaab-total-overprojection`).
  - So the live join now serves calibrated NCAAB totals, and the experts' reproduction does not apply that
    calibration. This is a likely cause, not a proven one: only 10 of the 4,296 rows are printed.
- The pooled F2 verdict was still being written at 11:15 AM.

**The same mismatch will void the M2 gate.**
- The gate's precondition (`m2_gate.py:124-128`) needs `alarms_plus_mismatches=0 exit=0` from the experts on
  EVERY test slate, 11-15..11-22.
- Its pinned experts (`981ef14f6`) predate #816, so 11-16..11-22 will fail on NCAAB live totals. The 11-24 read
  would print `M2_VERDICT NOT_A_VERDICT` and judge nothing.
- What would avoid it, both before any test-window outcome is read (none has been):
  - the experts reproduce #816's calibration (lane `engine-experts` / `engine-live-prior`, with the state-instant
    fix already owed after F2);
  - then a gate Amendment 2 that re-pins the code.

  The alternative is an amendment that drops NCAAB live totals after 00:04Z from the precondition and from
  judgement. Either path is the user's decision.
- Owner: lane `engine-learner` (the gate) + `engine-live-prior` (the experts).

**Learner slice 3a** (NBA prop outcomes): built locally (`d2609efd1` + `0a6c2e5d7`); dev reading in reading 1's
status block. Not pushed.

## Reading 3 (11:38 AM CST)

Probe 11:36:14-11:38:04 AM CST (17:36-17:38Z), base http://127.0.0.1:10000, page 200 in 0.22 s, shortlist 200 rows in 2.51 s.

**Ask:** 6/6 answered, 0/6 past the 45 s cut-off, median 18.78 s, max 29.95 s. All 200, all ok. A game was live (a `live_row` ask exists: NCAAB Hofstra @ Murray St, h1 Over 66.5).

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "this spread?" | 29.95 | yes | bet_analysis | 15:58:10Z (age 5,914 s) | 0 |
| free_text "Lakers vs Celtics" | 15.70 | yes | matchup_analysis | 15:58:10Z (age 5,930 s) | 0 |
| free_text "top edges today" | 22.52 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (soccer Gent h2h) | 18.78 | yes | bet_analysis | 2026-11-17 (date) | 5 |
| pregame_prop (soccer Boura SOT o0.5) | 6.61 | yes | bet_analysis | **2026-11-20 (date, in future)** | 10 |
| live_row (ncaab totals h1) | 10.46 | yes | bet_analysis | 2026-11-13 (date) | 2 |

**Web, 11:06-11:38 AM CST (104 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 9 (8 hard), max anon 1,036.3 MB vs limit 649.1 MB.
- Overlay warms: 41, median 15.14 s, 14 over 20 s, 1 over 45 s, 1 over 60 s, max 77.09 s.
- Requests over 20 s (14): POST /api/intelligence/query 9, GET / 2, POST /api/syndicate/query 2, GET /api/board/game-chips 1. Over 45 s (7): /api/intelligence/query 4, GET / 2, game-chips 1.
- Asks from any client: 14, 0 over 45 s, 0 non-200. 0 of 14 from a non-`Python-urllib` agent (6 are this probe; 8 at 11:11-11:12 AM CST are another urllib client, all 1.4-9.5 s).

**Host:** load 7.98 / 8.19 / 8.25 on 12 cores; MemAvailable 8,551 MB. Top CPU: refresh-worker 116% (ni 0, 2,158 MB, up 698 s), build_soccer_artifacts epl wk12 98% (ni 0), build_cheat_sheets 93% (ni 19), live-odds-worker 45% (ni 0), gunicorn x2 21% / 17% (ni 0), live_resim_workers 12% (ni 5).

**Engine:**
- 2a F2 task `engine-live-prior-f2-read-1117`: 1 run, succeeded (10:30-11:17 AM CST), summary "did NOT PASS". `f2_verdict.txt` last line: `F2_VERDICT PASS judged_families=12 failed_families=0 cutoff=2026-11-15T20:00:00Z files=2` (the families pass; the NOT PASSED is the 11-16 NCAAB totals JOIN mismatch, per `c765eec64`).
- 2b `engine-learner-m2-gate-read-1124`: enabled, fireAt 2026-11-24T16:30:00Z.
- 2c `m2_gate.py` sha256 `6915bb6a5ecb80f2...`: unchanged.
- 2d Engine-file commits on origin/main in the last 40 min: none.
- 2e Fleet loads in the last 40 min: 17:01:55Z (11:01 AM CST) ff `8aea4fe7e`->`0a60d9e0a`, no restart (#807 NCAAF sim-history dedupe); 17:25:58Z (11:25 AM CST) ff `0a60d9e0a`->`3d3c0a426` + refresh-worker TERM (#790 lever (i), incremental quote read self-check; also loaded #823 option A).

- **ANOMALY:** overlay warm of 77.09 s (> 60 s). Check next: which overlay and whether it lines up with the 11:25 AM refresh-worker restart or the soccer build's CPU.
- **ANOMALY:** `as_of_in_future` true on the pregame_prop ask (soccer Le Havre @ Troyes, as_of 2026-11-20, date kind). Check next: whether that date is the match date (fixture 11-20) leaking into as_of rather than the data time.
- **ANOMALY:** F2 result is in: the run says NOT PASSED; the verdict file says PASS 12/12. Check next: the 11-16 NCAAB totals JOIN mismatch (4,296) has to be fixed in the experts/gate before the 11-24 M2 read.
- **ANOMALY:** fleet load 11:25 AM CST, ff to `3d3c0a426` + refresh-worker TERM (#790 quote read; #823). It touches the quote read that the experts join. Check next: whether the live join's served quotes changed after 17:25Z.
- **ANOMALY:** fleet load 11:01 AM CST, ff to `0a60d9e0a` (NCAAF sim-history dedupe), no restart, so web picks it up at its next recycle. Check next: low pricing impact, but note it for the experts' reproduction window.

## Reading 4 (12:06 PM CST)

Probe 18:05:38Z (12:05 PM CST); web window from 11:35 AM CST.

**Ask:** 5/5 answered, 0 past 45 s, median 3.55 s, max 6.94 s. Shortlist 200 rows in 1.15 s; page 200 in 0.05 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "this spread?" | 3.55 | True | bet_analysis | 17:49:32Z (age 971 s) | 0 |
| free_text "Lakers vs Celtics" | 0.31 | True | matchup_analysis | 17:49:32Z (age 971 s) | 0 |
| free_text "top edges today" | 6.94 | True | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NBA MIN h2h) | 5.95 | True | bet_analysis | none | 2 |
| pregame_prop (NBA Quickley PA o21.5) | 2.09 | True | bet_analysis | age 1325 s | 7 |

None had as_of_in_future. No `live_row` ask was made, so no live game row was available to probe.

**Web (11:35 AM-12:05 PM CST, 129 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 5 (3 hard), max anon 945.8 MB vs limit 645.1 MB.
- Overlay warms: 19, median 10.23 s; 2 over 20 s, 1 over 45 s, 1 over 60 s; max 60.01 s.
- Requests over 20 s: 2, both `POST /api/syndicate/query`. These are the previous probe's asks at 11:36-11:37 AM CST (28.67 s and 22.48 s). Requests over 45 s: 0.
- Asks from any client: 11, 0 over 45 s, 0 non-200. All 11 came from `Python-urllib` (this probe's 5 plus Reading 3's 6), so 0 were from other clients.

**Host:** 12 cores. Load average 2.24 / 2.43 / 3.87; MemAvailable 10,928 MB. Top CPU processes:
- fetch_soccer_history_local (ligue_1), 239%, ni 0;
- refresh-worker, 120%, ni 0, up 115 s;
- refresh_odds_sources, 50%, ni 0;
- live-odds-worker, 45%, ni 0;
- gunicorn web, 12%, ni 0, up 124 s;
- live_resim_workers ×2, about 10% each, ni 5.

**Engine:**
- 2a: `engine-live-prior-f2-read-1117` has 1 run, status succeeded, 10:30-11:17 AM CST. Its summary says "did NOT PASS". But the last line of `f2_verdict.txt` (mtime 11:15 AM CST) reads `F2_VERDICT PASS judged_families=12 failed_families=0 cutoff=2026-11-15T20:00:00Z files=2`.
- 2b: `engine-learner-m2-gate-read-1124` is enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: The `m2_gate.py` sha256 starts `6915bb6a5ecb80f2`, which is unchanged.
- 2d: No engine-file commits on origin/main in the last 40 min.
- 2e: Fleet loads in the last 40 min: 17:34:59Z (11:34 AM CST), a DEPLOY ff `3d3c0a426` -> `92ae7490a` plus a switch flip at 17:35:08Z (todo #821: F1 ON, outs penalties OFF, for NBA sim totals). This touches live NBA total pricing. The 17:25:58Z refresh-worker TERM ff falls just outside the window (40m25s before). Other headers in the window are readings only.

- **ANOMALY:** An overlay warm took 60.01 s, over 60 s. Next, check the web log for which overlay and route, and whether it lines up with the recycles or the refresh-worker restart below.
- **ANOMALY:** An F2 result exists, and its two sources disagree: the run summary says "did NOT PASS", while the `f2_verdict.txt` last line says PASS 12/12. Next, the owning session should read run `local_dc76d55c` with list_events to see which verdict is final. The file may hold an earlier pre-run line, or the summary may reflect a later judgement.
- **ANOMALY:** A new fleet load landed: #821 F1 ON / outs OFF at 11:35 AM CST changes NBA sim totals. Next, check whether the experts' NBA totals reproduction still matches the live join, as #816 did not.
- **ANOMALY:** refresh-worker (up 115 s) and web (up 124 s) both restarted around 12:03 PM CST. deploys.md has no matching header; the last recorded refresh-worker pid was 4049350, and it is now 4060729. Next, check the supervisor log for the cause (memory recycle or crash), and check whether an MLB/NBA sim was in flight.

## Reading 5 (12:35 PM CST)

Probe file `ask_reading_20261117T183539Z.json` (asks 12:35:43-12:36:11 PM CST; web window from 12:05:39 PM).

**Ask: 6 / 6 answered, 0 / 6 past the 45 s cut-off, median 6.27 s, max 7.24 s.** Page 200 in 0.1 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "What do you think of this spread?" | 4.12 | yes | bet_analysis | 2026-11-17T18:16:24Z (ts) | 0 |
| free_text "Lakers vs Celtics" | 1.04 | yes | matchup_analysis | 2026-11-17T18:16:24Z (ts) | 0 |
| free_text "top edges today" | 7.24 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (Gent) | 7.12 | yes | bet_analysis | 2026-11-17 (date) | 5 |
| pregame_prop (Ismael Boura Over 0.5) | 4.62 | yes | bet_analysis | **2026-11-20 (date, in future)** | 10 |
| live_row (Under 135.5, Loyola (Chi) Ramblers, NCAAB) | 6.27 | yes | bet_analysis | 2026-11-17T18:16:24Z (ts) | 0 |

A game was live: the `live_row` ask exists (an NCAAB total). The three timestamp answers all carry as_of 18:16:24Z, about 19-20 min old at ask time.

**Web, 12:05-12:36 PM CST (182 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 5, of which 3 hard; max anon 932.8 MB against a 643.5 MB limit.
- Overlay warms: 18, median 7.17 s, 0 over 45 s, 0 over 60 s, max 17.52 s.
- Requests over 20 s: 0. Over 45 s: 0.
- Asks from any client: 11, 0 over 45 s, 0 non-200. 0 of 11 were NOT this probe (all `Python-urllib/3.12`: 5 at 12:05 PM from Reading 4, 6 at 12:35 PM).

**Host:** load 3.40 / 2.69 / 2.89 on 12 cores; MemAvailable 8,651 MB. Top CPU:
- build_soccer_artifacts epl wk12, 99%, ni 0;
- refresh-worker, 90%, ni 0, 3,022 MB, up 1,929 s (the 12:03 PM TERM);
- live-odds-worker, 43%, ni 0, 1,128 MB, up 1,378 s;
- live_resim_workers, 4.5%, ni 5;
- gunicorn, 5.3%, ni 0;
- the probe, 7.1%, ni 19.

The live-odds-worker restarted at 12:13:15 PM CST. The supervisor log reads "exited code=0 after 21751s -- restarting in 5s", just after a 200 MB log rotation. That is a supervised self-exit, not a deploy, and no deploys.md header names it.

**Engine:**
- 2a: `engine-live-prior-f2-read-1117` has 1 run, succeeded (10:30-11:17 AM CST), summary "did NOT PASS". The `f2_verdict.txt` last line (mtime 11:15 AM) is `F2_VERDICT PASS judged_families=12 failed_families=0 cutoff=2026-11-15T20:00:00Z files=2`. Nothing has changed since Reading 4.
- 2b: `engine-learner-m2-gate-read-1124` is enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: the `m2_gate.py` sha256 starts `6915bb6a5ecb80f2`, unchanged.
- 2d: 0 commits on origin/main in the last 40 min touch the five engine files.
- 2e: one fleet load in the last 40 min: `2026-11-17 18:03:56Z (12:03 PM CST) -- DEPLOY (TERM only, no ff)`. That is a drained refresh-worker TERM at fleet `92ae7490a`, loading todo #824 (lane `ncaab-total-overprojection`). Reading 4 was taken 2 min later, and its block did not name this load.

- **ANOMALY:** `as_of_in_future` is true on the pregame_prop ask (soccer, Ismael Boura Over 0.5, as_of 2026-11-20, date kind). This is the same item Readings 2 and 3 flagged. Check next: whether the fixture date is leaking into `as_of` instead of the data time.
- **ANOMALY:** An F2 result exists, and its two sources still disagree: the run summary says "did NOT PASS", while the verdict file says PASS 12/12. This is carried from Reading 4. Check next: the owning session reads run `local_dc76d55c` and records which verdict stands before the 11-24 M2 read.
- **ANOMALY:** New fleet load: the 12:03 PM CST refresh-worker TERM loads #824, the NCAAB totals over-projection fix. It touches live NCAAB totals pricing, the same family where #816 broke the experts' reproduction on 11-16. This reading's live_row ask was an NCAAB total, and it answered normally. Check next: whether the experts/gate reproduction of NCAAB live_resim:totals still matches the live join after 12:03 PM CST.

## Reading 6 (1:06 PM CST)

Probe file `ask_reading_20261117T190556Z.json` (asks 1:06:25-1:08:10 PM CST; web window from 12:35:56 PM).

**Ask: 6 / 6 answered, 0 / 6 past the 45 s cut-off, median 23.53 s, max 31.99 s.** Page 200 in 0.13 s. Median is up about 4x on Reading 5 (6.27 s); see the host line.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "What do you think of this spread?" | 28.80 | yes | bet_analysis | 2026-11-17T18:16:24Z (ts) | 0 |
| free_text "Lakers vs Celtics" | 0.90 | yes | matchup_analysis | 2026-11-17T18:16:24Z (ts) | 0 |
| free_text "top edges today" | 20.06 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (Minnesota Timberwolves) | 23.53 | yes | bet_analysis | 2026-11-16 (date) | 2 |
| pregame_prop (Jaden McDaniels Under 24.5) | 31.99 | yes | bet_analysis | 2026-11-17T18:53:39Z (ts) | 7 |
| live_row (Murray St Racers) | 21.09 | yes | bet_analysis | 2026-11-17T18:16:24Z (ts) | 0 |

A game was live: the `live_row` ask exists. as_of_in_future: 0 / 6. Three answers still carry as_of 18:16:24Z, ~50 min old at ask time; the game-line answer carries yesterday's date.

**Web, 12:36-1:08 PM CST (101 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 7, of which 4 hard; max anon 906.3 MB against a 649.6 MB limit.
- Overlay warms: 24, median 23.3 s, 14 over 20 s, 5 over 45 s, 3 over 60 s, max 136.56 s.
- Requests over 20 s: 14 (POST /api/intelligence/query 6, POST /api/syndicate/query 5, GET /api/board/game-chips 1, GET /intelligence 1, GET /api/portfolio/paper 1). Over 45 s: 2, both POST /api/intelligence/query.
- Asks from any client: 9, 0 over 45 s, 0 non-200. 0 of 9 were NOT this probe (all `Python-urllib/3.12`: 3 at 12:36 PM from Reading 5, 6 at 1:06-1:08 PM).

**Host:** load 10.55 / 10.88 / 9.34 on 12 cores (Reading 5: 3.40); MemAvailable 7,676 MB. Top CPU:
- fetch_soccer_oddsapi_props_local mls, 136%, ni 0 (1 s old);
- refresh-worker, 94%, ni 0, 3,368 MB;
- gunicorn worker, 94%, ni 0, 347 MB, up 11 s (fresh recycle);
- build_soccer_artifacts championship wk14, 93%, ni 0;
- live-odds-worker, 61%, ni 0, 1,148 MB;
- gunicorn worker, 48%, ni 0, 970 MB, up 281 s;
- backup `du -sb`, 45%, ni 19.

**Engine:**
- 2a: `engine-live-prior-f2-read-1117` has 1 run, succeeded (10:30-11:17 AM CST), summary "did NOT PASS". `f2_verdict.txt` (mtime 11:15 AM) last line: `F2_VERDICT PASS judged_families=12 failed_families=0 cutoff=2026-11-15T20:00:00Z files=2`. Unchanged since Reading 4.
- 2b: `engine-learner-m2-gate-read-1124` enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: `m2_gate.py` sha256 starts `6915bb6a5ecb80f2`, unchanged.
- 2d: 1 commit in the last 40 min touches the engine files: `ea723a9d9 engine learner slice 3a: NBA player-prop outcomes from the official box score (player_logs.csv), pregame and live -- the`.
- 2e: one fleet load in the last 40 min: `2026-11-17 18:58:45Z (12:58 PM CST) -- DEPLOY (ff + reload-web): fleet 92ae7490a -> 5db26434e`, loading todo #826 (board query opt-in `row_refs`, lane `board-query-row-refs-load`). Per the 11-17 findings this load also carries `ac2cbc2fc` (render-config step 1) and `2148f99cb` (paper endpoint).

- **ANOMALY:** 3 of 24 overlay warms over 60 s (max 136.56 s), with 5 over 45 s; Reading 5 had 0 over 45 s (max 17.52 s). It coincides with host load ~10.6 on 12 cores (soccer props fetch + soccer artifact build + refresh-worker, all ni 0) and the 12:58 PM reload-web. Check next: whether warm times fall back once the soccer jobs finish, and whether the slow warms cluster just after the reload.
- **ANOMALY:** 2 POST /api/intelligence/query requests over 45 s (none from this probe's Ask route, which maxed at 31.99 s). Check next: their agent and timing in the web log, and whether a user-facing caller saw them.
- **ANOMALY:** An F2 result exists and its two sources still disagree: the run summary says "did NOT PASS", the verdict file says PASS 12/12. Carried from Readings 4-5. Check next: the owning session reads run `local_dc76d55c` and records which verdict stands before the 11-24 M2 read.
- **ANOMALY:** New engine-file commit `ea723a9d9` (learner slice 3a, NBA player-prop outcomes). Check next: that it does not change `m2_gate.py`'s inputs or the frozen M2 population before 11-24.
- **ANOMALY:** New fleet load: 12:58 PM CST ff `92ae7490a -> 5db26434e` + reload-web (#826 row_refs, plus `ac2cbc2fc` and `2148f99cb`). It is web-side (board query), not a live-pricing change as named. Check next: whether the Ask latency jump (median 6.3 s -> 23.5 s) tracks the reload or only the host load.

## Reading 7 (1:56 PM CST)

**Ask:** 6/6 answered, 0 past the 45 s cut-off, median 20.1 s, max 35.95 s (live_row). All 200, all ok, 0 `as_of_in_future`. Page 200 in 0.94 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "this spread?" | 26.98 | yes | bet_analysis | 2026-11-17T18:16:24Z | 0 |
| free_text "Lakers vs Celtics" | 0.90 | yes | matchup_analysis | 2026-11-17T18:16:24Z | 0 |
| free_text "top edges today" | 13.61 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (Jazz @ LA U109.5) | 19.63 | yes | bet_analysis | 2026-11-15 (date) | 2 |
| pregame_prop (McBride U1.5) | 20.10 | yes | bet_analysis | 2026-11-17T17:43:54Z | 7 |
| live_row (Murray St) | 35.95 | yes | bet_analysis | 2026-11-17T18:16:24Z | 0 |

A game was live (a `live_row` ask existed).

**Web, 1:26-1:56 PM CST (62 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 3, all 3 hard, max anon 1008.8 MB vs limit 636.6 MB.
- Overlay warms: 8, median 27.72 s, 6 over 20 s, 1 over 45 s, 1 over 60 s, max 91.51 s.
- Requests over 20 s: 4 (`POST /api/syndicate/query` 3, `POST /api/intelligence/query` 1); over 45 s: 0.
- Asks from any client: 6, 0 over 45 s, 0 non-200; 0 of 6 were NOT this probe's (all `Python-urllib/3.12`).

**Host (12 cores):** load 9.50 / 6.08 / 2.82 (1/5/15 min), MemAvailable 9392 MB. Top CPU: refresh-worker 113% ni 0; gunicorn web worker 106% ni 0 (28 s old); `railload/pivotprof.py` 96.5% ni 19; live-odds-worker 50.6% ni 0; `refresh_nhl_oddsapi.py` 31.6% ni 0; second gunicorn worker 21.5% ni 0; live_resim_workers 14.5% ni 5.

**Engine:**
- 2a: `engine-live-prior-f2-read-1117`: 1 run, status succeeded (started 10:30 AM, last activity 11:17 AM CST), its summary: "did NOT PASS". `f2_verdict.txt` (38 lines, mtime 11:15 AM CST) last line: `F2_VERDICT PASS judged_families=12 failed_families=0 cutoff=2026-11-15T20:00:00Z files=2`.
- 2b: `engine-learner-m2-gate-read-1124` enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: `m2_gate.py` sha256 starts `c1a2c029c2a1816f`, not `6915bb6a5ecb80f2`. The file was rewritten 1:58 PM CST (13995 bytes); `m2gate_kit/amend2/` holds `AMENDMENT2_DRAFT.md` (header still has `__TIME__` / `__YES__` placeholders), `amendment2.diff` (1:56 PM) and a same-size `m2_gate.py` (1:32 PM).
- 2d: 0 engine-file commits on origin/main in the last 40 min.
- 2e: newest deploys.md headers are 1:06/1:07 PM CST READINGs; newest load is the 12:58 PM CST ff + reload-web (#826, `row_refs`), ~58 min before this reading. No fleet load in the last 40 min.

- **ANOMALY:** overlay warm 91.51 s (> 60 s), with 3 hard memory recycles (max anon 1008.8 MB vs 636.6 MB). Check next: the web role log for the warm's route and whether it ran beside a recycle; does it recur in the next reading?
- **ANOMALY:** M2 gate hash changed (`c1a2c029...` ≠ `6915bb6a...`), the file rewritten at 1:58 PM CST, apparently by Amendment 2 (draft still unfilled: `__TIME__`, `__YES__`). Check next: the lane owner confirms the user registered Amendment 2, the draft's placeholders are filled, and the M2 task prompt's expected hash is updated before 11-24.
- **ANOMALY:** F2 result in. The run summary says "did NOT PASS", but `f2_verdict.txt`'s last line says `PASS ... failed_families=0`. Check next: read the F2 run's session (local_dc76d55c) and the whole verdict file to settle which is the recorded verdict.

## Reading 8 (2:03 PM CST)

Probe 2:03:04-2:03:56 PM CST (`ask_reading_20261117T200304Z.json`); page 200 in 0.22 s; shortlist 200, 200 rows, 2.31 s.

**Ask:** 6 of 6 answered, 0 of 6 past the 45 s cut-off, median 10.54 s, max 11.85 s. All 6 status 200, ok, `answer_source` snapshot, no transport error.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "spread" | 1.56 | yes | bet_analysis | 18:16:24Z (ts, age 1.8 h) | 0 |
| free_text "Lakers vs Celtics" | 2.79 | yes | matchup_analysis | 18:16:24Z (ts) | 0 |
| free_text "top edges today" | 11.85 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line NBA UTA@LAC h1 Under 109.5 | 11.17 | yes | bet_analysis | 2026-11-15 (date) | 2 |
| pregame_prop NBA McBride threes U1.5 | 5.33 | yes | bet_analysis | 17:43:54Z (ts, age 2.3 h) | 7 |
| live_row WNCAAB Murray St @ Oregon h2h | 10.54 | yes | bet_analysis | 18:16:24Z (ts) | 0 |

`as_of_in_future`: 0 of 6. A game was live: yes (a `live_row` ask exists).

**Web, 1:33-2:03 PM CST** (69 requests; the window spans the 1:48:57 PM host restart, so it mixes two web processes):
- WORKER TIMEOUT kills: 0.
- Memory recycles: 5, all 5 hard; max anon 1008.8 MB vs limit 641.5 MB.
- Overlay warms: 17, median 24.81 s; 11 over 20 s, 3 over 45 s, 1 over 60 s; max 91.51 s.
- Requests over 20 s: 6 (POST /api/syndicate/query 3, POST /api/intelligence/query 2, GET /intelligence 1). Over 45 s: 0.
- Asks from any client: 12, 0 over 45 s, 0 non-200. All 12 are `Python-urllib/3.12`, so 0 from a non-probe client. 6 at 1:57-1:58 PM ran 0.9-29.4 s (first requests after the restart).

**Host:** load 7.22 / 6.98 / 4.09 on 12 cores; MemAvailable 9441 MB. Top CPU, all nice 0: soccer OddsAPI fetch (serie_a) 139%; refresh-worker 122%; NHL OddsAPI refresh 64%; live-odds-worker 64%; two gunicorn workers 59% and 55% (ages 24 s and 7 s, i.e. just recycled).

**Engine:**
- 2a F2: 1 run total (10:30-11:17 AM CST, NOT PASSED, recorded `c765eec64`); no newer run.
- 2b M2: `engine-learner-m2-gate-read-1124` enabled, fireAt 2026-11-24T16:30:00Z.
- 2c `m2_gate.py` sha256 `c1a2c029c2a1816f...` = Amendment 2.
- 2d Engine-file commits on origin/main in the last 40 min: 0.
- 2e deploys.md: a user-initiated Windows restart at 1:48:57 PM CST, then a fleet `up` at 1:51:31 PM CST on commit `5db26434e` (entry 20:02:54Z, betting change: no). That `up` started all three roles. The workers last loaded `92ae7490a`, so they now run the code from the 12:58 PM ff. It was also the first `up` built from `fleet_role_spec.json` + `fleet_env/`.

- **ANOMALY:** 1 of 17 overlay warms took over 60 s (max 91.51 s); 3 took over 45 s. These probably came right after the restart, with cold caches and the host under load. Next: check whether warms over 60 s still appear in the next reading's window, which has no restart in it.
- **ANOMALY:** New fleet load. Host restart + `up` at 1:51:31 PM CST put refresh-worker and live-odds-worker on `5db26434e`, from `92ae7490a`. This is the first launcher-spec/`fleet_env` `up` (`[web] ANTHROPIC_API_KEY` declared with no value). Next: lane `render-config-retirement`'s owed environ compare. Also check that Ask answers and live-row pricing stay consistent through the evening slate. Note the Ask `as_of` of 18:16:24Z predates the restart.

## Reading 9 (2:34 PM CST)

Probe started 20:34:56Z (2:34 PM CST); file `C:\tmp\elp\askmon\readings\ask_reading_20261117T203456Z.json`.

**Ask:** 5 of 5 answered, 0 of 5 past the 45 s cut-off, median 3.1 s, max 7.4 s. Page 200 in 0.06 s; shortlist 200 in 2.15 s (200 rows). All answers `answer_source=snapshot`.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "What do you think of this spread?" | 3.10 | True | bet_analysis | 2026-11-17T20:17:26Z (age 1053 s) | 0 |
| free_text "Lakers vs Celtics" | 0.51 | True | matchup_analysis | 2026-11-17T20:17:26Z (age 1054 s) | 0 |
| free_text "top edges today" | 7.40 | True | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NBA, Lakers h2h) | 5.51 | True | bet_analysis | 2026-11-15 (date) | 2 |
| pregame_prop (NBA, McBride threes U1.5) | 1.95 | True | bet_analysis | 2026-11-17T17:43:54Z (age 10286 s) | 7 |

No `live_row` ask: no game was live. `as_of_in_future` false on 5 of 5.

**Web, 20:04:56Z-20:35Z (2:04-2:35 PM CST), 137 requests:**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 8 (7 hard), max anon 956.1 MB vs limit 649.2 MB.
- Overlay warms: 23, median 10.61 s, 4 over 20 s, 1 over 45 s, 0 over 60 s, max 49.48 s.
- Requests over 20 s: 1 (`POST /api/intelligence/query`); over 45 s: 0.
- Asks from any client: 5, 0 over 45 s, 0 non-200; 0 of 5 NOT this probe (all `Python-urllib/3.12`).

**Host:** load 2.11 / 2.46 / 3.21 on 12 cores; MemAvailable 8434 MB. Top CPU: refresh-worker 108% (ni 0, RSS 3385 MB), live-odds-worker 53% (ni 0), three `<defunct>` python children 15-22% (ni 0, 16 s old), live_resim_workers x2 ~7% (ni 5), gunicorn 5.5% (ni 0).

**Engine:**
- 2a: `engine-live-prior-f2-read-1117` has 1 run total (16:30-17:17Z, 10:30-11:17 AM CST, "did NOT PASS") -- the one already recorded on main (`c765eec64`); no newer run.
- 2b: `engine-learner-m2-gate-read-1124` enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: `m2_gate.py` sha256 `c1a2c029c2a1816f...` -- matches Amendment 2.
- 2d: 0 commits to the engine files on origin/main in the last 40 min.
- 2e: deploys.md headers stamped since 19:55Z are all READINGs (19:56:39Z, 19:56:53Z, 19:58:28Z, 20:02:54Z); no new FLEET ff / DEPLOY / restart. The host reboot's `up` (19:50:39Z, `5db26434e`) is ~44 min old, just outside this window.

No anomaly.

## Reading 10 (3:05 PM CST)

Probe `ask_reading_20261117T210454Z.json` (asks 3:04:56-3:05:10 PM CST; web window 2:34:54-3:05 PM CST).

**Ask:** 5 / 5 answered, 0 past the 45 s cut-off, median 2.58 s, max 4.91 s. Shortlist 200 in 0.81 s (200 rows).

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "spread?" | 2.58 | True | bet_analysis | 2026-11-17T20:59:53Z | 0 |
| free_text "Lakers vs Celtics" | 2.47 | True | matchup_analysis | 2026-11-17T20:59:53Z | 0 |
| free_text "top edges today" | 4.91 | True | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NBA UTA@LAC H1 Under 109.5) | 3.81 | True | bet_analysis | 2026-11-15 (date) | 2 |
| pregame_prop (Henderson U1.5) | 1.71 | True | bet_analysis | 2026-11-17T20:54:26Z | 7 |

No `live_row` ask: no live game in the shortlist. `as_of_in_future` false on 5 / 5. (The game-line ask's as_of is a 2-day-old date, 2026-11-15; noted, not a rule breach.)

**Web (2:34-3:05 PM CST, 73 requests):** WORKER TIMEOUT kills 0. Memory recycles 3 (3 hard, max anon 986.5 MB vs limit 645.8 MB). Overlay warms 18: median 4.91 s, 0 over 45 s, 0 over 60 s, max 9.93 s. Requests over 20 s: 0; over 45 s: 0. Asks from any client 10, 0 over 45 s, 0 non-200; 0 of 10 were not this probe's (all `Python-urllib`; the 5 at 2:34-2:35 PM are reading 9's).

**Host:** load 2.36 / 2.35 / 2.33 on 12 cores; MemAvailable 8,403 MB. Top CPU: build_soccer_artifacts (mls wk34) 99.7% ni 0; refresh-worker 95.1% ni 0 (3,452 MB RSS); fetch_espn_live_status 71.4% ni 0; live-odds-worker 43.6% ni 0; live_resim_workers x2 ~4.5% ni 5; gunicorn web 3.3% ni 0; this probe 2.3% ni 19.

**Engine:**
- 2a F2: 1 run total (16:30-17:17Z, 10:30-11:17 AM CST, "did NOT PASS"), already on main `c765eec64`; no newer run.
- 2b `engine-learner-m2-gate-read-1124`: enabled, fireAt 2026-11-24T16:30:00Z.
- 2c `m2_gate.py` sha256 `c1a2c029c2a1816f...` = Amendment 2.
- 2d engine-file commits on origin/main in the last 40 min: none.
- 2e deploys.md headers in the last 40 min: one, 20:52Z (2:52 PM CST), a READING (no deploy): `2148f99cb`'s refresh-worker half is live (paper all-dates record; lane `portfolio-monitor`). It is not a new load in the window; refresh-worker and live-odds-worker etimes 4,130 s (up since ~1:56 PM CST, the host reboot). Paper endpoint, not live pricing.

No anomaly.

## Reading 11 (3:35 PM CST)

Probe 3:35:30-3:38:04 PM CST (`ask_reading_20261117T213530Z.json`), against http://127.0.0.1:10000. The page returned 200 in 0.12 s and the shortlist returned 200 in 2.21 s (200 rows).

**Ask:** 4 of 5 answered. 1 of 5 went past the 45 s cut-off. Median 19.69 s, max 73.64 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "What do you think of this spread?" | 73.64 | **no** (RemoteDisconnected, no status; user would see the timeout) | - | - | - |
| free_text "Lakers vs Celtics" | 24.04 | yes | matchup_analysis | 2026-11-17T21:02:56Z (2,063 s old) | 0 |
| free_text "top edges today" | 13.98 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NBA h2h, Portland Trail Blazers) | 19.69 | yes | bet_analysis | 2026-11-16 (date) | 2 |
| pregame_prop (NBA player_threes, Miles McBride U1.5) | 4.65 | yes | bet_analysis | 2026-11-17T17:43:54Z (14,049 s old) | 7 |

- `as_of_in_future`: 0 of 4.
- No game was live: there is no `live_row` ask.

**Web, 3:05:30 PM CST onward (66 requests):**
- WORKER TIMEOUT kills: **1**, at **3:36:36 PM CST**. That is inside this probe and matches the "spread" ask's disconnect. The web access log carries no row for that ask, so it shows 4 asks, not 5.
- Memory recycles: 5, 4 of them hard. Max anon 881.9 MB against a 644.9 MB limit.
- Overlay warms: 17. Median 6.02 s, max 13.41 s; 0 over 45 s, 0 over 60 s.
- Requests over 20 s: `POST /api/syndicate/query` x2. Over 45 s: 0 logged (the killed request is not logged).
- Asks from any client: 4. 0 over 45 s, 0 non-200. All 4 are `Python-urllib`, so 0 came from outside this probe.

**Host:** load 12.57 / 8.51 / 4.85 on 12 cores, so the 1-minute load was at the core count and rising. MemAvailable 8,129 MB. Top CPU:
- `build_soccer_artifacts` (ligue_1, ni 0): 107%
- `build_cheat_sheets` (ni 19): 96%
- refresh-worker (ni 0): 91% at 3,460 MB RSS
- live-odds-worker (ni 0): 42%
- gunicorn web workers (ni 0): 20% and 12%
- `refresh_odds_sources` (ni 0): 15%

**Engine:**
- 2a: `engine-live-prior-f2-read-1117` still has 1 run (10:30-11:17 AM CST, NOT PASSED; recorded at `c765eec64`). No newer run.
- 2b: `engine-learner-m2-gate-read-1124` is enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: `m2_gate.py` sha256 starts `c1a2c029c2a1816f`, which is Amendment 2.
- 2d: no engine-file commits on origin/main in the last 40 min.
- 2e: no fleet ff, DEPLOY or restart header in the last 40 min. The newest header in that list is the 2:52 PM CST READING (no deploy).

- **ANOMALY:** the free_text ask "What do you think of this spread?" was not answered. It disconnected at 73.64 s with no status, past the 45 s cut-off. Check next: the web log around 3:36:36 PM CST, for what that gunicorn worker was doing (the query path vs the overlay). Also check whether the vague "spread" question without context routes to a full-form scan, the I-16 shape.
- **ANOMALY:** a WORKER TIMEOUT kill at 3:36:36 PM CST. This probe's own ask was the victim, and it came under host load at the core count (soccer artifact build at ni 0, cheat-sheet build, refresh-worker). Check next: whether the kill repeats in the next reading at lower load, and the 4 hard recycles (881.9 MB vs the 644.9 MB limit).

## Reading 12 (4:05 PM CST)

Probe 22:05:10-22:05:37Z (4:05 PM CST); web window from 21:35:10Z (3:35 PM CST). File `C:\tmp\elp\askmon\readings\ask_reading_20261117T220510Z.json`.

**Ask:** 5/5 answered, 0 past 45 s, median 4.50 s, max 9.23 s. Page 200 in 0.07 s; shortlist 200, 200 rows, 0.71 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "this spread?" | 9.23 | True | bet_analysis | 2026-11-17T21:02:56Z (age 3,747 s) | 0 |
| free_text "Lakers vs Celtics" | 1.81 | True | matchup_analysis | 2026-11-17T21:02:56Z | 0 |
| free_text "top edges today" | 4.64 | True | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line NBA NYK@TOR Q1 Under 55.5 | 4.50 | True | bet_analysis | 2026-11-15 (date) | 2 |
| pregame_prop McBride threes Under 1.5 | 2.27 | True | bet_analysis | 2026-11-17T17:43:54Z (age 15,703 s) | 7 |

No `live_row` ask, so the shortlist had no live game. `as_of_in_future` false on 5/5.

**Web (21:35Z-22:05Z, 203 requests):**
- WORKER TIMEOUT kills: 1, at 21:36:36Z (3:36 PM CST).
- Memory recycles: 5 (3 hard); max anon 960 MB vs the 641.6 MB limit.
- Overlay warms: 10; median 11.08 s; 1 over 20 s; 0 over 45 s; 0 over 60 s; max 21.07 s.
- Over 20 s: `POST /api/syndicate/query` 2, `POST /api/intelligence/query` 1. Over 45 s: 0.
- Asks from any client: 9; 0 over 45 s; 0 non-200. 0 of 9 were non-probe (all `Python-urllib/3.12`). The 4 at 21:37Z (max 26.7 s) were the previous reading's probe.

**Host:** load average 3.89 / 3.67 / 3.91 on 12 cores; MemAvailable 9,496 MB. Top CPU:
- refresh-worker 114% (ni 0, 2,475 MB, up 696 s);
- `build_soccer_artifacts` epl wk12 107% (ni 0);
- cloud-init status 79% (ni 0);
- live-odds-worker 50% (ni 0, up 696 s);
- gunicorn web 20% (ni 0, up 129 s);
- live_resim_workers 6% (ni 5).

The workers' 696 s uptime matches the 3:52 PM full down/up.

**Engine:**
- 2a: F2 has 1 run (10:30-11:17 AM CST, succeeded, "did NOT PASS"), already recorded at `c765eec64`. No newer run.
- 2b: `engine-learner-m2-gate-read-1124` is enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: `m2_gate.py` sha256 starts `c1a2c029c2a1816f`, unchanged.
- 2d: 1 engine-file commit in the last 40 min: `85af16b35` (3:39 PM CST) "engine experts: an evidence row's instant is the later of its tick and its state (FEATURE_STATE_INSTANT) -- NHL / NCAAF". It is not in fleet `25fc2e4f0`.
- 2e: two fleet loads in the last 40 min:
  - 3:52 PM CST: DEPLOY ff + drained full down/up, `5db26434e` -> `91d865fd5` (render-config-retirement steps 2 + 3a, #766);
  - 3:56 PM CST: DEPLOY ff + reload-web, `91d865fd5` -> `25fc2e4f0` (board-query diagnostic strip, #827).

  `5db26434e..25fc2e4f0` touches 36 files under `syndicate/`, among them `execution_ledger.py`, `live_refresh_loop.py`, `game_board_contract.py`, `mlb/cards.py`, `nba/cards.py` and `nba/live_tick/tick.py`.

**Anomalies:**
- **ANOMALY:** 1 WORKER TIMEOUT kill at 3:36:36 PM CST, before both loads. Check next: the web role log around 21:36Z for the killed request's route. The 21:37Z probe asks ran 13.98-26.7 s, against 1.81-9.23 s now.
- **ANOMALY:** new engine-file commit `85af16b35` (3:39 PM CST, experts evidence-row instant, NHL / NCAAF). Check next: its lane's ledger entry. Does it change the experts' reproduction that F2 depends on? It is not loaded on the fleet.
- **ANOMALY:** new fleet loads at 3:52 PM CST (full down/up -> `91d865fd5`) and 3:56 PM CST (reload-web -> `25fc2e4f0`). The range touches live-path files (`execution_ledger`, `live_refresh_loop`, `game_board_contract`, NBA live tick, cards). Check next: whether either deploy changed what the live join serves. Use the deploys.md `verify:` lines and a next experts reproduction. Watch whether web recycles (5 in 30 min, max anon 960/641.6 MB) settle after the reload.

## Reading 13 (4:35 PM CST)

Probe ran 4:35:11-4:35:44 PM CST (`ask_reading_20261117T223511Z.json`).

**Ask:** 6 of 6 answered, 0 past the 45 s cut-off, median 4.67 s, max 7.80 s. Page 200 in 0.1 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "spread?" | 7.80 | yes | bet_analysis | 2026-11-17T22:08:55Z | 0 |
| free_text "Lakers vs Celtics" | 5.66 | yes | matchup_analysis | 2026-11-17T22:08:55Z | 0 |
| free_text "top edges today" | 4.67 | yes | market_summary | 2026-11-17 | 1 |
| pregame_game_line | 4.58 | yes | bet_analysis | 2026-11-15 | 2 |
| pregame_prop | 2.19 | yes | bet_analysis | 2026-11-17T22:29:30Z | 7 |
| live_row (Notre Dame Under 63.5) | 4.09 | yes | bet_analysis | 2026-11-13 | 2 |

A game was live: a `live_row` ask exists. as_of_in_future: 0 of 6.

**Web, 4:05-4:35 PM CST (239 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 4, of which 2 were hard; max anon 986.6 MB against a 641.8 MB limit.
- Overlay warms: 14, median 14.0 s, 2 over 20 s, 0 over 45 s, 0 over 60 s, max 30.6 s.
- Requests over 20 s: 1 (`POST /api/intelligence/query`). Over 45 s: 0.
- Asks from any client: 11, 0 over 45 s, 0 non-200. 0 of 11 were from another client: all were `Python-urllib`, 5 from Reading 12's probe and 6 from this one.

**Host:** load 4.19 / 3.24 / 3.37 on 12 cores; MemAvailable 8,044 MB. Top CPU:
- soccer artifact build (belgian_pro_league), ni 0, 108%;
- refresh-worker, ni 0, 100%, 3.5 GB RSS;
- live-odds-worker, ni 0, 50%;
- `refresh_nhl_oddsapi`, ni 0, 49%;
- live_resim_workers, ni 5, about 4% each;
- gunicorn web, ni 0, 3.6%.

**Engine:**
- 2a: F2 has 1 run (10:30-11:17 AM CST, NOT PASSED, already recorded at `c765eec64`). No newer run.
- 2b: `engine-learner-m2-gate-read-1124` is enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: `m2_gate.py` sha256 starts `c1a2c029c2a1816f` (Amendment 2). Unchanged.
- 2d: 0 engine-file commits on origin/main in the last 40 min.
- 2e: the newest header is 3:56 PM CST, DEPLOY ff + reload-web `91d865fd5` -> `25fc2e4f0` (#827). It falls 39.7 min ago, at the edge of the window. Reading 12 already flagged it, so it is not a new load. No fleet load since then.

No anomaly.

## Reading 14 (5:06 PM CST)

Probe ran 5:06:06-5:07:10 PM CST (`ask_reading_20261117T230606Z.json`).

**Ask:** 5 of 5 answered, 0 past the 45 s cut-off, median 10.29 s, max 17.44 s. Page 200 in 0.15 s. Slower than Reading 13 (median 4.67 s, max 7.80 s); the host was busier (below).

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "spread?" | 10.26 | yes | bet_analysis | 2026-11-17T22:08:55Z | 0 |
| free_text "Lakers vs Celtics" | 0.82 | yes | matchup_analysis | 2026-11-17T22:08:55Z | 0 |
| free_text "top edges today" | 10.29 | yes | market_summary | 2026-11-17 | 1 |
| pregame_game_line (Buccaneers) | 15.10 | yes | bet_analysis | 2026-11-15 | 5 |
| pregame_prop (C.J. Stroud Under 1.5) | 17.44 | yes | bet_analysis | 2026-11-17T22:57:48Z | 9 |

No game was live in the probe's rows: no `live_row` ask. as_of_in_future: 0 of 5.

**Web, 4:36-5:06 PM CST (62 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 5, of which 4 were hard; max anon 1,018.9 MB against a 645.9 MB limit.
- Overlay warms: 30, median 5.18 s, 1 over 20 s, 0 over 45 s, 0 over 60 s, max 31.17 s.
- Requests over 20 s: 0. Over 45 s: 0.
- Asks from any client: 5, 0 over 45 s, 0 non-200. 0 of 5 were from another client: all `Python-urllib`, this probe's.

**Host:** load 6.33 / 4.37 / 3.09 on 12 cores (rising); MemAvailable 7,693 MB. Top CPU:
- soccer artifact build (serie_a), ni 0, 107%;
- refresh-worker, ni 0, 91%, 3.4 GB RSS;
- `refresh_nhl_oddsapi`, ni 0, 74%;
- `fetch_espn_live_status_for_date`, ni 0, 72%;
- `refresh_odds_sources`, ni 0, 49%;
- live-odds-worker, ni 0, 44%;
- gunicorn web, ni 0, 42% (113 s old, a fresh recycle);
- live_resim_workers, ni 5, about 4%.

**Engine:**
- 2a: F2 has 1 run (10:30-11:17 AM CST, NOT PASSED, already recorded at `c765eec64`). No newer run.
- 2b: `engine-learner-m2-gate-read-1124` is enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: `m2_gate.py` sha256 starts `c1a2c029c2a1816f` (Amendment 2). Unchanged.
- 2d: 0 engine-file commits on origin/main in the last 40 min.
- 2e: the newest header is still 3:56 PM CST (DEPLOY ff + reload-web `91d865fd5` -> `25fc2e4f0`, #827), 71 min ago and already flagged by Reading 12. No fleet load in the last 40 min.

No anomaly.

## Reading 15 (5:35 PM CST)

Probe 23:35:20-23:36:05Z (5:35-5:36 PM CST), read-only, nice 19. Page 200 in 0.08 s; shortlist 200, 200 rows, 2.15 s.

**Ask:** 5 / 5 answered, 0 past the 45 s cut-off, 0 user-visible timeouts; median 10.35 s, max 14.34 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "What do you think of this spread?" | 11.38 | yes | bet_analysis | 23:00:45Z (2087 s old) | 0 |
| free_text "Lakers vs Celtics" | 0.81 | yes | matchup_analysis | 23:00:45Z (2088 s old) | 0 |
| free_text "top edges today" | 10.35 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NFL TB h2h) | 14.34 | yes | bet_analysis | 2026-11-15 (date) | 5 |
| pregame_prop (NFL Stroud U1.5 pass TD) | 2.00 | yes | bet_analysis | 23:11:42Z (1463 s old) | 9 |

No `live_row` ask: no live game row on the shortlist. as_of_in_future: 0 of 5.

**Web, 23:05-23:36Z (5:05-5:36 PM CST), 263 requests:**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 18 (14 hard); max anon 1054.6 MB vs 648.2 MB limit.
- Overlay warms: 47; median 13.43 s; 12 over 20 s, 1 over 45 s, 1 over 60 s; max 73.42 s.
- Requests over 20 s: POST /api/intelligence/query 3, GET / 1. Over 45 s: POST /api/intelligence/query 1, GET / 1.
- Asks from any client: 10, 0 over 45 s, 0 non-200; all 10 are probe traffic (`Python-urllib`; 5 from Reading 14 at 23:06Z, 5 from this one), 0 from other clients. So the >45 s POST /api/intelligence/query is not an Ask row in this log.

**Host:** load 4.83 / 4.09 / 4.10 on 12 cores; MemAvailable 8268 MB. Top CPU: fetch_espn_live_status (ni 0, 100%, transient), refresh-worker (ni 0, 84%, 3451 MB), web gunicorn x2 (ni 0, 68% / 52%, both ~85 s old = fresh recycles), live-odds-worker (ni 0, 62%, 613 s old), live_resim_workers x2 (ni 5, 23% each), probe (ni 19, 3%).

**Engine:**
- 2a F2: 1 run total (16:30-17:17Z, 10:30-11:17 AM CST, "did NOT PASS"), already on main `c765eec64`; no newer run.
- 2b `engine-learner-m2-gate-read-1124`: enabled, fireAt 2026-11-24T16:30:00Z.
- 2c `m2_gate.py` sha256 `c1a2c029c2a1816f...`: matches Amendment 2.
- 2d engine-file commits on origin/main in the last 40 min: 0.
- 2e fleet loads in the last 40 min: 2 (23:15:44Z ff + reload-web `25fc2e4f0` -> `64daca46f`, todo #828 board-query serialize-once; 23:22:26Z live-odds-worker TERM at `64daca46f`, todo #829 WNBA live box-score poll skip).

- **ANOMALY:** overlay warm of 73.42 s (> 60 s) in the window. Check next: the web log for which overlay and when; whether it sits with the 23:15:44Z reload-web or a hard recycle (18 recycles, 14 hard, in 30 min).
- **ANOMALY:** new fleet load 23:15:44Z (5:15 PM CST), ff + reload-web to `64daca46f` (todo #828, board query serialize-once). Web-only display path, not pricing; check next: the 23:30Z deploys.md reading for #828 and whether the >45 s POST /api/intelligence/query is board-query traffic.
- **ANOMALY:** new fleet load 23:22:26Z (5:22 PM CST), live-odds-worker TERM (todo #829 live-capture half, WNBA box-score poll). Touches the live-capture worker, not the experts' priced families directly; check next: whether the live join's served rows changed after 23:22Z before the next experts reproduction.

## Reading 16 (6:05 PM CST)

Probe 6:05:13-6:06:00 PM CST (00:05Z 11-18), file `ask_reading_20261118T000513Z.json`.

**Ask:** 6 / 6 answered, 0 past the 45 s cut-off, median 6.79 s, max 11.76 s. Page 200 in 0.1 s; shortlist 200 in 1.17 s (200 rows).

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "this spread?" | 11.76 | yes | bet_analysis | 23:11:20Z (54 min) | 0 |
| free_text "Lakers vs Celtics" | 4.81 | yes | matchup_analysis | 23:11:20Z | 0 |
| free_text "top edges today" | 5.21 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NCAAB h2h, Arkansas) | 6.43 | yes | bet_analysis | 23:11:20Z | 0 |
| pregame_prop (NBA, Jrue Holiday U16.5 PR) | 6.79 | yes | bet_analysis | 22:28:46Z (97 min) | 6 |
| live_row (NCAAB h2h, UMass Lowell) | 6.96 | yes | bet_analysis | 23:11:20Z | 0 |

A game was live (a `live_row` ask exists). `as_of_in_future` false on 6 / 6. All answers `answer_source=snapshot`; the snapshot `as_of` is 54 min old (23:11:20Z).

**Web, 5:35-6:05 PM CST (235 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 17 (14 hard); max anon 1032.2 MB vs limit 649.6 MB.
- Overlay warms: 44, median 10.26 s, 7 over 20 s, 0 over 45 s, 0 over 60 s, max 43.3 s.
- Requests over 20 s: `POST /api/intelligence/query` 3; over 45 s: none.
- Asks from any client: 11, 0 over 45 s, 0 non-200; 0 of 11 were NOT the probe (all `Python-urllib`: 5 from Reading 15's run at 5:35 PM, 6 from this one).

**Host:** load 6.24 / 5.08 / 4.40 on 12 cores; MemAvailable 5354 MB. Top CPU: build_soccer_artifacts (serie_a) 104% ni 0; local_watchdog 100% ni 0 (0 s old); refresh-worker 88% ni 0 (RSS 3621 MB); gunicorn web 56.6% ni 0 (40 s old); live-odds-worker 52.7% ni 0; m3_launch replay --rehearse 40.6% ni 19 (RSS 2360 MB); refresh_ncaab_odds_history 25.7% ni 0; live_resim_workers 20.8% ni 5.

**Engine:**
- 2a F2: still 1 run (10:30-11:17 AM CST, succeeded, "did NOT PASS"), already on main `c765eec64`; no newer run.
- 2b M2: `engine-learner-m2-gate-read-1124` enabled, fireAt 2026-11-24T16:30:00Z.
- 2c gate hash: `c1a2c029c2a1816f...` (Amendment 2) unchanged.
- 2d engine-file commits on origin/main in the last 40 min: none.
- 2e deploys.md headers since 5:26 PM CST: 5:30 PM READING (no deploy); 5:46 PM DEPLOY ATTEMPT ABORTED, NOTHING LOADED (`3f337b2d9`, #809, lane `ncaaf-grid-build-speed`); 5:54 PM READING (no deploy). No new fleet load.

No anomaly.

Notes, not anomalies: 17 recycles (14 hard) in 30 min is high for 235 requests, and the web worker was 40 s old at the probe. No request was killed and no Ask passed 20 s. Check next: whether the recycle rate tracks the 5:15 PM serialize-once load (#828) or the refresh-worker's 3.6 GB RSS. The ask snapshot is 54 min old; Reading 15 attributed this to the refresh-worker deploy drain holding board builds.

## Reading 17 (6:34 PM CST)

Probe 6:34:59-6:35:31 PM CST (`ask_reading_20261118T003459Z.json`). Page 200 in 0.12 s; shortlist 200 in 2.31 s (200 rows).

**Ask:** 6 / 6 answered, 0 past the 45 s cut-off, 0 user-saw-timeout. Median 6.25 s, max 7.86 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "What do you think of this spread?" | 6.28 | True | bet_analysis | 2026-11-17T23:11:20Z | 0 |
| free_text "Lakers vs Celtics" | 1.27 | True | matchup_analysis | 2026-11-17T23:11:20Z | 0 |
| free_text "top edges today" | 7.86 | True | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (ncaab, Houston @ Florida) | 6.25 | True | bet_analysis | 2026-11-17T23:11:20Z | 0 |
| pregame_prop (soccer, Boura SOT o0.5, Le Havre @ Troyes) | 6.25 | True | bet_analysis | 2026-11-20 (date, **in future**) | 10 |
| live_row (ncaab, Villanova @ Pittsburgh) | 1.13 | True | bet_analysis | 2026-11-17T23:11:20Z | 0 |

A game was live (a `live_row` ask exists). `as_of_in_future` true on 1 / 6 (the soccer prop's date-kind as_of). All answers `answer_source=snapshot`; the snapshot `as_of` is still 23:11:20Z, now 84 min old (54 min at reading 16): it has not advanced in this window.

**Web (6:04-6:35 PM CST, 97 requests):** WORKER TIMEOUT kills 0. Memory recycles 8, all hard; max anon 1133.7 MB vs limit 649.1 MB. Overlay warms 50: median 7.37 s, 2 over 20 s, 0 over 45 s, 0 over 60 s, max 23.28 s. Requests over 20 s: 0; over 45 s: 0. Asks from any client: 12, 0 over 45 s, 0 non-200. All 12 are `Python-urllib` (6 from the 6:05 PM probe, 6 from this one), so 0 from other clients.

**Host:** load 5.91 / 4.18 / 3.98 on 12 cores; MemAvailable 7499 MB. Top CPU: build_soccer_artifacts (belgian_pro_league) 99% ni 0; refresh-worker 89% ni 0 (4.0 GB RSS); gunicorn web worker 88% ni 0 (10 s old, just recycled); live-odds-worker 52% ni 0; 2 x live_resim_workers 31% ni 5; refresh_ncaab_odds_history 16% ni 0.

**Engine:**
- 2a F2: 1 run total (10:30-11:17 AM CST, "did NOT PASS"), already on main `c765eec64`; no newer run.
- 2b M2 task `engine-learner-m2-gate-read-1124`: enabled, fireAt 2026-11-24T16:30:00Z.
- 2c `m2_gate.py` sha256 `c1a2c029c2a1816f...`: matches Amendment 2.
- 2d engine-file commits on origin/main in the last 40 min: none.
- 2e deploys.md: newest header 23:54Z (5:54 PM CST, a READING, no deploy), 41 min before this reading; no fleet ff / deploy / restart in the last 40 min.

- **ANOMALY:** `as_of_in_future` true on the pregame_prop ask (soccer, Ismael Boura SOT over 0.5, Le Havre @ Troyes): `as_of` = 2026-11-20 (date kind), 3 days ahead. Check next: whether the soccer prop answer stamps `as_of` from the event/kickoff date instead of the snapshot time (reading 16 had 0 of 6 in the future).

## Reading 18 (7:05 PM CST)

**Ask:** 6 of 6 answered, 0 of 6 past 45 s, 0 timeouts the user saw. Median 5.39 s, max 6.46 s. The page answered 200 in 0.19 s.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "spread?" | 1.12 | yes | bet_analysis | 2026-11-17T23:11:20Z | 0 |
| free_text "Lakers vs Celtics" | 0.57 | yes | matchup_analysis | 2026-11-17T23:11:20Z | 0 |
| free_text "top edges today" | 5.42 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NBA MIN h2h) | 6.46 | yes | bet_analysis | 2026-11-16 (date) | 2 |
| pregame_prop (Clingan O12.5) | 2.35 | yes | bet_analysis | 2026-11-18T00:33:37Z | 7 |
| live_row (NBA NYK@TOR alt spread h1) | 5.39 | yes | bet_analysis | 2026-11-15 (date) | 2 |

A game was live: a `live_row` ask exists (NBA Knicks @ Raptors). Its `as_of` is a date two days back (2026-11-15). This is not on the anomaly list, but note it.

**Web, 6:35-7:05 PM CST (106 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 11, of which 10 were hard. Max anon was 1146 MB against a 648.5 MB limit.
- Overlay warms: 64. Median 8.05 s; 0 over 45 s and 0 over 60 s; max 18.79 s.
- Requests over 20 s: 0. Over 45 s: 0.
- Asks from any client: 12. None over 45 s and none non-200. 0 of 12 came from a client other than this probe.

**Host (12 cores):**
- Load 3.77 / 3.78 / 3.70.
- MemAvailable 7704 MB.
- Top CPU:
  - WNBA fetch-injuries CLI, 315% (ni 0, transient);
  - refresh-worker, 89% (ni 0, 4.2 GB RSS);
  - gunicorn web, 63% (ni 0, 17 s old);
  - live-odds-worker, 53% (ni 0);
  - live_resim_workers ×2, about 35% each (ni 5).

**Engine:**
- 2a: F2 has one run in total (10:30-11:17 AM CST, "did NOT PASS"). It is the one already recorded at `c765eec64`, and no newer run exists.
- 2b: `engine-learner-m2-gate-read-1124` is still enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: the `m2_gate.py` sha256 starts `c1a2c029c2a1816f` (Amendment 2), unchanged.
- 2d: no commits to the engine files on origin/main in the last 40 minutes.
- 2e: the newest deploys.md header is 23:54Z (5:54 PM CST, a reading with no deploy). No fleet ff, deploy or restart since 6:25 PM CST.

No anomaly.

## Reading 19 (7:35 PM CST)

Probe 7:35-7:37 PM CST (01:35:28Z). Web window from 7:05 PM CST (01:05Z), 108 requests.

**Ask:** 6 / 6 answered, 0 past the 45 s cut-off, median 8.99 s, max 33.86 s. A game was live (a `live_row` ask exists: Knicks @ Raptors total).

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text (spread) | 5.11 | yes | bet_analysis | 2026-11-17T23:11:20Z | 0 |
| free_text (Lakers vs Celtics) | 0.82 | yes | matchup_analysis | 2026-11-17T23:11:20Z | 0 |
| free_text (top edges) | 31.84 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line | 33.86 | yes | bet_analysis | 2026-11-16 (date) | 2 |
| pregame_prop | 8.99 | yes | bet_analysis | 2026-11-18T00:33:24Z | 7 |
| live_row | 3.14 | yes | bet_analysis | 2026-11-15 (date) | 2 |

No `as_of_in_future`. No user-seen timeout, no transport error.

**Web (30 min):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 8 (6 hard), max anon 1253 MB vs 642.9 MB limit.
- Overlay warms: 32, median 26.43 s, 24 over 20 s, 4 over 45 s, 1 over 60 s, max 82.0 s.
- Over 20 s: 11 (`POST /api/intelligence/query` 5, `GET /api/board/game-chips` 3, `POST /api/syndicate/query` 2, `GET /` 1). Over 45 s: 1 (`POST /api/intelligence/query`).
- Asks from any client: 6, 0 over 45 s, 0 non-200; 0 not this probe's (all `Python-urllib/3.12`).

**Host:** load 10.78 / 10.63 / 9.67 on 12 cores; MemAvailable 6241 MB. Top CPU: build_soccer_artifacts (bundesliga) 94% ni 0; refresh-worker 91% ni 0 (4.2 GB RSS); refresh_odds_sources x2 89% / 62% ni 0; live-odds-worker 64% ni 0; momentum_lag_study 55% ni 19; gunicorn web 50% ni 0 (up 192 s).

**Engine:**
- 2a F2: 1 run total (16:30-17:17Z, "did NOT PASS"), the one already on main `c765eec64`; no newer run.
- 2b `engine-learner-m2-gate-read-1124`: enabled, fireAt 2026-11-24T16:30:00Z.
- 2c `m2_gate.py` sha256 `c1a2c029c2a1816f...`: matches Amendment 2.
- 2d engine-file commits on origin/main in the last 40 min: none.
- 2e deploys.md headers since 6:57 PM CST: 01:08Z render_env/ deletion (no deploy), 01:08Z `923869cf3` deploy attempt ABORTED nothing loaded, 01:16Z operator ledger write (no deploy). No fleet load.

- **ANOMALY:** an overlay warm took 82.0 s (1 of 32 over 60 s; 4 over 45 s). Check next: the web log's overlay-warm lines 01:05-01:37Z for which sport/date, and whether it coincided with a hard recycle (6 hard of 8) or the soccer build + two odds refreshes at load ~10.7 on 12 cores.

## Reading 20 (8:05 PM CST)

Probe 8:05-8:06 PM CST (02:05:29Z). Web window from 7:35 PM CST (01:35Z), 261 requests.

**Ask:** 6 / 6 answered, 0 past the 45 s cut-off, median 11.61 s, max 16.45 s. A game was live (a `live_row` ask exists: Southern Miss Golden Eagles, NCAAB).

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text (spread) | 11.28 | yes | bet_analysis | 2026-11-17T23:13:09Z | 0 |
| free_text (Lakers vs Celtics) | 0.93 | yes | matchup_analysis | 2026-11-17T23:13:09Z | 0 |
| free_text (top edges) | 11.61 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NCAAF WKU) | 16.45 | yes | bet_analysis | 2026-11-14 (date) | 3 |
| pregame_prop (NBA Wagler) | 14.62 | yes | bet_analysis | 2026-11-18T00:33:24Z | 7 |
| live_row (NCAAB) | 8.34 | yes | bet_analysis | 2026-11-18T01:30:49Z | 0 |

No `as_of_in_future`. No user-seen timeout, no transport error. Page 200 in 0.18 s; shortlist 200 rows in 5.58 s.

**Web (30 min):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 21 (17 hard), max anon 1082 MB vs 646.1 MB limit (Reading 19: 8, 6 hard). One gunicorn worker was 15 s old at the host read.
- Overlay warms: 27, median 25.0 s, 18 over 20 s, 2 over 45 s, 2 over 60 s, max 82.0 s.
- Over 20 s: 8 (`POST /api/intelligence/query` 4, `GET /api/board/game-chips` 2, `POST /api/syndicate/query` 2). Over 45 s: 0.
- Asks from any client: 12, 0 over 45 s, 0 non-200; 0 not this probe's (all `Python-urllib/3.12`; 6 are Reading 19's probe at 01:35Z).

**Host:** load 8.65 / 7.47 / 7.62 on 12 cores; MemAvailable 6767 MB. Top CPU: gunicorn web 108% ni 0 (15 s old) and 62% ni 0; refresh-worker 92% ni 0 (3.9 GB RSS); live-odds-worker 69% ni 0; m2gate_kit `launch.py learner run` 51% ni 19 (not this probe's); live_resim_workers x2 47% ni 5; out790_chips_prof 18% ni 19.

**Engine:**
- 2a F2: 1 run total (16:30-17:17Z, "did NOT PASS"), the one already on main `c765eec64`; no newer run.
- 2b `engine-learner-m2-gate-read-1124`: enabled, fireAt 2026-11-24T16:30:00Z.
- 2c `m2_gate.py` sha256 `c1a2c029c2a1816f...`: matches Amendment 2.
- 2d engine-file commits on origin/main in the last 40 min: none.
- 2e deploys.md headers since 7:27 PM CST: 01:46:27Z (7:46 PM CST) web load of `3920a2d4d`, the loop-stall black box (lane `web-silent-worker-kills`). A fleet load; web instrumentation, not live pricing.

- **ANOMALY:** 2 overlay warms over 60 s (max 82.0 s, 2 of 27). Check next: the web log's overlay-warm lines 01:35-02:06Z for sport/date, and whether they sit beside the hard recycles.
- **ANOMALY:** new fleet load at 7:46 PM CST: web `3920a2d4d` (loop-stall black box). Check next: its deploys.md `verify:` reading, and whether the recycle jump (8 -> 21, 17 hard) follows the reload or predates it.

## Reading 21 (8:35 PM CST)

Probe 8:35:24-8:36:14 PM CST (02:35Z-02:36Z 11-18); web window 8:05-8:36 PM CST.

**Ask:** 6 / 6 answered, 0 past the 45 s cut-off, 0 user-saw-timeout; median 10.12 s, max 14.98 s (pregame_prop). Page 200 in 0.19 s; shortlist 200 in 1.16 s (200 rows).

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "this spread?" | 10.12 | ok | bet_analysis | 2026-11-18T01:30:49Z (7:30 PM CST, 65 min) | 0 |
| free_text "Lakers vs Celtics" | 0.52 | ok | matchup_analysis | 2026-11-18T01:30:49Z | 0 |
| free_text "top edges today" | 7.62 | ok | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line NCAAF WKU +16.5 | 11.76 | ok | bet_analysis | 2026-11-14 (date) | 3 |
| pregame_prop NBA Wagler o12.5 pts | 14.98 | ok | bet_analysis | 2026-11-18T00:33:24Z (6:33 PM CST, 123 min) | 7 |
| live_row NBA Knicks h2 h2h | 1.76 | ok | bet_analysis | 2026-11-18T01:30:49Z | 0 |

All `answer_source=snapshot`; `as_of_in_future` false on 6 / 6. A game was live: a `live_row` ask exists (Knicks @ Raptors, h2).

**Web (8:05-8:36 PM CST, 265 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 19 (17 hard); max anon 1069.7 MB vs 644.6 MB limit.
- Overlay warms: 35; median 19.42 s; 17 over 20 s; 2 over 45 s; 0 over 60 s; max 57.52 s.
- Requests over 20 s: 8 (POST /api/intelligence/query 6, GET /api/board/game-chips 2); over 45 s: 0.
- Asks from any client: 12, 0 over 45 s, 0 non-200; 0 of 12 not this probe's (all `Python-urllib`; 6 are the 8:05 PM reading's, 6 this one's).

**Host:** load 7.27 / 6.80 / 7.08 on 12 cores; MemAvailable 6,618 MB. Top CPU: refresh-worker 92.9% (ni 0, 4.5 GB RSS), gunicorn web worker 87.9% (ni 0, 35 s old), live-odds-worker 72.7% (ni 0), two live_resim_workers 47.2% each (ni 5), second gunicorn worker 25.9% (ni 0, 109 s old). The probe's own `ps` (ni 19) is excluded.

**Engine:**
- 2a F2: 1 run total (10:30-11:17 AM CST, "did NOT PASS"), already recorded at `c765eec64`; no newer run.
- 2b M2: `engine-learner-m2-gate-read-1124` enabled, fireAt 2026-11-24T16:30:00Z.
- 2c gate hash `c1a2c029c2a1816f...`: matches Amendment 2.
- 2d engine-file commits on origin/main in the last 40 min: none.
- 2e deploys.md: no header in the last 40 min (since 7:56 PM CST). Newest is the 7:46 PM CST web loop-stall black box `3920a2d4d` (`web-silent-worker-kills`), 50 min ago, so outside this window. The two recent gunicorn worker ages (35 s, 109 s) are recycles, not a load.

No anomaly.

## Reading 22 (9:06 PM CST)

Probe `ask_reading_20261118T030512Z.json`, run 9:05 PM CST. The web window starts 8:35 PM CST (02:35Z).

**Ask:** 6 of 6 answered. 0 of 6 went past the 45 s cut-off. Median 6.51 s, max 8.15 s. The page answered 200 in 0.07 s. The shortlist answered 200 in 0.86 s with 200 rows.

| kind | s | ok | schema | as_of | tables |
|---|---|---|---|---|---|
| free_text "this spread" | 7.92 | yes | bet_analysis | 02:01:14Z (3846 s old) | 0 |
| free_text "Lakers vs Celtics" | 0.71 | yes | matchup_analysis | 02:01:14Z (3847 s old) | 0 |
| free_text "top edges today" | 6.51 | yes | market_summary | 2026-11-17 (date) | 1 |
| pregame_game_line (NBA UTA@LAC Over 54.5, q2) | 8.15 | yes | bet_analysis | 2026-11-15 (date) | 2 |
| pregame_prop (Wagler Over 12.5) | 3.31 | yes | bet_analysis | 00:33:24Z (9135 s old) | 7 |
| live_row (NBA POR@MIN h2h) | 1.21 | yes | bet_analysis | 2026-11-16 (date) | 2 |

No `as_of` is in the future. A game was live: the probe found a `live_row` ask. Every answer came from the snapshot path.

**Web over the window (244 requests):**
- WORKER TIMEOUT kills: 0.
- Memory recycles: 20, of which 17 were hard. Max anon 1152.2 MB against a 648.9 MB limit.
- Overlay warms: 44. Median 16.87 s. Over 20 s: 18. Over 45 s: 3. Over 60 s: 1. Max 68.32 s.
- Requests over 20 s: `POST /api/intelligence/query` 4, `GET /api/board/live-rail` 1.
- Requests over 45 s: `GET /api/board/live-rail` 1.
- Asks from any client: 12 (6 from the previous reading, 6 from this one). 0 over 45 s, 0 non-200. All 12 are `Python-urllib`, so 0 came from another client.

**Host:**
- Load 5.49 / 4.89 / 5.39 on 12 cores. MemAvailable 6423 MB.
- Top CPU:
  - refresh-worker 93.9% (nice 0, 4634 MB RSS);
  - live-odds-worker 73.9% (nice 0);
  - gunicorn web workers 57.2% and 30.7% (nice 0; one was 54 s old, the other 190 s old);
  - two live_resim workers at 45.5% each (nice 5);
  - this probe 3.3% (nice 19).

**Engine:**
- 2a: `engine-live-prior-f2-read-1117` still has 1 run (16:30-17:17Z, NOT PASSED, already recorded at `c765eec64`). No newer run.
- 2b: `engine-learner-m2-gate-read-1124` is enabled, fireAt 2026-11-24T16:30:00Z.
- 2c: The `m2_gate.py` sha256 starts `c1a2c029c2a1816f`, which matches Amendment 2.
- 2d: No engine-file commits on origin/main in the last 40 min.
- 2e: The newest deploys.md header is 02:46:25Z (8:46 PM CST), "OPS, NO DEPLOY": a hung `refresh_nhl_oddsapi.py` child was killed. That is a process kill, not a code or env load, so live pricing is unchanged. There is no FLEET ff, DEPLOY or role restart in the last 40 min.

- **ANOMALY:** One overlay warm took 68.32 s, over the 60 s line. Three of 44 warms went past 45 s, and 1 `GET /api/board/live-rail` request went past 45 s. Next: check the web log for the warm's timestamp and whether it lines up with the 8:46 PM NHL odds child kill or with a hard recycle. 17 of 20 recycles were hard, and max anon was 1152 MB against a 649 MB limit.

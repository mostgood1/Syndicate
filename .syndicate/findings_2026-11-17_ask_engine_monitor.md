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

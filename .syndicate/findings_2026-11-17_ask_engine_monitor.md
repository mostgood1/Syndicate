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

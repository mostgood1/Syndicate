# Which requests carry web workers over the recycle limit — 2026-11-28

Lane `web-recycle-routes` (session 9ef6a9cf), todo `#867` (a). READ-ONLY on the fleet: every read ran at nice 19
(web.log, `/proc`, `ss`), plus Windows `Get-ScheduledTask` reads. Nothing was loaded or changed.

**Answer: the Layer 2 board query.** A web worker that serves its first combined-board call
(`/api/intelligence/query`, or the `/intelligence` page) installs the full board and is recycled a median 85 s
later.
- **What it costs:** the first install adds +339 to +468 MB of peak to a ~96 MB worker and settles at +290 to
  +438 MB. The board's own overlay warmer then rebuilds it 25-87 s later, holding two copies. That adds +191 to
  +325 MB more, and in 6 of 7 sampled cases it is what took the worker over its ~620-650 MB limit.
- **The count:** recycles an hour track board polls that land on a fresh worker almost one for one, whenever live
  overlays are moving.
- **At night they are not.** With no overlay rebuilds, the same board polls every 15 min cost 0-1 recycles an hour.
- The callers are an open board page (desktop Chrome and the iPad, one poll every 60 s each) and two scheduled
  tasks: `SyndicateCheatSheetPicks` (every 15 min) and `SyndicateRailWatch` (every 20 min, 10:03 AM-2:03 AM CST).
- Every other route together accounts for 2-8% of recycles.
- The NCAAF cards route was the main other cause until `4bfaa108a` (todo #867).
- The remedy is already decided and unblocked: #857's 1,500 MB limit (section 5).

## Hypothesis (written before any attribution read, lane block 2026-11-28 ~9:55 AM CST)

- **H-BOARD:** the recycles are the Layer 2 board.
- **H-OTHER (rival):** other routes carry workers over the limit without a board.
- **Falsified if:** more than 20% of memory recycles come from workers that logged no board install, or the 1 Hz
  sampler shows limit crossings with no board request in flight.

**Verdict: H-BOARD is NOT falsified; H-OTHER is not supported.**
- **The log test:** 2% of recycles before the NCAAF fix and 8% after had no board install, both under the 20% bar.
- **The sampler:** 7 of 7 crossings were board workers, with no other route in flight. 3 of them had no request in
  flight at all: there, the board's own background warmer pushed the worker over. The test's wording did not foresee
  that (section 4).

## 1. Every recycle against its own worker's board installs (web.log 11-26 01:09Z .. 11-28 15:50Z)

Instrument `C:\tmp\ncc_9ef6\rr\recycle_join.py`.
- **Per pid:** the boot ("Booting worker with pid"), the `WEB_WORKER_MEMORY_RECYCLE` line, and the pid-stamped
  board lines (`COMBINED_BOARD_SHARED_BUILD` / `_ADOPTED` / `_SERVED_STALE` / `_PUBLISHED`,
  `COMBINED_BOARD_OVERLAY_WARMER_STARTED`).
- **Window:** web.log holds 1,269 worker lives and 1,238 memory recycles. The split is the NCAAF fix's load,
  06:01:23Z 11-28.

| | recycles | with a board install before the recycle | without |
|---|---|---|---|
| before the NCAAF fix (11-26 01:09Z .. 11-28 06:01Z) | 1,212 | **1,184 (98%)** | 28 |
| after it (.. 11-28 15:50Z) | 26 | **24 (92%)** | 2 |

- **Timing, before the fix:**
  - first board install to recycle: p10 38 s, **p50 85 s**, p90 119 s;
  - last board event to recycle: p50 9.5 s.
- **Anon at recycle:** p50 935 MB and p90 1,112 MB with a board, against a limit of 617-650.
- **How the guard fired:** the 5 s timer watch 1,170 of 1,212 times (965 of them over the hard margin), and after a
  request 42 times. A board worker is recycled as soon as it passes the guard's 120 s minimum age.
- **The 28 without a board, before the fix:**
  - 26 were 11-27 20:29Z .. 11-28 06:00Z, at 645-1,378 MB with 0-46 requests. The requests in flight were mostly
    the #859 NCAAF cards poller (`Python-urllib/3.12`, to ~04:12Z) and my deploy probe (05:50-06:00Z), plus other
    pages' card APIs (nba / nfl cards, props, picks).
  - 1 came in the 8:15 AM grader's past-date `game-chips` sweep (14:21Z 11-27).
  - 1 came amid mixed `Python-urllib/3.12` requests (`/api/syndicate/query`, `layer2-shortlist`, nhl cards; 15:31Z
    11-27).
- **The 2 without, after the fix:** 14:22Z and 14:26Z 11-28. Both fell in the 8:15 AM grader's past-date
  `/api/board/game-chips` sweep (35 requests in 13:50-14:27Z, mean 2.7 s), and both were timer recycles at
  680-707 MB.

## 2. Which request starts the board in a fresh worker

Instrument `C:\tmp\ncc_9ef6\rr\warmer_attrib.py`.
- **What it matches:** `COMBINED_BOARD_OVERLAY_WARMER_STARTED` marks a worker's first combined-board call. Each one
  is matched to the access-log requests in flight at that instant (start = the line's time minus `%(M)s`).
- **Counts:** 1,217 warmer starts and 1,239 recycles in the window.
  - 1,210 had a board route in flight;
  - 7 had only other routes in flight;
  - 0 had nothing in flight;
  - 70 had more than one candidate route or caller, and were split equally between them.

| route | caller | warmer starts (share-weighted) | share |
|---|---|---|---|
| `/api/intelligence/query` | desktop Chrome (the board page) | 622.5 | 51% |
| `/api/intelligence/query` | iPad Chrome (the board page) | 322.5 | 27% |
| `/api/intelligence/query` | `Python-urllib/3.11` (the two scheduled tasks, section 3) | 215.0 | 18% |
| `/intelligence` (page) | `Python-urllib/3.11` (`SyndicateRailWatch`) | 20.0 | 2% |
| `/api/intelligence/query` | `Python-urllib/3.12` (session probes) | 17.0 | 1% |
| `/api/intelligence/query` | Claude app browser | 8.5 | 1% |
| everything else | | 11.5 | 1% |

**Per UTC hour, the recycles follow the open board pages:**

| hours | board polls an hour (Chrome / iPad / 3.11) | warmer starts | recycles |
|---|---|---|---|
| 11-26 18Z-11-27 01Z (both browsers open) | 54-68 / 37-60 / 7 | 48-56 | 49-57 |
| 11-27 04Z (iPad only) | 0 / 60 / 7 | 50 | 46 |
| 11-27 17Z (desktop only) | 77 / 0 / 7 | 50 | 49 |
| 11-28 00-03Z (desktop, intermittent) | 12-36 / 0 / 7 | 16-30 | 24-32 |
| 11-28 05Z (iPad) | 0 / 19 / 7 | 21 | 22 |
| 07-15Z any day (no browser) | 0 / 0 / 4-5 | 0-6 | 0-8 |

- **One open board page saturates it.** The page polls `/api/intelligence/query` every 60 s (gap p10 / p50 / p90:
  desktop 37 / 60 / 63 s over 1,079 polls, iPad 58 / 60 / 62 s over 798). The poll lands
  on a worker that does not hold the board (the other was just recycled) and installs it; ~85 s later the guard
  recycles that worker.
- **The ceiling:** with 2 workers and a 120 s minimum age it is ~60 an hour, and the open-browser hours run at
  46-57.
- **#853's shared copy changed the cost, not the count.** A fresh worker adopts another worker's copy in ~0.3-0.8 s
  instead of building it, but the copy still lands in its own heap.

## 3. The two scheduled callers (`Python-urllib/3.11`)

`Python-urllib/3.11` is the fleet venv (Python 3.11.16) or Windows Python 3.11; WSL's system `python3` is 3.12. Split by
tick minute (`C:\tmp\ncc_9ef6\rr\split311.py`), the 3.11 board-route warmer starts are:

| task | cadence | what it asks | warmer starts |
|---|---|---|---|
| **`SyndicateCheatSheetPicks`** | every 15 min at :07 / :22 / :37 / :52, day and night | POST `/api/intelligence/query`, the board page's own query (`scripts/build_cheat_sheets.py:725`) | 164 |
| **`SyndicateRailWatch`** | every 20 min, 10:03 AM-2:03 AM CST | `GET /intelligence` (23 s, 6.3 MB), then POST `/api/intelligence/query` (13.3 s, 11.5 MB) | 67 (53 query + 14 page) |
| other | :00, :06, :30 | | 9 |

- **`SyndicateCheatSheetPicks`:**
  - action: `wsl ... ~/.venvs/syndicate/bin/python scripts/build_cheat_sheets.py --picks-only`; trigger start
    2026-10-16 14:37 CST, `PT15M`;
  - **caught 16:07:04Z:** `ss -tnp` on the fleet showed pid 1904564 `build_cheat_sheets.py ... --picks-only` holding
    the connection to :10000. At the same tick a Windows-side `Get-NetTCPConnection` catch saw no Windows process;
  - its responses ran 3.9-5.8 MB in 1.6-17.2 s (07:07Z..15:52Z 11-28);
  - **at night it costs no recycle.** In 08-12Z it rebuilds the board 4 times an hour in the same long-lived worker,
    and the overlay warmer rebuilds nothing (0 warmer builds, 0 `OVERLAY_WARMED ... rebuilt=True`). Web recycles
    0-1 an hour then (11-27 and 11-28), with boards of 6,100-6,300 rows, the daytime size;
  - once live overlays move (from ~14-16Z, 8-10 AM CST), each of its polls that meets a fresh worker costs a
    recycle.
- **`SyndicateRailWatch`** (`pythonw C:\tmp\railmon\railwatch\tick.py`):
  - **seen in the sampler at 10:03 AM CST:** its `/intelligence` page built the board in worker 1899126
    (16:03:23Z). Its board query then landed on worker 1898605, which installed the shared copy (16:03:57Z).
  - Both workers crossed their limits by 16:04:08Z and were recycled at 16:04:26Z and 16:05:07Z: one tick, two
    recycles.

## 4. The 1 Hz sampler: what each request adds

**Instrument.** `C:\tmp\ncc_9ef6\rr\sampler.py` read each web worker's `RssAnon`, `VmHWM` and CPU ticks from `/proc`
once a second: 15:56:24-16:41:24Z 11-28 (9:56-10:41 AM CST), 2,686 ticks, nice 19, read-only.
`sampler_join.py` joins the ticks to web.log.

**The window:** a quiet Saturday morning. There were 43 requests, and the board was smaller than on an evening
(#857's evening plateau is ~1 GB). Read the numbers below as the morning's.

**Every recycle in the window was a board worker: 7 limit crossings, 7 recycles.** Each worker logged three board
lines (warmer start, first install, the warmer's rebuild) before crossing. Each was recycled 50-119 s after its
first install.

| first install (UTC) | caller | anon before -> first-install peak / settled | warmer rebuild start -> peak | crossed (limit) | recycled |
|---|---|---|---|---|---|
| 16:03:23 | `SyndicateRailWatch` (`/intelligence`) | 96 -> 546 (+450) / 392 (+296) | 16:03:51 -> 717 (+325) | 16:04:08 (635), 17 s after the rebuild | 16:04:26 |
| 16:03:57 | `SyndicateRailWatch` (query; adopted the copy above) | 201 -> 643 (+442) / 491 (+290) | 16:04:31 -> 780 (+289) | **16:04:06 (625), during the first install** | 16:05:07 (hard) |
| 16:07:04 | `SyndicateCheatSheetPicks` | 96 -> 461 (+365) / 458 (+362) | 16:07:49 -> 650 (+192) | 16:08:14 (627), 25 s after | 16:08:15 |
| 16:17:46 | desktop Chrome (board page opened) | 103 -> 571 (+468) / 540 (+438) | 16:18:27 -> 731 (+191) | 16:18:35 (621), 8 s after | 16:18:39 |
| 16:20:42 | `Python-urllib/3.12` (a session's probe) | 96 -> 458 (+362) / 458 (+362) | 16:21:12 -> 670 (+211) | 16:21:27 (630), 15 s after | 16:21:51 |
| 16:22:02 | `SyndicateCheatSheetPicks` | 96 -> 496 (+400) / 418 (+322) | 16:23:29 -> 680 (+262) | 16:23:41 (645), 12 s after | 16:24:01 |
| 16:37:02 | `SyndicateCheatSheetPicks` | 122 -> 461 (+339) / 461 (+339) | 16:37:27 -> 713 (+252) | 16:37:36 (642), 9 s after | 16:37:52 |

The "settled" figure is the worker's anon when its warmer's rebuild started. The rebuild's figure in brackets is
its peak over that settled level.

- **The first install.** It adds +339 to +468 MB of peak anon to a ~96 MB fresh worker. That settles at +290 to
  +438 MB, so the worker holds 392-540 MB. In 1 of 7 the first install alone crossed the limit: worker 1898605,
  643 MB, while serving the rail watch's 11.5 MB query response.
- **The board's own overlay warmer** (interval 5 s, window 600 s, started by that first call):
  - 25-87 s later it rebuilds the expired board in a background thread, holding the old and the new board at once;
  - that adds +191 to +325 MB of peak over the settled level, to 650-780 MB;
  - in 6 of 7 this rebuild is what crossed the limit, 8-25 s after it started.

**Other routes**, on solitary requests (no other request within 1 s either side): the change in the serving worker's
anon, where the serving worker is the one whose CPU rose.

| route | caller | n | after - before p50 (max) | peak - before max |
|---|---|---|---|---|
| `/api/intelligence/query` | 3.11 / 3.12 | 4 | +342 (+362) | +365 |
| `/api/board/live-rail` | 3.11 | 5 | +33 (+142) | +142 |
| `/api/portfolio/live` | 3.12 | 1 | +27 | +27 |
| `/cheatsheets` | curl | 2 | +16 (+22) | +22 |
| `/api/ops/version` | 3.11 | 1 | 0 | 0 |

- n is small. The morning had no game-chips sweep, NCAAF poller or open card pages to measure.

**The sampler's falsification test, read as worded.** The test: limit crossings with no board request in flight.
- **3 of the 7 crossings had no request of any kind in flight:** 16:08:14, 16:21:27 and 16:37:36Z.
- **Each came 9-25 s after that worker's warmer rebuild started** (16:07:49, 16:21:12, 16:37:27Z, all
  `own=expired warm=1`). That is board work in a background thread, which the test's wording did not foresee.
- **No other route was in flight at any of the 7.** H-OTHER needs one, so it gets no support.
- **The night contrast agrees.** The same board queries with no warmer rebuilds (08-12Z: 4 request builds an hour,
  0 warmer builds) recycled 0-1 workers an hour (section 3).
- **How this is recorded:** the crossings are the board's, through its warmer, and the falsification test missed
  the warmer. This is said here so it is not read as a clean pass.

## 5. What to do about it

**Nothing new is needed: the remedy is #857's, already decided and unblocked.**
- **The decision.** `WEB__SYNDICATE_WEB_WORKER_ANON_LIMIT_MB=1500` (env only; absent = today). The user said
  "Yes, after #853" on 11-20 (lane `web-recycle-anon-limit`, findings `findings_2026-11-20_web_recycle_anon_limit.md`).
- **Unblocked since #853's first-evening reading** (deploys.md, the #853 READING: "#857 ... is unblocked for the
  next drained full down/up").
- **Still not loaded.** Today's `WEB_MEMORY_GUARD_ARMED` lines read 631-647 MB, and no drained full down/up has
  happened since. Its deadline is the 12-08 window's down/up.
- **This finding agrees with #857's model.** #857 found a board-holding worker plateaus near ~1 GB, and here 98% of
  recycles are board-holding workers recycled ~85 s after their first board call. At 1,500 MB #857 predicts <= 2
  recycles an hour (pre-registered P1, falsified above 4), against 46-57 an hour with a board page open.
- **Its cost:** +1.0-1.2 GB of fleet RSS at p50, at every hour.

- **It covers the other routes too.** The past-date `game-chips` sweep (680-707 MB at recycle) and the NCAAF cards'
  old first-build peak (1,193 MB, gone since `4bfaa108a`) both sit under 1,500.

**Nothing to change at the callers.**
- The board page's 60 s poll is the product: the user watches the board.
- `SyndicateCheatSheetPicks` asks the board page's own query on purpose, so a promoted pick is what the board shows
  (`build_cheat_sheets.py` `fetch_board_cards` docstring).
- `SyndicateRailWatch` reads the board to grade it.
- Thinning any of them would cut recycles only while the 650 MB limit stands.

**Leads (not followed):**
- **The warmer's rebuild holds two boards at once** (+191 to +325 MB of peak over the settled level). In 6 of 7
  sampled crossings it was the step over the limit. Dropping the old board before the rebuild, or rebuilding the
  overlay in place, would lower every board worker's peak, whatever the limit.
- **A fresh worker still copies the whole board into its own heap**, even when it adopts another worker's copy
  (#853). A board held once per host would remove the +290-440 MB a worker settles at, and more on an evening board.
  That could be a read-only mmap of the shared copy, or one process serving the board.
- Both leads are code in `pipeline/intelligence_state.py` and `combined_board_shared_copy.py`; a separate lane.
- #857's own lead, an idle eviction of the board cache, would remove the night cost of the higher limit.

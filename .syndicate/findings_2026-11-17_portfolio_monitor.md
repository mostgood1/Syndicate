# Portfolio endpoint — standing monitor, 2026-11-17 (lane `portfolio-monitor`)

Day 1. The user asked on 11-17 ~10:00 AM CST: "similar to the layer 2 game rail monitoring, this session should be
actively monitoring, diagnosing, optimizing, and improving the portfolio endpoint".

Times are Central (CST) unless marked Z. Money stays out of this file (the repo is public): counts, rates and
percentages of caps only. Raw payloads and the JSON readings stay in `C:\tmp\pfmon\readings` (outside the repo).

## How a reading is taken

- `scripts/portfolio_monitor_probe.py` (fleet only, loopback refused otherwise; IDLE priority; log reads at nice 19).
  One run is one reading, appended to `C:\tmp\pfmon\readings\readings.jsonl`. Plain GETs only.
- **Endpoints read, each against a latency budget** (about 3x the first reading): `/api/portfolio/live` (3 s),
  `/api/portfolio/live?on=all&show=all` (5 s), `/api/portfolio/plan` (6 s), `/limits`, `/settings`, `/books` (2 s),
  and the `/portfolio` page (3 s).
- **Never read:** `/api/portfolio/summary` and `/api/portfolio/paper`. One GET of `/paper` cost the fleet a web
  worker this morning (below). Those two are watched only through the web access log.
- **From the logs, over the window:**
  - web: every caller's requests to `/portfolio*` (n, statuses, p50/p95/max ms, browser vs script) and gunicorn
    `WORKER TIMEOUT` kills;
  - workers: live-mode `[execute_portfolio] EXECUTED` ticks per venue (placed / filled / failed / refused by
    reason), the newest `[portfolio_commit] LIVE_PLAN_WRITTEN` per venue, and `UNRECONCILABLE_ORDER` keys.
- **From the payloads:**
  - the banner's own verdict and fields, the kill switch, and the worker state age against the page's 900 s;
  - the plan funnel (board rows -> suggested -> rows_in -> sized -> positions) with refusals by reason;
  - today's live orders by status, resting age, and late settlement (filled, started more than 8 h ago,
    no outcome);
  - day-cap use per venue;
  - ledger flags (unknown submits, unreconciled, grade conflicts);
  - the scale-up gate on the betting-change clock (`live_book_edge_readout`).
- An ANOMALY line is printed for each threshold crossed. Thresholds: an endpoint not 200 or over budget; any
  worker timeout; any 5xx; banner not ok; kill switch engaged; state or balances older than 900 s; plan older than
  45 min; CLV join match rate below 1; any unknown submit, grade conflict or unreconciled row; any failed or
  rejected order today; a resting order older than 120 min; a late settlement; a cap at 90% or more; a failed or
  unarmed live tick; the gate clock pending or unclassified.
- 10 tests: `tests/test_portfolio_monitor_probe.py`.

## Survey before the first reading — Tue 11-17 ~10:10 AM CST (16:10Z)

One pass over every portfolio route, before any probe existed:

| route | status | time | size |
|---|---|---|---|
| `/api/portfolio/settings` | 200 | 0.12 s | 0.5 KB |
| `/api/portfolio/limits` | 200 | 0.31 s | 0.9 KB |
| `/api/portfolio/plan` | 200 | 1.80 s | 469 KB |
| `/api/portfolio/live` | 200 | 0.62 s | 91 KB |
| `/api/portfolio/live?on=all&show=all` | 200 | 0.66 s | 4,184 KB (2,268 orders) |
| `/api/portfolio/books` | 200 | 0.02 s | 0.3 KB |
| `/portfolio` | 200 | 0.67 s | 94 KB |
| **`/api/portfolio/summary`** | **connection reset** | | |
| **`/api/portfolio/paper`** | **no response (~177 s); its web worker SIGKILLed** | | |

## FINDING 1 — `/api/portfolio/paper` does ~12–24 s of CPU and ~625 MB in the request path; at today's size a GET can cost a web worker

- **Measured cost, today (2026-11-17):**
  - My survey's single GET of `/api/portfolio/paper` began ~16:10:26Z. The client got no response.
  - At 16:13:23Z gunicorn logged `WORKER TIMEOUT (pid:3996790)` and SIGKILLed that worker, about 177 s after the
    request began. Every other request in flight on its 4 threads died with it.
  - The web runs 2 workers × 4 threads with `--timeout 60`, so this killed half its workers.
  - This was my request. I do not repeat it; the monitor never reads this route.
- **Where the time goes:** profiled outside the web, with the web worker's env, at nice 19 (read-only; the env was
  never printed).
  - `_paper_portfolio_payload('2026-11-17')` took **24.2 s** (cProfile on), peaked at **772 MB RSS**, and
    returned **2.4 MB**.
  - `settlement_summary` ran twice for 13.6 s (`_grouped` / `_market_family` / `canonical_market_key` over
    67,839 rows).
  - `_with_archive` / `archived_orders` ran twice for 8.3 s. That is the disk archive: `orders_2026-10.jsonl`
    50 MB (30,098 lines) plus `orders_2026-11.jsonl` 70 MB (39,566 lines), 51,075 rows after dedup.
  - `ledger_summary(date)` took 4.0 s.
  - Without the profiler, the archive read alone is 2.0 s at **625 MB peak RSS**, and settlement over all paper
    rows is 0.7 s.
- **Why it was fine before:** the access log has 30 successful paper GETs at 0.8–12.7 s (11-03, ~2 h of the page
  polling every 5 min) and one at 1.6 s on 11-10. The November shard has grown since: the paper ladder alone
  wrote 196 orders in one 16:16Z tick today.
- **Rule broken:** CLAUDE.md, "The web service does no heavy computation." The builder's docstring calls itself a
  "PURE READ", and of the plan it is. But it also re-reads the whole two-month archive and re-settles all of it
  on every request.
- **Who calls it:** only `/portfolio/paper` (`paper_portfolio_pulse.js`, which polls) and three manual scripts
  (`measure_game_market_option_value.py`, plus the `/summary` readers `verify_recent_shipped_work.py` and
  `ask_syndicate_regression.py`). No scheduled job calls it. So the cost lands when someone opens the paper page.
- **The worker-kill mechanism, measured over every WORKER TIMEOUT in web.log (10-31..11-17, n = 8):**
  - 5 of 8 match one pattern (11-01, 11-06 ×2, 11-08, 11-11). `WEB_WORKER_MEMORY_RECYCLE` fires
    (`hard: true`, anon 780–893 MB against a ~630 MB limit, or one soft at 641 MB). Then `WEB_WORKER_DRAINED`
    shows `still_in_flight: 1`. About 66 s later comes the TIMEOUT.
  - The mechanism: `DrainingThreadWorker.run` drains for 5 s, then `futures.wait(..., graceful_timeout=30)`
    without a heartbeat. Interpreter exit then joins the thread pool, which blocks on the still-running request.
    The arbiter sees no heartbeat for 60 s and kills the worker.
  - 10-31: drained with nothing in flight, and was still killed 60 s later.
  - **Today's two (15:23:37Z pid 4012882, 16:13:23Z pid 3996790) have NO recycle or drain line.** Those workers
    went silent while alive. The 16:13 kill coincides with my paper GET. The 15:23 kill is **unattributed**: a
    killed request leaves no access line, and no scheduled caller exists.
  - **OPEN:** how a worker stops heart-beating while alive and serving a long request. Not tested.
- **What a fix looks like (not started; needs its own lane):** the all-time paper settlement and the per-date
  ledger summary become worker-written artifacts, and web reads them. The date view reads only that month's
  shard plus the live document. The drain path's join-on-exit is a separate defect: any long request in flight
  at a memory recycle costs the worker.

## Reading 1 — Tue 11-17 10:21 AM CST (16:21Z), window 60 min

- **Endpoints:** all 7 read 200, inside budget.
  - `live` 0.80 s; `live?on=all` 3.20 s; `plan` 0.03 s; `/portfolio` 0.25 s.
- **Web log:** 2 WORKER TIMEOUTs in the window, 15:23Z and 16:13Z (FINDING 1). 0 of 17 portfolio requests
  answered 5xx. 0 came from a browser: no one had the page open.
- **Banner:** ok. All six fields true; the kill switch is clear; worker state 85 s old (limit 900); mode live,
  armed.
- **Plan (8 min old):**
  - Funnel: board 4,786 -> suggested 42 -> rows_in 42 -> sized 25 -> positions 16.
  - Refusals (26 of 42 rows): beyond_max_positions 13, below_min_stake 9, zero_kelly 2,
    below_min_ev_after_fair_noise 1, no_model_edge 1.
  - CLV join 16 of 16. Sim edge on 29 of 42 rows (69%). The sim picked the side on 0 of 16 positions.
  - Staked share of the slate ceiling: 22.9%.
- **Live plans per venue (16:14Z):**
  - kalshi: rows_in 860 -> placeable 23 -> positions 4; 801 of 860 (93%) refused `below_live_net_floor`.
  - polymarket: 428 -> 9 -> 5; 261 of 428 (61%) below the net floor, and 158 `aggregator_priced`.
  - novig 262 and prophetx 245: all `aggregator_priced`.
- **Execution:**
  - kalshi: 11 live ticks, 1 placed, 0 failed. Refusals: 25 `outside_price_band`,
    11 `already_held_other_slate`, 2 `game_started`.
  - polymarket: 10 live ticks, 0 placed. Refusals: 39 `outside_price_band`.
- **Orders today:** 25 (24 filled, 1 resting); 0 failed or rejected. Cap use: kalshi 12.5% of day dollars
  (4.4% of day orders); polymarket 10.6% (5.6%).
- **Gate:** clock BC-022 (2026-11-17T15:47:46Z), 0 of 800 events.
- **ANOMALIES (4):**
  1. Web worker timeouts 2 (FINDING 1).
  2. **Unreconciled live order** `f8b62e6a` (kalshi, slate 11-13).
     - The ledger says `status=submitted`, `outcome=lost`; the venue graded it lost.
     - `grade_check.reason=side_not_a_team_in_this_game`, `held_side=no`, `reconciled_at` empty.
     - Every reconcile pass logs `UNRECONCILABLE_ORDER ... reason=outcome_already_set blocks_live=False`.
     - Standing since 11-14; it does not block live. **Owner: not found yet.**
  3. **Resting maker-pilot order:** kalshi, submitted 06:12Z, 609 min old (`execution_style=maker_pilot`,
     11 contracts remaining). Its game is 11-18 00:00Z. The pilot rests by design, so this may be expected; the
     threshold is mine.
  4. **Late settlement:** 1 of 1 started-and-filled live bet is unsettled more than 8 h after its start (nhl,
     13.7 h).

## Reading 2 — Tue 11-17 10:29 AM CST (16:29Z), window 30 min

- **Endpoints:** all 200, inside budget. Web: 1 timeout in the window (16:13Z, mine), 0 5xx, 0 browser requests.
- **Banner:** ok, state 63 s old.
- **Plan:** 15.7 min old, the same plan. Gate: 0 of 800 since BC-022, a true zero (0 bets).
- **Execution, 30 min:** 9 live ticks, 0 placed. Refusals: 27 `outside_price_band`, 5 `already_held_other_slate`,
  2 `game_started`.
- **Anomalies:** the same 4. The resting order is now 617 min old; the late NHL bet is 13.8 h after its start.

## Reading 3 — Tue 11-17 10:34 AM CST (16:34Z), window 30 min — the loop starts

- **Endpoints:** all 7 read 200, inside budget. `live` took 1.48 s, the slowest of three readings (budget 3 s);
  `live?on=all` 2.28 s.
- **Web log:** 1 timeout in the window (16:13Z, mine). 0 5xx on 26 portfolio requests, 0 from a browser.
- **Plans rewritten 16:30Z:**
  - kalshi: 860 -> 22 placeable -> 5 positions (was 4).
  - polymarket: 437 -> 9 -> 6 (was 5).
  - The share below the live net floor is unchanged: kalshi 801 of 860 (93%), polymarket 268 of 437 (61%).
- **Execution, 30 min:** 8 live ticks, 0 placed, 0 failed. Refusals: 24 `outside_price_band`,
  4 `already_held_other_slate`, 1 `game_started`.
- **Unchanged:** the resting maker-pilot order (622 min old); the late NHL bet (13.9 h after its start);
  the unreconciled `f8b62e6a`.
- **NEW anomaly: 2 deploys.md loads unclassified in the betting-change register. Handed to their lanes.**
  - 16:17:31Z, NFL week-11 projection REBUILD on #808's profile (lane `nfl-profile-load`); no code, no restart.
  - 16:24:06Z, ff-only `17ff69398 -> c4d35b515`, #814's portfolio `key_player_out` refusal (lane
    `live-player-exit-gate`). By its own description this changes which live bets are placed, so it reads as a
    `yes` pending a refresh-worker load.
  - Effect now: none. The gate count is 0 of 800 either way (0 bets since BC-022). If neither lane classifies
    them by the next readings, I will raise it again.

## FINDING 1 — FIX BUILT (lane `paper-endpoint-request-path`; user "Yes, fix it", ~10:50 AM CST)

- **Change:**
  - `execution_ledger.ledger_for_date(date)` returns one date's orders (all modes) and its `ledger_summary`
    from ONE read. It takes the live document plus only that date's lines of its month shard (substring
    prefilter, then an exact `selected_date` check; last archived copy per identity; the document wins).
    Nothing enters `_ARCHIVE_PARSE_CACHE`.
  - The paper builder uses `ledger_for_date` and never calls `full_history_orders()`.
  - The all-dates paper record (`mode != live`, the same population) is written by the refresh-worker's
    settle pass (`paper_settlement.write_paper_all_time`, at most every 10 min, logged
    `[paper_settlement] PAPER_ALL_TIME_WRITTEN`) to `reports/intelligence/paper_settlement_all_time.json`
    (keyvalue). Web only reads it (`read_paper_all_time`). Before the worker's first write the line is
    absent (None), never zero.
  - The template shows "as of HH:MM UTC" on the all-dates line.
- **A/B on the fleet's data and the web worker's env, nice 19, read-only.** Old = the fleet's code at
  `8aea4fe7e`; new = this change. Both runs in separate processes.

  | date | paper orders | old s / peak MB | new s / peak MB | orders, keys, ledger summary, date settlement |
  |---|---|---|---|---|
  | 2026-11-17 | 813 | 13.12 / 769 | 9.79* / 105 | identical |
  | 2026-11-16 | 1,560 | 5.06 / 774 | 0.67 / 121 | identical |
  | 2026-10-20 | 275 | 10.97 / 1,052 | 0.52 / 137 | identical |

  \* The first call in a fresh process includes cold imports (portfolio_commit and the plan reads). A web
  worker has those warm, so 0.5–0.7 s is the representative cost. The old builder's first call carried the
  same imports and was still 5–13 s on every date.
- **Falsification test (written before the change):** >= 3 s warm, or >= 150 MB over baseline, or any
  difference in orders, keys or summary. **Not met on any of the 3 dates**, so the hypothesis stands.
- **Tests:** 8 new (`tests/test_paper_payload_request_path.py`). Three existing tests were moved onto the
  worker write: `test_the_all_dates_record_spans_every_slate`,
  `test_a_live_order_is_excluded_from_the_paper_all_dates_record` and
  `test_the_paper_page_shows_archived_rows_for_a_past_date_and_all_time`. Each isolates the reports root.
- **Not deployed.** A fleet ff to this commit also carries 50 commits since the fleet's head `8aea4fe7e`.
  Among them are `c70674e3b` (#823 NFL quarter/half lines every run, recorded at 16:26Z as not
  user-approved) and `3dbe53df0` (#824 college live totals refusal, a betting change of another lane).
  The deploy waits on the user.

## HYPOTHESIS F3 (written 11:25 AM CST, before any log is read for it)

- **Observation (reading 4):** 4 web worker kills today, 15:23:37Z, 16:13:23Z (mine), 16:38:10Z and 16:49:49Z.
  None was preceded by `WEB_WORKER_MEMORY_RECYCLE` / `WEB_WORKER_DRAINED` for its pid. Each of the 6 kills from
  10-31 to 11-11 was.
- **Hypothesis:** a single long request on the worker stops the gthread main loop's heartbeat for 60 s. The
  candidate is `/api/intelligence/query`: 44,950 ms, 11.5 MB at 16:08:42Z, and `board_read` alone 17.7 s.
- **Prediction:** in the 120 s before each silent kill, the web log shows the start-side lines of a long request
  (`QUERY_STAGE_MS` / `INTEL_TRACE` / a `compute in request path` burst) with no matching access line before the kill.
- **Falsified if:** before at least 2 of the 3 kills not caused by me, there is no such request, or there is
  only a stream of short requests.

## Reading 4 — Tue 11-17 11:22 AM CST (17:22Z), window 50 min

- **Endpoints:** all 7 read 200, inside budget.
  - `live` 2.20 s, the slowest yet against its 3 s budget (0.80 / 0.33 / 1.48 s at readings 1-3); `/portfolio` 1.20 s.
  - Web log: 0 5xx on 10 portfolio requests, 0 from a browser.
- **Plan:** 29.3 min old, written 16:53Z; earlier plans were about 15 min apart.
  - Funnel: board 4,818 -> suggested 39 -> sized 25 -> positions 16. Refusals: 11 beyond_max_positions,
    9 below_min_stake, 2 zero_kelly, 1 below_min_ev_after_fair_noise.
  - Live plans 16:54Z: kalshi 893 -> 24 placeable -> 5 (829 of 893, 93%, below the net floor);
    polymarket 428 -> 10 -> 7.
- **Execution, 50 min:** 12 live ticks, 1 placed (polymarket), 0 failed. Refusals: 52 `outside_price_band`,
  2 `already_held_other_slate`.
- **Orders today:** 26 (25 filled, 1 resting). Cap use: kalshi 12.5%, polymarket 11.3%.
- **Unchanged anomalies:**
  - the resting maker-pilot order (670 min);
  - the late NHL bet (14.7 h);
  - unreconciled `f8b62e6a`;
  - **2 loads still unclassified** in the betting-change register (16:17Z NFL rebuild, 16:24Z #814 ff). Their
    lanes have not classified them in the hour since.
- **NEW: 2 more web worker kills, 16:38:10Z (pid 4032063) and 16:49:49Z (pid 4035235).** Neither was mine.

### F3 tested — hypothesis FALSIFIED; cause still open

- **Base rate:** gunicorn WORKER TIMEOUTs per day were 0, 0, 0, 0, 0 on 11-12..11-16 (~1,550 worker boots).
  On 11-17 there are 4, all between 15:23:37Z and 16:49:49Z (16:13Z was my paper GET), and **0 in the
  ~35 min since**. All 4 are "silent while alive": none has a recycle or drain line for its pid.
- **Prediction tested:** a long request before each kill. In the 120 s before the 15:23, 16:38 and 16:49
  kills, the only requests are short:
  - `/wnba/api/live_player_boxscore`, 4.6–7.8 s, with its `compute in request path` ESPN fetches;
  - `/api/ops/version`, a 401 in under 0.7 s;
  - one browser `/syndicate` page load.
  - No `QUERY_STAGE_MS` or intelligence query is in any window. **Falsified.**
- **A correlation that does not discriminate:** the killed pid logged `COMBINED_BOARD_OVERLAY_WARMER_STARTED`
  67 s before the 16:38 kill and 74 s before the 16:49 kill. But a warmer starts on nearly every worker (192
  starts against 193 boots on 11-17; 154 / 154 on 11-16, with 0 kills). The 15:23 worker had started its
  warmer 31 min earlier.
- **Status:** cause unknown. Not actionable yet. The probe counts kills every reading; a recurrence opens a lane.
- **Lead:** what changed on web on 11-17 before 15:23Z. The fleet's ffs today were 15:25:07Z, 16:24Z and 16:27Z,
  all after the first kill, so their code is not a candidate for the 15:23 kill.

## Reading 5 — Tue 11-17 12:13 PM CST (18:13Z), window 52 min — and an instrument fix

- **INSTRUMENT FIX (probe, this reading):** both worker logs rotated inside the window.
  - `refresh-worker.log` began at 17:46:09Z and `live-odds-worker.log` at 17:56:08Z. Rotation is at 200 MB to
    `<name>.1`, by `local_production.rotate_running_log`.
  - The probe read only the live file, so the first take of this reading counted **3 live ticks per venue**
    instead of **8**.
  - The probe now reads the tail of `<name>.1` first, and the cutoff keeps only the window. The two truncated
    takes are set aside in `C:\tmp\pfmon\readings\superseded.jsonl`.
  - Readings 1-4 did not span a rotation: the previous ones were 11-16 ~17:38Z and ~11:00Z.
- **Endpoints:** all 7 read 200, the fastest of the day (`live` 0.31 s, `live?on=all` 0.34 s, `/portfolio` 0.28 s).
  - Web: **0 worker kills in the window**; the last was 16:49:49Z, now 84 min of none. 0 5xx; 0 browser requests.
- **Plan (2.7 min old):**
  - Funnel: board 4,539 -> **suggested 101** (39-42 earlier today) -> sized 25 -> **positions 11** (16 earlier).
  - Refusals: **beyond_max_positions 72**, below_min_stake 14, `in_play_market_fair` 2 (new reason today),
    zero_kelly 1, below_min_ev_after_fair_noise 1.
  - Sim edge on 85 of 101 rows (84%). Staked share of the ceiling 12.7% (23% earlier).
- **Live plans 18:11Z:**
  - kalshi: 937 -> 25 placeable -> 7 positions (871 of 937, 93%, below the net floor).
  - polymarket: 543 -> 18 -> 8 (413 of 543, 76%, below the net floor; 61% earlier).
- **Execution, 52 min:** 16 live ticks; 5 placed (kalshi 3, polymarket 2); 0 failed.
  83 refused `outside_price_band`.
- **Orders today:** 31 (30 filled, 1 resting). Cap use: kalshi 13.8%, polymarket 12.3%.
- **Worker state** was 304 s old at the first take (limit 900); 48-85 s earlier. Watching.
- **Anomalies (unchanged):** unreconciled `f8b62e6a`; the resting maker-pilot order (721 min); the late NHL bet
  (15.6 h); **2 unclassified loads, now ~2 h old.**
  - If they are still unclassified at the next reading, I will record the 16:24Z #814 refusal as `yes`,
    pending the refresh-worker load. That is fail-closed: the count holds at 0 until it loads. The 16:17Z NFL
    rebuild stays the owner's call.

## FINDING 1 — the fix's route to the fleet (12:2x PM CST)

- The fleet is now at `92ae7490a` (read ~18:2xZ), so `c70674e3b` (#823) and `3dbe53df0` (#824), the
  ride-alongs I was holding the deploy for, are already on the fleet.
- Lane `board-query-row-refs` (session "Layer 2 Game Rail monitor") has user approval to load
  `92ae7490a -> 5db26434e` tonight, not before ~5 PM CST: an exact-SHA ff plus reload-web. That range contains
  `2148f99cb`, and its session asked whether my fix is safe as a ride-along.
- **Answered (a), safe:** before refresh-worker loads the writer, web's `settlement_all_time` is None and the
  template prints no all-dates line, with no error and no zero. Every other part of the page was identical in
  the fleet A/B. The record appears after the first settle pass on new code. Betting change: no.
- I flagged `ac2cbc2fc` (launcher role spec) to them as another ride-along; it is read at `up`, not at reload.
- **Owed after their load:** one `/portfolio/paper` GET timed from the web access log with no WORKER TIMEOUT,
  and `PAPER_ALL_TIME_WRITTEN` after refresh-worker's next restart.

## PAPER PAGE RETIRED (user "Retire it", ~1:05 PM CST; lane `paper-page-retirement`)

- **Question, answered with the logs (web.log.1 + web.log, ~10-03..now):**
  - 176 requests to `/portfolio/paper` or `/api/portfolio/paper` in all. The last browser visit was
    **2026-10-19** (one session: 3 page views, 4 API calls). Every request since came from a script: 105 on
    11-02/03, 1 on 11-10, and mine on 11-17.
  - For comparison, `/portfolio` had 16 browser visits since 11-01.
  - No scheduled job, worker or other page calls it. The only programmatic reader,
    `scripts/measure_game_market_option_value.py`, was a one-off study, last touched 10-06.
- **Kept:** the paper BOOK. Workers place and settle paper orders (813 on 11-17), and the following read
  the ledger directly, not this endpoint:
  - sizing's credibility sample (`settled_decisions_by_sport`);
  - the min-EV tuner;
  - the paper ladder and policy studies.
- **Removed:**
  - `_paper_portfolio_payload` and `_paper_date_nav`;
  - `portfolio_paper.html` and `paper_portfolio_pulse.js`;
  - the "Paper portfolio" link on `/portfolio`;
  - the Paper entry in the book switcher (`BUILTIN_PORTFOLIOS`; `paper` stays a reserved id);
  - `execution_ledger.ledger_for_date` / `_archived_rows_for_date` and `paper_settlement.read_paper_all_time`.
    I added these today; with the page gone, nothing calls them.
- **Retired routes:** `/portfolio/paper` now 302-redirects to `/portfolio` (as `/portfolio/live` does), and
  `/api/portfolio/paper` answers **410** with `PAPER_PAGE_RETIRED` saying where the data is now.
- **The all-dates paper record moves to Portfolio Watch.**
  - The refresh-worker's settle pass still writes it (`write_paper_all_time`, at most every 10 min).
  - Its `PAPER_ALL_TIME_WRITTEN` line now carries won / lost / push / roi_pct / win_pct, counts and rates
    only, with no dollars.
  - The probe reads the newest such line, and the page has a "Paper book, all dates" tile.
  - Until the refresh-worker loads that code (its next restart after a fleet ff past this commit), the tile
    shows "—".
- **Research script:** `measure_game_market_option_value.py` reads its cache, then `--ledger-json`, a fleet
  dump of `full_history_orders()`. Without either it says the API is retired.
- **Shared file:** `syndicate/blueprints/intelligence.py` is also claimed by `nba-live-props-midnight`
  (`_lens_prop_index` and `_refresh_lens_prop_live_columns` only). My hunks touch neither function. A note is
  in that lane's block, because my block replacement ran as a script, which the lane guard does not see.
- **Tests:** `test_portfolio_paper_page.py` deleted. `test_paper_payload_request_path.py` rewritten: worker
  record, throttle, settle-pass reachability, the line's fields with no `$`, redirect plus 410, switcher.
  Updated: live page, auth, books, credibility, ledger archive, probe (+1).
- **Not deployed.** This lands on main after `5db26434e` (tonight's approved load, which carries `2148f99cb`),
  so it reaches the fleet with a later ff. Betting change: no (a page and an API removed, one log line
  widened).

## Reading 6 — Tue 11-17 1:03 PM CST (19:04Z), window 70 min

- **Endpoints:** all 7 read 200, inside budget (`live` 1.09 s, `live?on=all` 1.00 s, `/portfolio` 0.78 s).
  - Web: **0 worker kills; none since 16:49:49Z** (2 h 14 min). 0 5xx on 16 portfolio requests; 0 from a browser.
- **Banner:** ok, armed, worker state 299 s old (limit 900).
- **Execution, 70 min:** 22 live ticks (11 per venue), 5 placed (kalshi 3, polymarket 2), 0 failed.
  117 refused `outside_price_band`.
- **Live plan kalshi 18:45Z:** 886 -> 28 placeable -> 7 positions (831 of 886, 94%, below the net floor).
- **Orders today:** 33 (32 filled, 1 resting). Cap use: kalshi 14.9%, polymarket 13.1%.
- **Gate clock moved to BC-030** (18:04:04Z, #824: college live totals below the points scored are refused).
  0 of 800 events.
- **Register (origin/main, read 19:1xZ):**
  - the 16:24Z #814 refusal was classified by its lane: BC-027 / BC-031, `yes`, loaded at the 17:26:26Z
    refresh-worker TERM. My fail-closed fallback is not needed.
  - **2 entries stay unclassified, handed to their lanes:** 16:17:31Z NFL week-11 rebuild (`nfl-profile-load`)
    and the 17:01:55Z ff `8aea4fe7e -> 0a60d9e0a`, no restart (`ncaaf-sim-history-order-dedupe`).
  - Both are older than BC-030, and the 17:26:26Z refresh-worker restart loaded anything ff'd before it.
    However they are classified, the clock start stays at BC-030 and the count at 0.
- **Paper book record:** no `PAPER_ALL_TIME_WRITTEN` line yet. Expected: the writer is in `2148f99cb`, which is
  not on the fleet until tonight's load.
- **Unchanged anomalies:** unreconciled `f8b62e6a`; the resting maker-pilot order (772 min); the late NHL bet
  (16.4 h).

## FINDING 1 — the fix measured on the fleet, 1:08 PM CST (19:08Z)

- `2148f99cb`'s web half went live at 18:58:52Z, riding lane `board-query-row-refs-load`'s ff
  `92ae7490a -> 5db26434e` plus reload-web. The user answered "Carry both"; deploys.md 18:58:45Z, BC-032 `no`.
- **One authenticated `GET /api/portfolio/paper?date=2026-11-17` at 19:07:37Z:**
  - 200, 2.38 MB, **31.4 s** server-side (access log 31,375 ms); 908 paper orders; `ledger_error` and
    `settlement_error` None; `settlement_all_time` None, as expected until refresh-worker loads the writer.
  - **No WORKER TIMEOUT.** The same request on the old code ran ~177 s at 16:10Z until gunicorn killed its worker.
- **Not a clean cost reading. The web was saturated during it.** In the same seconds:
  - `POST /api/intelligence/query` 42,280 ms (11.3 MB);
  - `POST /api/syndicate/query` 31,978 ms and 21,068 ms;
  - `GET /intelligence` 9,023 ms;
  - a `COMBINED_BOARD_OVERLAY_WARMED ... build_s=64.24`;
  - a hard memory recycle at 19:07:03Z (pid 4075611, anon 823 MB, drained with 1 in flight, exited
    19:07:42Z, no kill).
  - With 2 workers x 4 threads, wall time here is mostly waiting on that work. The fleet A/B measured
    0.5-0.7 s warm and 9.8 s cold-import at nice 19.
  - **Lane goal "< 3 s": NOT shown on the fleet.** The lane is closed DRIFTED, and the page is retired at the
    next ff after `f7fb3ed4e`, so I am not re-measuring it.
- **NEW LEAD for F3 (silent kills), not tested:** the combined-board overlay warmer runs inside web workers and
  one build took **64.24 s**. Its WARMED line carries no pid, so a warm still running when its worker was killed
  would leave no line. Next test: `build_s` over the day against the kill times, from warmer STARTED to
  WARMED / kill.

## Reading 7 — Tue 11-17 1:58 PM CST (19:58Z), window 55 min — after a Windows restart

- **Fleet event:** Windows was restarted from the Start menu at 13:48:57 CST (System event 1074,
  StartMenuExperienceHost, on behalf of the signed-in user, reason "Other"); LastBootUpTime 13:50:05.
  - The fleet was not drained. It came back LIVE by itself: WSL up 13:51:05, web / refresh-worker /
    live-odds-worker pids 496 / 560 / 561 from ~19:51:20Z, supervisor `LOCAL PRODUCTION UP ... commit=5db26434e310`.
  - All Claude sessions restarted with it. My 2:01 PM loop wakeup did not fire; this reading was taken by hand.
- **Balance read failure 1.5 min before the restart:** `[live_odds_worker] VENUE_BALANCES error` at
  19:47:19Z, Kalshi `balance_auth_error`, Polymarket `balance_path_unknown`. Cause unknown; it preceded the
  restart click.
- **Zero caps on the page for ~9 min, display only:**
  - The new live-odds-worker stamped its execution state at boot, ~19:51:19Z. That was 3 s before its first
    balance read (19:51:22Z, both ok), so the stamp carried the 19:47 failure: `fail_closed` for both
    venues, every dollar cap 0.
  - The page shows the worker's stamp (`read_execution_state`), so `/portfolio` showed zero caps.
  - The worker's own enforced caps were nonzero at 19:51:54Z and 19:52:21Z (`[execute_portfolio] LIMITS`),
    and its ticks refused only `outside_price_band`. No live bet was blocked by it.
  - Healed by the next stamp, 20:00:03Z: caps nonzero, `fail_closed` empty, caps from the 13:51:22 read.
- **What the restart loaded:**
  - refresh-worker: 92ae7490a..5db26434e, newly. That is the launcher change, lane tools, the board-query
    `row_refs` response, and `2148f99cb`'s `write_paper_all_time`. No betting change.
  - live-odds-worker: d7c183d8d..5db26434e (it had run since the morning). Of the execution files, only
    `execution_ledger.py` changed (+54, `2148f99cb`, display). #814's MLB entry hold reaches it now; MLB is
    out of season, so no bet is affected, as BC-022 said.
  - Recorded in deploys.md as a READING with `betting change: no`, so the register is not blind to it.
- **Endpoints:**
  - **`/api/portfolio/settings` 13.31 s** (budget 2 s; 0.0-0.12 s all day), on a web 6.5 min after a cold
    start. Watching, not acting.
  - The other six read 200 inside budget (`live` 2.16 s).
  - Web: 0 kills since the restart; 0 browser requests.
- **Plan:** 36.5 min old (the refresh-worker restarted mid-cycle). Board 5,100 -> suggested 85 -> sized 25
  -> positions 11.
- **Live plan kalshi 19:21Z:** 877 -> 30 placeable -> 9 positions.
- **Execution, 55 min:** 12 live ticks; 3 placed (kalshi); 0 failed; 64 refused `outside_price_band`.
- **Orders today:** 36 (35 filled, 1 resting). `unknown_submits` 0 after the restart, so no order was lost
  mid-submit.
- **Paper record:** no `PAPER_ALL_TIME_WRITTEN` line yet. The writer is now loaded on the refresh-worker;
  expect it after its first settle pass. That line has rows / settled / pending only until `f7fb3ed4e` loads.
- **Unchanged anomalies:** unreconciled `f8b62e6a`; the resting maker-pilot order (826 min); the late NHL bet
  (17.3 h); the 2 unclassified loads (16:17Z, 17:01Z), handed to their lanes.

## Reading 8 — Tue 11-17 2:52 PM CST (20:52Z), window 56 min

- **Endpoints:** all 7 read 200, the fastest of the day (`live` 0.31 s, `live?on=all` 0.28 s, `/settings`
  0.00 s). Reading 7's 13.31 s `/settings` was the web's cold start after the restart; it has not recurred.
  - Web: 0 kills, 0 5xx, 0 browser requests.
- **Banner:** ok, armed, worker state 37 s old.
- **Plan (1.2 min old):** board 4,757 -> suggested 87 -> sized 25 -> positions 11.
  - Refusals: beyond_max_positions 59, below_min_stake 14, below_min_ev_after_fair_noise 2, zero_kelly 1.
  - Staked share of the ceiling 20.3%.
- **Execution, 56 min:** 17 live ticks; 3 placed (kalshi 2, polymarket 1); 0 failed; 68 refused
  `outside_price_band`.
- **Orders today:** 39 (38 filled, 1 resting). Cap use: kalshi 18.0%, polymarket 13.8%.
- **The paper all-dates writer works on the fleet** (`2148f99cb`'s worker half, loaded by the 19:51:20Z restart):
  - `[paper_settlement] PAPER_ALL_TIME_WRITTEN` at 20:11:30, 20:23:45, 20:35:25 and 20:45:34Z: every 10-12 min,
    0 `PAPER_ALL_TIME_FAILED`.
  - Latest: 51,936 paper rows, 14,606 settled, 592 pending.
  - Won / lost / ROI are absent on this line format until `f7fb3ed4e` loads, so the Portfolio Watch tile shows
    the settled count and dashes.
- **Unchanged anomalies:** unreconciled `f8b62e6a`; the resting maker-pilot order (880 min); the late NHL bet
  (18.2 h); the 2 unclassified loads (16:17Z, 17:01Z), with their lanes.

## F4 FIXED — the stuck Kalshi order (user "fix the stuck Kalshi order", ~3:10 PM CST; lane `stuck-kalshi-fill-repair`)

- **What it was:** key `f8b62e6a`, an in-play IOC for 4 NO on `KXNHLGAME-26NOV13NSHVGK-NSH` (NSH @ VGK, 11-13
  slate), submitted 2026-11-14 05:55:45Z late in the game.
  - It filled at once. Kalshi's per-order read: `executed`, `fill_count_fp 4.00`, taker cost $1.76 (0.44 a
    contract, inside the 0.62 limit), fee $0.069.
  - The row stayed `submitted`. Venue settlement graded it `lost`, pnl -1.829 = -(1.76 + 0.069), at 05:59:19Z,
    before any reconcile pass read the fill.
  - `reconcile_live_orders` takes only outcome-is-None rows, so status, contracts and price could never be
    filled in. `UNRECONCILABLE_ORDER ... outcome_already_set` was logged on every pass and `/portfolio` listed it
    unreconciled for 3 days.
  - **The loss was real and correctly graded; only the fill bookkeeping was missing.**
- **Fix:** `execution_ledger.operator_fill_from_venue` (main `b96ea17a7`, 12 tests) writes exactly reconcile's
  filled-branch fields from the reconciler's own view of the venue's per-order read.
  - It never touches outcome, P&L or settlement fields, and keeps `pre_operator_fill` and `operator_fill`
    (evidence, note, time).
  - It refuses not-live, not-submitted, ungraded, identity mismatch, no fill, absurd fill, or no note.
  - CLI `scripts/operator_fill_from_venue.py`: dry run by default.
- **Applied on the fleet 21:45:02Z** (my worktree's code against the fleet store, with the live-odds-worker's
  env, nice 19; `_load`/`_persist` are identical to the fleet's). The ledger's CAS write landed:
  `OPERATOR_FILL ... contracts=4 fill_price=0.44 fill_stake=1.76 outcome=lost (unchanged)`.
- **Verified, read 21:45Z:** `/api/portfolio/live?on=all` shows unreconciled **0** (was 1 at every reading
  today); the row is `filled`, 4, 0.44, $1.76, fee $0.069, `executed`, still `lost` / -1.829. 
- **Owed:** no `UNRECONCILABLE_ORDER key='f8b62e6a…'` on a reconcile pass after 21:45:02Z. The last lines were
  live-odds 21:43:21Z and refresh 21:33:01Z, and no pass had run 29 s after the write.
- **Root cause stays possible:** an in-play IOC that venue settlement grades before reconcile reads its fill.
  This is the first in 2,282 live orders. The operator path is the documented exit; a reconcile change that
  fills in venue-graded rows would be its own lane.

## Reading 9 — Tue 11-17 3:46 PM CST (21:46Z), window 62 min

- **Endpoints:** all 7 read 200, inside budget (`/portfolio` 1.34 s, `plan` 0.86 s). 0 5xx; 0 browser requests.
- **Ledger:** unreconciled **0** (was 1 at every reading until the 21:45:02Z operator fill); unknown submits 0.
- **F4 verify (partial):** refresh-worker ran 6 execution passes after 21:45:02Z with **0**
  `UNRECONCILABLE_ORDER` lines for `f8b62e6a`. Its last was 21:33:01Z. live-odds-worker had not run a pass since
  the write (its last line was 21:43:21Z); it is checked next reading.
- **Banner:** ok, armed, state 335 s. **Plan (1.6 min):** board 4,581 -> suggested 96 -> sized 25 ->
  positions 13; beyond_max_positions 67.
- **Execution, 62 min:** polymarket 9 live ticks, 5 placed, 0 failed, 48 refused `outside_price_band`.
  Orders today 41. Cap use: kalshi 18.3%, polymarket 15.9%.
- **Paper record (21:46:10Z):** 52,007 rows, 14,606 settled, 612 pending.
- **NEW: a 5th silent web worker kill, 21:36:36Z, pid 19708** (after the restart). It has no recycle or drain
  line, like the 4 earlier today.
  - Its 120-s window again holds only short requests: `/wnba/api/live_player_boxscore` 3.1 s, `/syndicate`.
  - **Tested and NOT discriminating:** `/wnba/api/live_player_boxscore` (a `compute in request path` ESPN
    fetch). It sat in 4 of 5 kill windows, but it is polled every ~75 s (414 requests since 12Z), so it sits in
    every window.
  - **A shift worth keeping:** its mean duration was ~0.7 s per hour at 12-14Z and 1.2-2.6 s from 15Z on. The web
    slowed around the hour the kills began (15:23Z).
  - **F3 is outside the portfolio endpoint:** it is web capacity, which hurts every route. It needs its own lane
    (leads: the 15Z slowdown, 21-42 s board / Syndicate queries, the 64 s overlay warm in a web worker).
- **Unchanged anomalies:** the resting maker-pilot order (934 min); the late NHL bet (19.1 h); 1 unclassified
  load (was 2).

## Reading 10 — Tue 11-17 4:29 PM CST (22:29Z), window 45 min — after the 21:53Z drained down/up

- **The paper retirement is live** (fleet `91d865fd5` since the 21:53Z drained down/up). Read 21:55Z:
  `/portfolio/paper` 302 -> `/portfolio`; `/api/portfolio/paper` 410; `/portfolio` has no Paper link; book
  switcher `["live"]`. deploys.md 21:56Z.
- **The widened paper record line is live:** at 22:19:25Z, `PAPER_ALL_TIME_WRITTEN` 52,033 rows, 14,606 settled,
  615 pending, **7,362 W / 7,104 L / 58 P, win 50.89%, ROI -1.39%**.
  - A statistical read, not advice: the paper book, all dates (all simulated, no money), sits about 1.4% under
    break-even on 14.6k settled order rows. Rows are not independent: the same decision appears at several
    paper venues, so the true sample is smaller.
- **Endpoints:** all 7 read 200, the fastest of the day (`live` 0.22 s, `/portfolio` 0.28 s). 0 kills, 0 5xx,
  0 browser requests.
- **Banner:** ok, armed, state 333 s. **Ledger:** unreconciled 0 and unknown submits 0, for a second reading.
- **Plan (3.4 min):** board 4,719 -> suggested 82 -> sized 25 -> positions 7; beyond_max_positions 53,
  below_min_stake 18.
- **Execution, 45 min:** 14 live ticks; 5 placed (all kalshi), 0 failed; 76 refused `outside_price_band`.
  Orders today 50 (49 filled, 1 resting). Cap use: kalshi 20.7%, polymarket 16.0%.
- **Anomalies (3, unchanged):** the resting maker-pilot order (977 min); the late NHL bet (19.8 h); 1 unclassified
  load.

## The "resting maker-pilot order" was a monitor false positive (user "fix the resting maker-pilot order", ~5:00 PM CST)

- **The order:** key `a1f809ca`, `execution_style=maker_pilot`, NCAAF spread, Ball State +10.5 at Ohio
  (`KXNCAAFSPREAD-26NOV17BALLOHIO-OHIO11`). A $5 post for 11 contracts, submitted 06:12:21Z
  (`[kalshi_maker_pilot] MAKER_PILOT POST`, `tif=good_till_canceled`, `expiry=1794960000` = 2026-11-18T00:00:00Z
  = its kickoff, 6 PM CST). 0 of 11 filled.
  - The reconciler read it at 22:24:17Z (`resting`, `venue_open` True). The live-odds-worker re-priced the
    ticker on 66 ticks today (`LIVE_PRICE`).
- **Working as designed:** `cancel_stale_resting_orders` (`execution_ledger.py:4127`) exempts maker-pilot posts
  from the 900 s stale cancel. A post's life ends in one of three ways: the venue expiry at commence, the
  kickoff cancel, or the fair-move cancel (`kalshi_maker_pilot.review_resting`, per tick). Nothing was stuck,
  and nothing was cancelled or changed.
- **The defect was the probe's generic "resting > 120 min" rule.** Fixed in `scripts/portfolio_monitor_probe.py`
  (`resting_overdue_reason`):
  - a maker-pilot post is overdue only if it is still resting more than 10 min after its kickoff;
  - any resting order is overdue if the reconciler has not read it for 30 min;
  - other orders keep the 120-min rule.
  - 3 new tests; 14 pass.
  - On the 22:29Z payload at its own time: 1 resting, 0 overdue, so no ORDERS anomaly.
- **Owed:** after 00:10Z, the order reads expired / not resting (Kalshi's own expiry at kickoff). If it is still
  resting, the probe now flags it by name.

## Reading 11 — Tue 11-17 5:16 PM CST (23:16Z), window 48 min

- **Endpoints:** all 7 read 200, inside budget. 0 kills, 0 5xx, 0 browser requests. **Banner:** ok, armed,
  state 270 s.
- **The maker-pilot post is no longer flagged** (the probe change; the post rests until its 6 PM kickoff).
- **Plan (15 min):** board 4,803 -> suggested 87 -> sized 25 -> positions 10.
  - Live plans 23:11Z: kalshi 308 rows in (was ~900, as tonight's games go in play), polymarket 240 (was 428).
- **Execution, 48 min:** 16 live ticks; 2 placed; 0 failed. Refused: 57 `outside_price_band` and a new reason,
  **`axis_held_live` 6** (kalshi), meaning a live position is already held on that axis.
- **Ledger:** unreconciled 0, unknown submits 0. Orders today 52. Cap use: polymarket 16.7%.

### The late NHL bet, diagnosed (read-only): Kalshi graded it won, but our venue grader cannot attribute the payout

- **The bet:** key `a2c3f0c0`, 11-16 slate, Utah +1.5 vs Vancouver as NO on `KXNHLSPREAD-26NOV16VANUTA-VAN2`.
  An in-play IOC at 04:44:44Z 11-17, reconciled `filled` 4 at 0.66 ($2.64, fee $0.0629).
  - A take-profit exit fired at 05:18:04Z, but `FAST_EXIT_LIVE_DISPATCH ... live_exits={'phase_not_armed': 1}`:
    in-game live exits are off (BC-003), so it was held to the end.
- **Kalshi:** market `finalized`, `result=no`, closed 05:19:35Z, so **our NO won** (Vancouver won by 1). The
  bet tracker on the row also reads `won`.
- **Why it is ungraded after 20 h:** Kalshi's settlement row for the ticker carries our `no_count_fp 4.00`
  ($2.64) **and `yes_count_fp 66.46` ($23.93) on the same account**.
  - The YES side is not in our ledger. It is among the foreign-client orders that `RECONCILE_ORPHANS` counts
    every pass (357 on Kalshi).
  - With both sides held, `grade_kalshi_settlement` cannot hand the row's revenue to our order (the
    `both_sides_held` refusal, documented in `operator_grade_from_venue`).
  - `settle_from_venue(dry_run=True)` on the fleet (23:3xZ): status ok, settled 0, awaiting 72, refused 1,
    errors 0. Kalshi settlements fetched: 1,375, error None.
- **Expected resolution, no action now:** `settle_orders` holds a live row for the venue for
  `_venue_grace_hours()` = **24 h** after its start (02:40Z 11-17), then grades it from the game. Due at **02:40Z
  11-18 (8:40 PM CST tonight)**.
  - If it is still ungraded by then, `execution_ledger.operator_grade_from_venue(..., market_result="no")` is the
    documented exit for exactly this case.
- **Worth knowing:** another client trades on the same Kalshi account (66.46 YES on this market). Every such
  overlap delays our venue grade by up to 24 h.

## Reading 12 — Tue 11-17 5:56 PM CST (23:56Z), window 41 min

- **Endpoints:** all 7 read 200, inside budget (`live?on=all` 0.22 s, `/portfolio` 0.25 s). 0 kills, 0 5xx, 0 browser
  requests. **Banner:** ok, armed, state 211 s.
- **Plan (1.2 min):** board 4,859 -> suggested 97 -> sized 25 -> positions 7; beyond_max_positions 62,
  `in_play_market_fair` 5.
  - Live plans 23:55Z: kalshi 887 -> 31 placeable -> 8 (814 below the net floor); polymarket 586 -> 17 -> 6.
- **Execution, 41 min:** 14 live ticks, **0 placed**, 0 failed. Refused: 47 `outside_price_band`, 14 `axis_held_live`.
- **Ledger:** unreconciled 0, unknown submits 0. Orders today 52 (unchanged). Cap use: polymarket 16.8%.
- **Owed next reading:** the maker-pilot post `a1f809ca` ends at its 00:00Z kickoff (Kalshi expiry), and the late
  NHL bet gets its score-grader grade after 02:40Z.

## Reading 13 — Tue 11-17 6:27 PM CST (00:27Z 11-18), window 32 min

- **The maker-pilot post ended as designed:** `a1f809ca` was reconciled at 00:00:07Z as `venue_status=canceled`,
  `venue_open` False, 0 contracts, recorded `rejected` / `error=venue_canceled` (the status that frees its budget).
  This is Kalshi's expiry at its kickoff. **Verify for the earlier "fix the resting maker-pilot order": MET.**
- **Probe refined, one more false positive removed:** that ending was then counted as "failed or rejected today: 1/54".
  A maker post the venue cancelled or expired unfilled is now counted separately (`maker_posts_expired_unfilled`)
  and not as a failure. 15 tests pass.
- **Endpoints:** all 7 read 200, the fastest of the day (`live` 0.19 s, `/portfolio` 0.19 s). 0 kills, 0 5xx.
  **Banner:** ok, armed, state 283 s.
- **Plan (1.9 min):** board 4,982 -> suggested 96 -> sized 25 -> positions 7; `in_play_market_fair` 13 (games live);
  **ceiling used 42.9%** (16-23% earlier).
- **Execution, 32 min:** 10 live ticks; 2 placed (1 per venue); 0 failed. Refused: 28 `outside_price_band`,
  9 `axis_held_live`, 6 `game_started`.
- **Orders today:** 54. Ledger: unreconciled 0, unknown submits 0. Cap use: polymarket 17.6%.
- **Settlement:** 7 started bets unsettled, 1 late. The late one is the NHL both-sides case; score grader due 02:40Z.

## Reading 14 — Tue 11-17 6:59 PM CST (00:59Z 11-18), window 32 min

- **Endpoints:** all 7 read 200, inside budget. 0 kills, 0 5xx. **Banner:** ok, armed, state 297 s.
- **Plan (3.7 min):** board 4,835 -> suggested 110 -> sized 25 -> positions 7; `in_play_market_fair` 31 (games live).
  Ceiling used 12.0%. Live plans 00:56Z: kalshi 743 -> 34 placeable -> 4; polymarket 548 -> 25 -> 4.
- **Execution, 32 min:** 8 live ticks, 0 placed, 0 failed (22 `outside_price_band`, 1 `game_started`).
- **Ledger:** unreconciled 0, unknown submits 0. Orders today 54. Settlement: 26 started-and-unsettled (games in
  progress), 1 late (the NHL both-sides case).
- **Register:** the 23:46Z "DEPLOY ATTEMPT ABORTED, NOTHING LOADED" entry (lane `ncaaf-grid-build-speed`) was a
  heuristic false positive; classified `no` (BC row added). 1 unclassified load remains (16:17Z NFL rebuild,
  with its lane).

## The late NHL bet GRADED (user "fix the late NHL bet", ~7:05 PM CST)

- `a2c3f0c0` (Utah +1.5 as NO on `KXNHLSPREAD-26NOV16VANUTA-VAN2`) was graded at 01:16:32Z 11-18 by the existing
  `scripts/kalshi_operator_grade.py`, the documented exit for `both_sides_held`. Outcome **won**, pnl **+1.2971**
  (own fill: 4 x 0.34 - 0.0629 fee), `settled_by` venue; evidence, note and the prior fields are kept on the row.
- **Verified:** `/api/portfolio/live` row won +1.2971; late settlements 0 (was 1 at every reading today).
  deploys.md 01:16:32Z.
- **The cause stays:** another client trades on the same Kalshi account (357 foreign-client orders in
  `RECONCILE_ORPHANS`). Any market where both hold positions makes `grade_kalshi_settlement` refuse
  `both_sides_held`. The score grader takes over after 24 h; this tool is the faster exit.

## Reading 15 — Tue 11-17 7:31 PM CST (01:31Z 11-18), window 33 min

- **Anomalies down to 1** (the 16:17Z NFL rebuild, unclassified, with its lane). **Late settlements 0** after
  the 01:16:32Z operator grade of the NHL bet. Unreconciled 0, unknown submits 0.
- **Endpoints:** all 7 read 200 and inside budget, but the slowest since the morning on a busy live-slate web:
  `/portfolio` 2.30 s (budget 3), `live?on=all` 1.77 s, `live` 1.44 s, `settings` 0.84 s. 0 kills, 0 5xx.
- **Plan (12.9 min):** board 5,027 -> suggested 130 -> sized 25 -> positions 9; `in_play_market_fair` 40.
  **`key_player_out` 2 is the first time today the #814 live player-exit gate refuses in the plan.** Ceiling used
  27.2%.
- **Execution, 33 min:** 10 live ticks, 0 placed, 0 failed (20 `outside_price_band`, 7 `game_started`). Orders
  today 54.

## Reading 16 — Tue 11-17 8:02 PM CST (02:02Z 11-18), window 32 min

- **Endpoints:** all 7 read 200 and are fast again (`/portfolio` 0.33 s). 0 kills, 0 5xx. **Banner:** ok, armed,
  state 262 s.
- **Plan read at 43.9 min old (stale line 45).** That plan is tonight's (11-17), generated when `portfolio_commit`
  started at 01:18:10Z. *Corrected 02:11Z:* this note first said a fresh plan followed 29 s later, but that write
  (02:02:23Z) was **tomorrow's** (11-18) plan. The board loop alternates dates, and its 01:51:40Z cycle built 11-18
  (shortlist 430.4 s, board 829.4 s). No 11-17 plan has been written since 01:21:13Z; it was 53 min old at 02:11Z.
  Cause: the board cycle that started 01:05:38Z ran for 25 min (`BOARD_BUILD_TIMING wall_s=1509.8`). Its
  shortlist span took 633.4 s, against 63-138 s for each of the 18 builds from 23:55 to 00:55Z. The next cycle started
  46 min after that one began. Finding F7; handed to lane `layer2-board-process-split` (02:09Z), which owns the build.
- **Gate clock PENDING (count 0), as designed:** BC-041. The web-silent-worker-kills ff to `3920a2d4d` carries
  ride-along `ee47c930a` (NFL live re-sim event-id seeds), a `yes` pending the refresh-worker's next restart.
  It is registered by that session, so the register is doing its job.
- **Execution, 32 min:** 10 live ticks, 0 placed, 0 failed (20 `outside_price_band`, 10 `game_started`).
- **Orders today:** 54 (53 filled, 1 rejected: the maker post's kickoff expiry, which is no longer counted as a
  failure). Resting 0. Late settlements 0; 34 started bets unsettled while games are live. Cap use: kalshi 18.3%,
  polymarket 17.6%.

## Reading 17 — Tue 11-17 8:22 PM CST (02:22Z 11-18), window 30 min

- **New instrument: tonight's plan cadence** (`plan_commits`, asked for by lane `layer2-board-process-split` as the
  portfolio-side before/after for its board-process switch). The probe reads 6 h of `LIVE_PLAN_WRITTEN` lines per
  date. Venue lines of one date less than 3 min apart are one commit, and a write for tomorrow does not count for
  tonight. Tonight (11-17): **41 commits in 6 h, max completed gap 45.0 min; newest 01:21:13Z, 60.7 min ago.**
  11-18's newest is 02:02:23Z.
- **PLAN stale 64.3 min (> 45): finding F7, real.** The board loop published 11-18 at 02:05:37Z
  (`board_publication` 847 s), then ran `LAYER2_AROUND_NEXT_DAY phase=after ... ran=yes` (02:11:59), then
  `LOOP_ITERATION` (02:13:05), then Layer 2 shard writes until 02:22:43. **No 11-17 cycle had started by 02:22:51Z.**
  Bets are still checked against current prices before placement (`outside_price_band` 20, `game_started` 10 in the
  window), so the likely cost is missed bets, not bad ones. Sent to the owning lane 02:24Z.
- **Endpoints:** all 7 read 200 inside budget (`live?on=all` 1.25 s, `/portfolio` 0.70 s). 0 kills, 0 5xx.
  **Banner:** ok, armed, state 184 s.
- **Execution, 30 min:** 10 live ticks, 0 placed, 0 failed. Orders today 54 (53 filled, 1 rejected maker expiry).
  Resting 0. Late settlements 0, 32 started bets unsettled while games are live. Cap use kalshi 18.6%, polymarket 17.6%.
- **Gate:** clock pending BC-041 (count 0), as designed until the refresh-worker restart loads `ee47c930a`.

## F7 diagnosed — why tonight's plan goes stale (Tue 11-17 8:31 PM CST, read-only)

The user asked to "fix the stale plan". Hypothesis before reading: the plan only waits on slow board builds.
**Partly false.** From `refresh-worker.log`, every step on the board-loop thread between today's `portfolio_commit`s:

- **Gap 1: 4:58 -> 5:46 PM CST (22:58 -> 23:46Z), ~48 min.**
  - A next-day (11-18) cycle: 23:03-23:13Z.
  - 16 `DEFERRED_BOARD_BUILD reason=deploy_drain_requested`, 23:14:42-23:32:44Z: a refresh-worker drain that never
    reached an idle worker.
  - `_refresh_today_layer2_on_cadence`: 23:33-23:39Z.
  - Today's build: 542 s.
- **Gap 2: 7:21 PM -> still open at 8:30 PM CST (01:21Z -> after 02:30Z), 69+ min.**
  - The rest of the 1,510 s build: paper execution and persist, to 01:33Z.
  - `LAYER2_TODAY_CADENCE ran=yes elapsed_s=779.6`: the in-loop Layer 2 refresh, 13 min.
  - The pending 11-18 key popped ahead of today. The queue is FIFO and today is re-queued to the end every pass.
  - Then the 11-18 cycle: refresh before (01:46-01:51Z), build (829 s), refresh after (02:05-02:11Z).
  - Another 10-min in-loop refresh (02:13-02:23Z).
  - Today's build started 02:24:34Z and was still running at 02:30:52Z.
- **For contrast, 00:00-01:04Z:** the loop wrote today's plan every 4-7 min, with builds of 150-350 s.

**One root, three multipliers.** Everything on the loop thread runs 5-10x slower in the live evening.
`layer2-board-process-split` measured why: the board thread gets 0.19-0.46 of a core against the book-grid and odds
threads in one interpreter. Its fix, `09eddabf2` (`SYNDICATE_BOARD_BUILD_PROCESS`), is on main and not loaded. It
needs an env line plus a drained `down`/`up` after a slate, because two live-evening drains on 11-17 never reached an
idle worker. Its pre-registered metric 4 is this lane's `plan_commits` series.

The multipliers stay after the split, but each costs minutes once builds run at calm speed:
- the next-day cycle with its two extra Layer 2 refreshes, about hourly;
- deploy drains;
- the in-loop Layer 2 refresh.

**No live mitigation tonight.** A refresh-worker restart now drops the in-flight build, takes about 20 min to first
publish, and drains have not reached idle this evening. Bets are still checked against current prices before
placement, so a stale plan costs missed bets, not bad ones.
- **USER DECISION, Tue 11-17 ~8:35 PM CST.** The user answered "Load the board-process split after tonight's slate?"
  with "Yes, after the slate". Relayed verbatim to lane `layer2-board-process-split` ("Take the board build out of
  the live tick's process"), which runs the load under its own claims, preflight and betting-change row. Sent with
  it: the clash with lane `ncaaf-grid-build-speed`'s 1:10 AM CST TERM-only refresh-worker load at `3920a2d4d`, which
  refuses if the fleet head moves. This lane keeps the `plan_commits` series running for that lane's metric 4.

## Reading 18 — Tue 11-17 8:34 PM CST (02:34Z 11-18), window 35 min

- **Only finding F7 is still open: tonight's plan is 76.1 min old.** Tonight's newest write is still 01:21:13Z, 72.5 min
  ago. Today's build started at 02:24:34Z and was still running at this reading.
  - In 6 h: 39 commits, max completed gap 45.0 min.
  - Fix approved by the user (load after the slate). The owning lane sequences it after the 1:10-1:40 AM CST
    `ncaaf-grid-build-speed` restart and the 1:50 AM I-17 task, starting about 2:00-2:15 AM CST. This lane reads
    through that window.
- **Endpoints:** all 7 read 200 inside budget (`live` 1.67 s of 3.0, the slowest). 0 kills, 0 5xx.
  **Banner:** ok, armed, state 190 s.
- **Execution, 35 min:** 10 live ticks, 0 placed, 0 failed (20 `outside_price_band`, 10 `game_started`).
  - Orders today 54 (53 filled, 1 rejected maker expiry). Resting 0. Late settlements 0.
  - 32 started bets are unsettled while their games are live.
  - Cap use: kalshi 18.6%, polymarket 17.6%.
- **Gate:** pending BC-041 (count 0). One unclassified load (16:17Z NFL rebuild) remains with its lane.
- **No new anomaly.**

## Reading 19 — Tue 11-17 9:06 PM CST (03:06Z 11-18), window 33 min

- **Tonight's plan was rewritten at 02:40:12Z (8:40 PM CST), ending a 79.0-min gap** (01:21:13 -> 02:40:12Z). This is the
  longest tonight and is finding F7. Plan age 30.1 min at the reading.
  - In 6 h: 36 commits.
  - The fresh plan is larger: kalshi rows_in 625 -> 27 placeable -> 3 positions; polymarket 579 -> 20 -> 3.
  - The plan as a whole: 109 suggested -> 25 sized -> 11 positions.
  - Ceiling used 27.2% -> 32.3%.
- **Execution, 33 min: 2 placed** (1 kalshi, 1 polymarket), the first live placements since reading 14, both after the
  rewrite. 10 live ticks, 0 failed, refused 12 `outside_price_band` and 2 `game_started`.
  - Orders today 57: 55 filled, 1 submitted, 1 rejected maker expiry.
  - Resting 1, 1.2 min old.
  - Cap use: kalshi 20.8%, polymarket 18.5%.
- **NEW anomaly: `LEDGER unreconciled: 1 (6d56320b)`.**
  - *Hypothesis, written before the check:* it is the order the worker just submitted, and the next reconcile pass
    picks it up. So it is no failure.
  - *Falsified if* it is still unreconciled 15+ min after submit.
  - *Check 03:07:12Z:* it is the NHL Kalshi order submitted 03:05:02Z, status `submitted`, `reconciled_at` null,
    2 min old. **Result (watcher, 60 s polls):** reconciled at 03:08:30Z, 3.5 min after submit. The ledger shows
  `rejected` / `venue_canceled`, `venue_resolved_at` 03:05:04.9Z (2 s after submit), and no contracts. It was an
  in-play entry (`position_key ingame:KXNHLSPREAD-...`), and in-play entries go out immediate-or-cancel
  (`inplay_entries_live._IOC`). So it is a **no-fill, not a failure**: nothing was available at our price that
  instant. Hypothesis confirmed. No money moved.
  - **Probe fix, same lane:** `unreconciled` now alarms only past `UNRECONCILED_GRACE_MIN` = 10 min, or when there
    is no submit time. An unfilled in-play IOC (`is_unfilled_inplay_ioc`) is counted as `inplay_ioc_unfilled`,
    not in `failed_or_rejected`, as was done for the maker-pilot expiry. 2 tests, 18 pass.
- **Endpoints:** all 7 read 200 inside budget (`/portfolio` 1.86 s of 3.0). 0 kills, 0 5xx. **Banner:** ok, armed.
- **Settlement:** 22 started and unsettled while live, 0 late. **Gate:** pending BC-041 (count 0).

## Reading 20 — Tue 11-17 9:34 PM CST (03:34Z 11-18), window 30 min

- **Clean apart from the gate's clock.** Only anomalies: gate pending BC-041 (count 0) and 1 unclassified load with
  its lane.
- **Plan 6.8 min old.** Tonight's newest commit is 03:28:29Z, 5.5 min before the reading.
  - In 6 h: 30 commits, max completed gap still 79.0 min (01:21 -> 02:40Z).
  - 85 suggested -> 25 sized -> 9 positions. Ceiling used 37.6%.
- **Execution, 30 min:** 10 live ticks, 0 placed, 0 failed (10 `outside_price_band`, 3 `game_started`).
  - Orders today 57: 55 filled, 2 rejected. Both rejections are designed endings, now counted as such: the maker
    expiry and reading 19's unfilled in-play IOC. `failed_or_rejected` is 0.
  - Resting 0. Unreconciled 0.
  - Cap use: kalshi 20.8% -> 18.7% (the cancelled IOC's budget came back), polymarket 17.8%.
- **Settlement:** 10 started and unsettled (from 22), 0 late. **Endpoints:** all 7 read 200, all fast
  (`/portfolio` 0.27 s). 0 kills.
- **Paper book (all dates):** 14,688 settled, ROI -1.31%, win 50.92%.

## Reading 21 — Tue 11-17 10:05 PM CST (04:05Z 11-18), window 31 min

- **Clean apart from the gate's clock.**
- **The new unreconciled grace did its job.** 1 order is submitted and unreconciled at 3.1 min old (Polymarket, placed
  in this window). It is reported, not alarmed: `UNRECONCILED_GRACE_MIN` = 10.
- **Plan 5.9 min old.** Tonight's newest commit is 04:00:43Z. The 11-18 board was also written at 03:44:59Z, and
  tonight's next commit came 16 min later, not after a stall.
  - In 6 h: 30 commits, max completed gap 79.0 min (unchanged).
  - 71 suggested -> 25 sized -> 12 positions. Ceiling used 23.4%.
- **Execution, 31 min:** 10 live ticks, 1 placed (polymarket), 0 failed, 9 `outside_price_band`. Orders today 58:
  55 filled, 2 rejected (both designed endings), 1 submitted.
- **Settlement:** 3 started and unsettled (from 10), 0 late. Cap use: kalshi 18.8%, polymarket 18.4%.
- **Endpoints:** all 7 read 200, fast. 0 kills. **Paper book:** 14,772 settled, ROI -1.31%.

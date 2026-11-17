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

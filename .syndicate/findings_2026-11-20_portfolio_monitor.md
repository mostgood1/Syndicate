# Portfolio monitor — Fri 2026-11-20 (lane `portfolio-monitor`)

Continues `findings_2026-11-19_portfolio_monitor.md` (readings 61-93; the 11-19 daily summary goes there once the
day's last game settles). Readings are of the fleet (`http://127.0.0.1:10000`) and read-only. Percentages and counts
only, because this repo is public.

## Reading 94 — Fri 11-20 12:28 AM CST (06:28Z), window 30 min

- **Results first. 11-19 is nearly settled.**
  - 11-19 ("yesterday" now): **50 bets / 22 events, ROI +5.36% [-9.5, +20.2]**. Won 62.0% against a 64.6%
    breakeven, so the return is above zero while the win rate is below breakeven. Fees were 3.52% of stake.
  - **30 d: 1,683 bets / 718 events, -7.36% [-12.8, -2.0]**. The window rolled to take in 11-19 and drop 10-20.
  - 7 d: 403 bets / 180 events, -6.07% [-16.6, +4.5].
  - CLV over 7 d, net of fees: -0.37 pp (se 0.43); beat the close on 64.0% of 178.
  - All-time: 2,145 / 1,149, -10.72%.
  - Gate: **13 of 800 events** (17 bets) on BC-053.
  - 1 game has started and is unsettled; none is late.
- **No new anomaly.**
  - `live_today` 1.64 s, inside its 3.0 s budget; it is the new day's view, 44 KB.
  - The 148-min "max gap" is the 11-20 plan series across its earlier other-date writes, not a stall: the 11-19 plan
    ran to 05:51Z.
  - The GATE line is the same 2 unclassified loads.
- **Flow (new day):**
  - Plan: 40 suggested, 12 positions.
  - Live ticks: 1 placed on Polymarket. 10 refused `already_held_other_slate`, a normal guard at the day boundary.
  - Orders today: 1 filled.
  - Cap use: 0.0% Kalshi, 1.0% Polymarket.
- **30 d slices beyond noise, unchanged in kind:**
  - Kalshi -6.13%; totals -12.54%; `model_edge` -7.53%;
  - EV 2-5 band -10.43% against a predicted +4.07%;
  - price 0.30-0.45 -12.67%;
  - the largest-stake quartile (64.4% of dollars) -9.10%.

## Reading 95 — Fri 11-20 12:59 AM CST (06:59Z), window 31 min

- **Results first. 11-19 is fully graded** (0 games started and unsettled). Its DAILY SUMMARY is in
  `findings_2026-11-19_portfolio_monitor.md`.
  - 11-19: 51 bets / 23 events, +4.21% [-10.8, +19.3].
  - 30 d: 1,684 / 719, -7.38% [-12.8, -2.0].
  - 7 d: 404 / 181, -6.20% [-16.8, +4.4].
  - Gate: 13 of 800 (BC-053).
- **No new anomaly.** `live_today` 0.86 s; every endpoint was inside budget. The GATE line is the same 2
  unclassified loads.
- **Flow (11-20):**
  - Plan 1.0 min old: 44 suggested, 12 positions.
  - Live ticks: 1 placed on Kalshi. 10 refused `already_held_other_slate`.
  - Orders today: 2 filled.
  - Cap use: 4.0% Kalshi, 1.0% Polymarket.
- **Pace:** no games until the afternoon, so readings go hourly or slower overnight.

## Reading 96 — Fri 11-20 2:00 AM CST (08:00Z), window 61 min

- **Results first.** Unchanged overnight:
  - 30 d: -7.38% [-12.8, -2.0] on 719 events;
  - 7 d: -6.20% [-16.8, +4.4] on 181;
  - gate: 13 of 800 (BC-053);
  - nothing open.
- **No new anomaly.**
  - Every endpoint was inside budget. `plan` took 1.81 s of its 6.0 s budget (1,778 ms server-side), the slowest
    tonight.
  - The GATE line is the same 2 unclassified loads.
- **Flow (11-20 pregame):**
  - Plan 1.7 min old: 45 suggested, 13 positions; ceiling used 42.8%.
  - Live ticks: 3 placed (1 Kalshi, 2 Polymarket) in 18; 1 refused `maker_pilot_held`.
  - Orders today: 5 filled.
  - Cap use: 4.4% Kalshi, 1.7% Polymarket.

## Reading 97 — Fri 11-20 3:00 AM CST (09:00Z), window 60 min

- **Results first.** Unchanged:
  - 30 d: -7.38% [-12.8, -2.0] on 719 events;
  - 7 d: -6.20% [-16.8, +4.4] on 181;
  - gate: 13 of 800 (BC-053);
  - nothing open.
- **No new anomaly. Watch item:** `plan` 2.91 s against a 6.0 s budget (server 2,820 ms), up from 1.81 s at
  Reading 96; `page` 1.22 s.
  - Both are inside budget. It becomes an anomaly at more than 6 s, or if it keeps rising into the morning reads.
  - The other endpoints returned in 0.25 s or less.
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 2.8 min old: 27 suggested, 13 positions.
  - Live ticks: 0 placed in 18 (18 `already_held_other_slate`).
  - Orders today: 5 filled.
  - Cap use: 4.4% Kalshi, 1.7% Polymarket.

## Reading 98 — Fri 11-20 4:00 AM CST (10:00Z), window 60 min

- **Results first.** Unchanged:
  - 30 d: -7.38% [-12.8, -2.0] on 719 events;
  - 7 d: -6.20% [-16.8, +4.4] on 181;
  - gate: 13 of 800 (BC-053);
  - nothing open.
- **No new anomaly.**
  - `plan` 2.88 s against a 6.0 s budget, flat against Reading 97's 2.91 s, so it is not rising. Its payload grew
    with the day's plan (209 to 230 KB); the server time was 2,777 ms. The watch stays at "more than 6 s".
  - The plan's own max gap is down to 12.0 min, because the 148-min boundary artifact rolled out of the 6-h window.
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 1.8 min old: 23 suggested, 13 positions.
  - Live ticks: 1 placed on Kalshi in 20.
  - Orders today: 6 filled.
  - Cap use: 4.8% Kalshi, 1.7% Polymarket.

## Reading 99 — Fri 11-20 5:00 AM CST (11:00Z), window 60 min

- **Results first.** Unchanged:
  - 30 d: -7.38% [-12.8, -2.0] on 719 events;
  - 7 d: -6.20% [-16.8, +4.4] on 181;
  - gate: 13 of 800 (BC-053);
  - nothing open.
- **No new anomaly.**
  - `plan` is back to 0.01 s (2.88 s at Reading 98).
  - `live_today` 2.23 s (2,162 ms server-side), inside its 3.0 s budget. It landed 3 s after a plan write (11:00:07Z),
    and the web log has no recycle, no worker boot and no overlay rebuild in 10:57-11:01Z, so no cause is logged.
  - **Running tally since 6 PM 11-19:** 5 of 20 `live_today` reads were above 2 s and 1 was above 3 s. 2 sit on a web
    memory recycle; 3 have no logged cause.
  - Owners as before: `web-silent-worker-kills` and `board-read-cold-share` (#853).
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 0.2 min old: 20 suggested, 13 positions.
  - Live ticks: 1 placed on Polymarket in 20.
  - Orders today: 7 filled.
  - Cap use: 4.8% Kalshi, 2.4% Polymarket.

## Reading 100 — Fri 11-20 6:00 AM CST (12:00Z), window 60 min

- **Results first.** Unchanged:
  - 30 d: -7.38% [-12.8, -2.0] on 719 events;
  - 7 d: -6.20% [-16.8, +4.4] on 181;
  - gate: 13 of 800 (BC-053);
  - nothing open.
- **No new anomaly.** Every endpoint was inside budget (`live_today` 0.20 s, `live_all` 0.39 s). The GATE line is the
  same 2 unclassified loads.
- **Flow:**
  - Plan 3.0 min old: 14 suggested, 8 positions.
  - Live ticks: 1 placed on Polymarket in 20.
  - Orders today: 8 filled.
  - Cap use: 4.8% Kalshi, 3.3% Polymarket.
  - Polymarket placeable: 8 of 384 rows, so its feed is healthy, unlike the F21 window at this hour on 11-19.

## Reading 101 — Fri 11-20 7:00 AM CST (13:00Z), window 60 min

- **Results first.** Unchanged:
  - 30 d: -7.38% [-12.8, -2.0] on 719 events;
  - 7 d: -6.20% [-16.8, +4.4] on 181;
  - gate: 13 of 800 (BC-053);
  - nothing open.
- **No new anomaly.** Every endpoint was inside budget (`live_all` 1.02 s of 5.0 s; the rest 0.27 s or less). The GATE
  line is the same 2 unclassified loads.
- **Flow:** the morning board has widened the plan.
  - 106 suggested (14 at Reading 100), 18 positions; 80 refused `beyond_max_positions`.
  - Placeable: Kalshi 28 of 761 rows, Polymarket 34 of 651.
  - Live ticks: 1 placed on Polymarket.
  - Orders today: 9 filled.
  - Cap use: 4.8% Kalshi, 4.2% Polymarket.

## Reading 102 — Fri 11-20 8:00 AM CST (14:00Z), window 60 min

- **Results first.** Unchanged:
  - 30 d: -7.38% [-12.8, -2.0] on 719 events;
  - 7 d: -6.20% [-16.8, +4.4] on 181;
  - gate: 13 of 800 (BC-053);
  - nothing open.
- **No new anomaly.** Every endpoint returned in 0.31 s or less. The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 2.6 min old: 112 suggested, 14 positions; 84 refused `beyond_max_positions`.
  - Live ticks: 1 placed on Polymarket in 18.
  - Orders today: 10 filled.
  - Cap use: 4.8% Kalshi, 4.9% Polymarket.
  - Plan max gap 10.7 min.

## Reading 103 — Fri 11-20 9:27 AM CST (15:27Z), window 88 min

- **Results first.** Unchanged:
  - 30 d: -7.38% [-12.8, -2.0] on 719 events;
  - 7 d: -6.20% [-16.8, +4.4] on 181;
  - gate: 13 of 800 (BC-053);
  - nothing open.
  - Orders today: 11, all filled.
- **ANOMALY: 3 endpoints over budget.**

  | endpoint | probe | server (web log) | budget |
  |---|---|---|---|
  | `live_today` | 5.39 s | 5,294 ms | 3.0 s |
  | `page` | 3.20 s | 3,104 ms | 3.0 s |
  | `settings` | 3.45 s | 285 ms | 2.0 s |

  - **Hypothesis, written first:** another web memory recycle, as at 00:33Z and 05:27Z.
    - **Falsified:** the web log has no recycle, no worker boot and no overlay rebuild in 15:26-15:28Z.
  - **What it was: host CPU load.** The load average rose from 3.4 (15 min) to 5.7-6.1 (1 min). The top CPU users at
    the read:
    - another lane's research replay, `/mnt/c/tmp/odds_lane_838/livewin.py`, at 86%. It finished before its nice
      value could be read; it belongs to `layer2-rail-monitor`'s #838 reading R-E.
    - `fetch_ncaaf_oddsapi_game_lines.py` at 80%;
    - `pipeline.board_build_process` at 66%;
    - `refresh_odds_sources.py` at 47%.
  - **Re-reads:** six, 10 s apart, gave 0.45-0.53 s, plus one at 2.88 s (load 5.6). So it is intermittent and follows
    host load.
  - **`settings` was the probe, not the server:**
    - 3.45 s on the client against 285 ms on the server, so the probe was starved.
    - The cause was this session's Idle fix (497a34c7d), which made the probe really run at Idle.
    - **Fixed (8506b7202):** the probe drops to Idle only after its timed fetches. Every earlier reading was timed at
      Normal, so the series stays comparable.
  - **Handoff:** `live_today` crossed the 5 s line set at Reading 86, so the reads go to the web owners in this
    ledger. This is not a fix for this lane.
    - Tally since 6 PM 11-19: **6 of 23 `live_today` reads above 2 s, 2 above 3 s.**
    - Causes: 2 on web memory recycles, 1 on host CPU load (this one), 3 not logged.
    - Owners: `web-silent-worker-kills` (memory growth) and `board-read-cold-share` (#853).
    - Host contention from research jobs is the runbook's "Research/test jobs at Idle / nice 19" rule.
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan: 31 suggested, 14 positions. The plan was 11.5 min old; max gap 13.1 min.
  - Live ticks: 1 placed on Polymarket.
  - Cap use: 4.8% Kalshi, 5.7% Polymarket.
  - A browser loaded `/portfolio` and logged in during the window (2 browser requests).

## Local Portfolio Watch, no credits (user, 11-20 ~9:55 AM CST: "make this dashboard self contained so it doesnt use up credits")

- **What spent credits:** the claude.ai dashboard's page never calls Claude. The cost was this session re-uploading its 3
  files and rewriting its datasets after every reading.
- **What replaces it:** the Windows task **`SyndicatePortfolioWatch`**.
  - It runs every 30 min at :04 and :34, keeping off the :07/:22/:37/:52 picks minutes. The user, Interactive logon,
    `conhost --headless`, so no window. IgnoreNew, a 15-min limit.
  - It runs `C:\tmp\pfmon\local_watch.py`:
    1. the probe from the main checkout (`--log-minutes 30`, read-only);
    2. `build_page_data.py`;
    3. `build_local_dashboard.py`, which writes **`C:\tmp\pfmon\page\dashboard.html`**, one file with its data
       inside (no network, reloads every 5 min, flags itself stale past 75 min);
    4. prunes the raw reading folders older than 48 h (40 removed at the first run, 510 MB to 326 MB).
  - Its log is `C:\tmp\pfmon\local_watch.log`.
  - Verified:
    - a manual run and a Task Scheduler run (09:59), every step rc 0;
    - rendered headless at 1280 px light and 390 px dark: 0 script errors and no horizontal scroll.
- **The claude.ai page** (https://claude.ai/artifact/BUBiY1Qd5EizqJJUGMmqGN) is no longer updated after each reading.
  It keeps its 9:27 AM data.

## Reading 104 — Fri 11-20 9:58 AM CST (15:58Z), by hand through the new runner

- **Results:** unchanged (30 d -7.38% on 719 events; gate 13 of 800).
- **ANOMALY: `live_today` 8.77 s** (server 8,627 ms at 15:58:36Z). This read was timed at Normal priority, so it is
  not the probe's starvation.
- **No recycle, boot or overlay line** in 15:56-15:59Z.
- **Host load 6.2** (15 min 4.5, rising), from the fleet's own morning builds:
  - `build_soccer_artifacts.py` ×2 (nice 0, ~100% each);
  - `build_college_pregame_sims.py` (nice 15, 129%);
  - a `find ~/syndicate-prod/data -maxdepth 4 -name *state*2026-11-2*` (nice 0, 88%);
  - `board_build_process` (67%).
- The task's own run at 09:59 read `live_today` inside budget.
- **Tally since 6 PM 11-19:** 7 of 25 `live_today` reads above 2 s, 3 above 3 s. Causes: 2 memory recycles, 2 host
  load (now the fleet's own workers, not only research jobs), 3 not logged.
- Added to the web owners' evidence. `web-silent-worker-kills` has the brief, and keeps the session open by the user's
  "Keep it open".

## Hourly loop stopped; a daily learning review replaces it (user, 11-20 ~10:15 AM CST: "stop the loop but you should be checking the dashboard to learn")

- **Loop:** the self-paced reading loop (`/loop` + ScheduleWakeup) is stopped. Numeric monitoring continues for free
  through the `SyndicatePortfolioWatch` task.
- **Daily review:** the scheduled task **`portfolio-learning-review`** runs at about 1:57 AM local (Bypass mode,
  inherited from this session). Each run:
  - reads the local dashboard's data;
  - writes the previous day's DAILY SUMMARY, performance first;
  - writes a "What the data teaches" block with exactly one pre-registrable optimization lead;
  - runs the dated study reads once each when due: S8 look 1 (after 11-23 9 AM) and look 2 (after 11-25 12:12 PM,
    then it disables `SyndicateS8Collector`), the S6 forward test at 150 events, the 11-24 check of the
    fill-quote-logging fields, and the S5 forward test at 150 events.
  - It never changes anything live and never edits lanes.md.
- **First learning pass, from the dashboard (11-20, 30 d):**
  - Nothing wins beyond noise. Seven slices lose beyond noise:
    - WNBA -35.6% (21 bets);
    - price 0.30-0.45 -12.7% [-23.9, -1.4] (315 / 206);
    - totals -12.5% [-24.0, -1.1] (400 / 309);
    - EV band 2-5 -10.4% [-18.0, -2.9] (1,016 / 536; predicted +4.1%);
    - the largest-stake quartile -9.2% [-16.7, -1.7] (64% of dollars);
    - the `model_edge` path -7.5%;
    - Kalshi -6.2%.
  - The dollars sit where the book does worst: the middle stake quartiles are -3% to -4%.
  - Under the per-line rule, the lead is what overstates edge in sizing and in the totals fair, not a totals
    exclusion.

## Portfolio Watch keeps full history (fleet-watcher's request, relaying the user ~10:50 AM CST: "pull in the history we already should have. I want all 3 of these available in one central dashboard hub")

- **The 48 h prune never touched the history.** It removes only the raw per-reading folders (each about 4.5 MB of
  response bodies). The reading log `C:\tmp\pfmon\readings\readings.jsonl` is never pruned and has every probe
  reading since 11-17 10:21 AM.
- **New: `C:\tmp\pfmon\build_history.py`, a durable daily rollup.**
  - Output: `C:\tmp\pfmon\history\daily_rollup.json`, a folder nothing prunes.
  - It is rebuilt every run from the fleet ledger, the newest saved `/api/portfolio/live?on=all&show=all`, which
    holds every live order since trading began. So it backfills to the **first graded live bet, 2026-08-06**: 106
    days, 64 with bets, 2,146 graded bets.
  - Each day carries:
    - that day's ROI with its event-clustered 95% range;
    - won vs breakeven, fees, and fee-net same-book CLV;
    - rolling 7-day and 30-day ROI ending that day, with ranges;
    - orders, filled and not filled;
    - from 11-17 on, the day's reading count, non-GATE anomalies and `live_today` reads above 2 s and 3 s.
  - It uses the same instrument as the probe (`live_book_edge_readout`). Its 11-19 30-day row is -7.38%
    [-12.79, -1.97], identical to the probe's. Percentages and counts only.
  - If the ledger cannot be read, the previous rollup is kept.
- **Dashboard:** a new "History since 2026-08-06" section.
  - It charts rolling 30-day ROI with its range and 7-day ROI. A point is plotted only when its window holds at least
    20 events (30-day) or 10 (7-day), because a one-bet 7-day ROI of +370% on 08-23 flattened the chart.
  - A table lists every trading day.
  - Rendered headless at 1280 px light and 390 px dark: 0 errors, no horizontal scroll, 64 rows.
- **Runner:** `local_watch.py` now runs the probe, page data, **history** and the dashboard, then the prune.
  Verified under Task Scheduler at 10:45 AM: every step rc 0.
- **The output path stays `C:\tmp\pfmon\page\dashboard.html`**, for the central hub
  (`C:\SyndicateProd\dashboards\index.html`, built by the fleet-watcher session).

## Portfolio Watch moves to durable paths and publishes to the fleet data root (fleet-watcher's request, relaying the user ~11:05 AM CST: "yes, open the lane and send the asks"; lane ops-dashboards-hub fd2c27f7b)

- **Code is versioned** in `scripts/portfolio_watch/` (3cb203107, fix 12136a4d0, 6 tests):
  - `paths.py`, `build_page_data.py`, `build_history.py`, `build_dashboard.py`, `run.py`.
- **Installed and run from `C:\SyndicateProd\portfolio_watch`** (out of C:\tmp, which a cleanup once wiped).
  - The reading log, the 8 newest reading folders, the durable `history\daily_rollup.json` and the findings register
    were copied there.
  - The old `C:\tmp\pfmon` copies are left in place.
  - The probe now writes its readings there (`--out-dir`).
- **Every run publishes the page atomically** (write `.tmp`, then rename) to three places:
  1. `C:\SyndicateProd\portfolio_watch\page\dashboard.html`;
  2. **`C:\tmp\pfmon\page\dashboard.html`**, unchanged, for the local hub;
  3. **the fleet data root `~/syndicate-prod/data/reports/portfolio_watch/index.html`**, for `/ops/dashboards`. This is
     the Rail Watch pattern; no service reads it until that route lands.
- **The task `SyndicatePortfolioWatch` now runs `C:\SyndicateProd\portfolio_watch\run.py`.**
  - Verified by a Task Scheduler run at 10:59 AM: every step rc 0, and the fleet copy was updated at 11:00 with the
    same md5 as the local copy.
- **A slip, caught and fixed:**
  - `paths.py` was first written through a shell heredoc that ate one of the two leading backslashes. The "fleet copy"
    went to `C:\wsl.localhost\...\index.html`, a stray 249 KB file on C:.
  - The runner logged only each step's last line, so it showed no failure.
  - Fixed: a forward-slash UNC path, a test that the target's drive is the WSL share, and the runner now logs every
    `FAILED` publish line.
  - **Removing the stray `C:\wsl.localhost` folder was refused by the safety check (a top-level folder on C:); it is
    left for the user.** It holds only that one file.
- **The daily learning review's prompt** now points at the durable paths and reads `daily_rollup.json` first.

## Portfolio Watch matches the original's detail (fleet-watcher's request, relaying the user ~11:30 AM CST: "make sure all 3 dashboards deliever the same level of detail as the original ones")

- **Compared against:** the original claude.ai page's code, read from its store (`files/index.html`, version 4,
  byte-identical to the last local copy).
- **Gaps found:**
  1. The two summary sentences: endpoints answered, live banner, open anomalies; 30-day ROI with its range, games and
     the count of signals beyond noise.
  2. The **Web worker kills** tile (`worker_timeouts` in the web-log window).
  3. Plan detail: board rows and sized.
  4. Paper detail: won and lost of settled, plus the "simulated" note.
  5. The banner's "stale after 900 s" note.
  6. The response-time chart on a **real time axis** with points, and every series against its budget in the tooltip.
  7. The money table's **window rows**, **Predicted EV %** and excess wins, plus its explanatory note.
  8. The findings table's **First seen** column, register order and note.
  9. The readings table: **every** reading (the local page showed the last 24) with **live ticks, placed, failed,
     refusals by reason** (price band / held on another slate / game started / other) and **both venue caps**.
  10. Per-section notes.
  11. **Sources** (each dataset's notes).
- **A bug found while comparing:** the local banner tile tested `banner_ok` as truthy, but the field is the string
  `"ok"`, so a non-ok banner would have shown OK. It now tests `=== "ok"`.
- **All of these are added** (8688f5ae7, `scripts/portfolio_watch/build_dashboard.py`, installed). The local page keeps
  what it already had beyond the original: yesterday and all-time tiles, the full history since 08-06, cap use and
  the S8 collector.
- **Verified:** rendered headless at 1280 px light and 390 px dark, 0 errors, no horizontal scroll.
  - Rows and columns: money table 42 × 11, findings 33 × 6, readings 111 × 18, sources 10 × 3, history 64 × 11.
  - The 9 status tiles are present.
  - All three outputs were rewritten (local `C:\tmp\pfmon\page\dashboard.html`, `C:\SyndicateProd\portfolio_watch\page`,
    fleet `reports/portfolio_watch/index.html`).
- Every 30-minute run of `SyndicatePortfolioWatch` uses the new builder.

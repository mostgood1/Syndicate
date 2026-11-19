# Findings 2026-11-19 -- what spaces live-odds-worker's odds-sweep launch attempts 1.5-5 min apart (lane `live-odds-loop-attempt-spacing`)

Read-only. The hypothesis was written into the lane (`17befde3f`) from the code alone, before any stage timing.
The user asked for this study ("Yes, read it") after the puck-drop study found the loop's attempt spacing was the largest part of the wait.

## The loop (`scripts/run_live_odds_refresh_worker.py` main, 2923-2986), one thread, serial

Each iteration runs these steps in order:

1. `_run_tick`: the soccer and WNBA autoruns, the in-play capture autoruns, then `_run_live_refresh_tick`, which launches the odds sweep. Logged as `tick_start` .. `tick_end`.
2. `run_disk_maintenance`.
3. `_polymarket_us_slate_refresh_tick`, single-flight against the venue-poll thread.
4. `_run_execution_tick`: balances, venue settlement, exits and placement.
5. `_ledger_rebuild_tick`.
6. Sleep 60 s while a game is live.

The worker logs `LIVE_ODDS_WORKER_MEMORY {"stage": ...}` at `loop_tick_begin`, `tick_start`, `tick_end` and `loop_sleep`. Those lines time every iteration.

## Verdicts

- **H1 SUPPORTED.** Most of an iteration outside the 60 s sleep is spent OUTSIDE the odds tick.
  - Live windows (00-05Z, nights 11-15..11-18), **482 iterations**:

    | part | share of loop time |
    |---|---|
    | sleep | 40.3% |
    | **post-tick work** | **44.8%** |
    | odds tick | 14.0% |
    | autoruns | 0.9% |

  - Inside the post-tick work:

    | part | share of loop time | p90 | max |
    |---|---|---|---|
    | **Polymarket US slate sweep, run on the main thread** | **25.9%** | 142 s | 233 s |
    | execution tick | 18.4% | 82 s | 262 s |
    | the rest | 0.5% | | |

  - **125 of 482** iterations had more than 120 s of post-tick work. The slate sweep is the larger part in **117** of them, the execution tick in 8.
- **The slate attribution is checked, not assumed.**
  - With no slate write before the execution tick's first line: tick end -> that line is p50 1 s, max 9 s (n 80).
  - With one: p50 146 s, min 92 s (n 107).
- **H2 FALSIFIED.** There is no second launcher: **482 of 482** live `ODDS_SWEEP_LAUNCHED` lines fall inside the main loop's odds tick (2,518 of 2,520 over all logged time). The launch "pairs" ~1.5 min apart are consecutive iterations.
- **Iteration length = the attempt spacing.** Iterations ran p50 100 s, p90 299 s, max 570 s, against the puck-drop study's attempt gaps of p50 93 s, p90 299 s.

## Why the main loop runs the slate sweep at all

- The slate writer is single-flight between two threads. The venue-poll thread calls it every 120 s, and the main loop calls it once per iteration. The sweep is gated to one every 180 s (`SLATE_INTERVAL_SECONDS`), and whichever thread finds it due does the whole 92-233 s sweep.
- In the live windows the main loop won **153 of 387** writes (40%). In each of those, the next odds sweep waited for it.
- The main-loop call sits before the execution tick on purpose: "so an order placed this pass is priced from the freshest slate this pass can get". `execute_portfolio` prices Polymarket orders off this artifact. The comment at `run_live_odds_refresh_worker.py:1731-1733` names a 3x price-age ceiling there; that ceiling was not read in code here.

## Counterfactual (same 482 iterations with parts subtracted; ignores knock-on effects)

| loop | p50 | p90 | max | iterations over 180 s |
|---|---|---|---|---|
| as measured | 100 s | 299 s | 570 s | 138 |
| without the main-loop slate sweep | 91 s | **170 s** | 413 s | **42** |
| also without the execution tick | 79 s | 102 s | 199 s | 1 |

## Levers (none built; each is a betting change: default-off, or the 11-24 window, put to the user)

1. **Keep the Polymarket slate sweep off the main loop.** The venue-poll thread already does 60% of writes. Either drop the main-loop call, or make it non-blocking.
   - Cost: an order placed in an iteration may be priced off a slate up to one interval older. Check the price-age ceiling in `execute_portfolio` before building.
   - Benefit: odds-sweep attempts p90 299 -> ~170 s, for every sport in the live lane.
2. **Run the execution tick on its own thread.** It reaches p90 ~102 s, but it changes the order of pricing and placement. A larger, riskier change.

## Coverage

- live-odds-worker logs 11-15 08:30Z .. 11-19 14:36Z: 2,734 iterations, 482 of them in the 00-05Z live windows of 4 nights.
- No manifests or data files were needed.
- Scratchpad `loopstages.py`.

## Raw output

```
events 26524: 11-15 08:30Z..11-19 14:37Z

== LIVE 00-05Z nights 11-15..11-18: 482 iterations ==
  pre    p50      1s p90      3s max      9s  share  0.9%
  tick   p50     17s p90     39s max    135s  share 14.0%
  post   p50      1s p90    214s max    461s  share 44.8%
  sleep  p50     60s p90     61s max     66s  share 40.3%
  ITERATION p50 100s p90 299s max 570s
  post.slate_s  p50     0s p90   142s max   233s  share of all time 25.9%  nonzero in 135
  post.exec_s   p50     0s p90    82s max   262s  share of all time 18.4%  nonzero in 187
  post.rest_s   p50     0s p90     2s max    14s  share of all time  0.5%  nonzero in 66
  iterations with post > 120 s: 125 of 482; of those with a SLATE write inside: 123; with execution markers: 112; slate is the larger part in 117; exec in 8; rest in 0
  ODDS_SWEEP_LAUNCHED in tick spans 482, outside 0
  POLYMARKET_US_SLATE_WRITE lines in window: 387; inside a main-loop post span: 153

== ALL logged iterations: 2735 iterations ==
  pre    p50      1s p90      2s max     67s  share  0.7%
  tick   p50     15s p90     43s max    186s  share 15.2%
  post   p50      2s p90    177s max    634s  share 38.8%
  sleep  p50     60s p90     61s max    426s  share 45.3%
  ITERATION p50 97s p90 255s max 838s
  post.slate_s  p50     0s p90   129s max   351s  share of all time 22.4%  nonzero in 641
  post.exec_s   p50     0s p90    59s max   305s  share of all time 15.3%  nonzero in 980
  post.rest_s   p50     1s p90     3s max    14s  share of all time  1.1%  nonzero in 2029
  iterations with post > 120 s: 541 of 2735; of those with a SLATE write inside: 534; with execution markers: 465; slate is the larger part in 511; exec in 30; rest in 0
  ODDS_SWEEP_LAUNCHED in tick spans 2518, outside 2
  POLYMARKET_US_SLATE_WRITE lines in window: 2170; inside a main-loop post span: 805

LONGEST 12 live iterations:
  11-18 01:32:04Z total   570 pre    2 tick   81 post  425 (slate  233 exec  191 rest    1) sleep  61
  11-19 00:59:13Z total   540 pre    1 tick   16 post  461 (slate  208 exec  252 rest    1) sleep  62
  11-17 00:50:21Z total   535 pre    8 tick   94 post  370 (slate  226 exec  142 rest    2) sleep  62
  11-19 00:38:44Z total   506 pre    3 tick   22 post  420 (slate  232 exec  188 rest    1) sleep  61
  11-18 02:05:52Z total   485 pre    3 tick   66 post  355 (slate  229 exec  126 rest    0) sleep  61
  11-18 02:28:04Z total   449 pre    5 tick   21 post  363 (slate  144 exec  218 rest    1) sleep  60
  11-18 02:35:33Z total   442 pre    1 tick   53 post  328 (slate  185 exec  141 rest    1) sleep  60
  11-17 00:59:16Z total   435 pre    3 tick   47 post  325 (slate  204 exec  121 rest    1) sleep  60
  11-18 02:15:23Z total   420 pre    2 tick   12 post  345 (slate  217 exec  128 rest    0) sleep  61
  11-18 01:19:44Z total   413 pre    5 tick   84 post  262 (slate    0 exec  262 rest    0) sleep  62
  11-17 00:43:31Z total   410 pre    1 tick   20 post  324 (slate  214 exec  110 rest    0) sleep  66
  11-19 00:13:17Z total   407 pre    1 tick   19 post  323 (slate  190 exec  132 rest    1) sleep  64

CONFOUND CHECK (live window): tick_end -> first BAL marker
  with a SLATE write before BAL: n 107 p50 146s p90 207s min 92s
  without:                       n 80 p50 1s p90 2s max 9s
  SLATE writes in live windows: 387; gaps between successive writes p50 173s

COUNTERFACTUAL iteration length, live window (same iterations, parts subtracted; ignores knock-on effects):
  as measured:            p50 100s p90 299s max 570s; over 180 s 138 of 482
  minus main-loop slate:  p50 91s p90 170s max 413s; over 180 s 42 of 482
  minus slate and exec:   p50 79s p90 102s max 199s; over 180 s 1 of 482
```

## Addendum 2026-11-19 ~10:05 AM CST -- the fix is on main, default off (todo #851, lane `polymarket-slate-off-odds-loop`)

- **On main `8f0d73a2e`.**
  - `SYNDICATE_POLYMARKET_SLATE_MAIN_LOOP_BACKGROUND`, absent = off = the inline call.
  - `_main_loop_polymarket_slate_step` starts a due sweep on a daemon thread, returns `in_flight` / `not_due` otherwise, and never pages the venue on the main thread.
- **Tests:** 22 new cases, all failing on the old code; 919 passed across the 42 test files that import the worker.
- **Not loaded.** It is a betting change: the 11-24 window, the user's decision.
- **Prediction P1-P5** is in the lane block and todo #851.

# Portfolio monitor — Thu 2026-11-19 (lane `portfolio-monitor`)

Continues `findings_2026-11-18_portfolio_monitor.md` (readings 25-60 and the 11-18 daily summary). Readings are of the
fleet (`http://127.0.0.1:10000`), read-only. Percentages and counts only: this repo is public.

## Reading 61 — Thu 11-19 12:18 AM CST (06:18Z), window 31 min

- **Results first. 11-18 is nearly settled:**
  - 11-18 ("yesterday" now): **63 bets / 33 events, ROI +2.97% [-26.1, +32.0]**, won 63.5% against breakeven 59.3%;
  - **30 d: 1,668 bets / 705 events, -7.18% [-12.6, -1.8]**;
  - 7 d: 396 bets / 177 events, -4.20% [-15.4, +7.0];
  - all-time: 2,089 bets, -10.88%;
  - fee-net CLV (30 d) -0.42 pp (se 0.21).
  - 3 games started and unsettled; the 11-18 DAILY SUMMARY waits for them.
- **New: 2 unclassified loads** (1 at the last reading).
  - *Hypothesis, written first:* a late-evening deploy by another lane not yet registered.
  - **Read:** `betting_change.py candidates` lists the soccer ff (17:58:30Z, known) and the **04:46:22Z ff +
    board-child TERM `a3104a5b6 -> 199d6c529`** (lane `layer2-suggested-grader`: the population recorder writes each
    line's first SUGGESTED sighting). Its own deploys.md entry says **"betting change: no"** (research records only).
    It is not yet in the register.
  - **Neither can move the gate's clock:** the soccer ff predates BC-052 (21:02:51Z), and the 04:46Z load is declared
    `no`. Both registrations are owed by their lanes.
- **No endpoint anomalies.** Every endpoint was inside budget: `live_all` 0.27 s, page 0.19 s.
- **Flow (the 11-19 board):**
  - plan 0.3 min old: 36 suggested, 14 positions;
  - 10 live ticks, 2 placed (3 `already_held_other_slate`);
  - orders today 2, both submitted 2.5 min ago (unreconciled 2, inside the grace);
  - cap use 0.0% / 1.6%.
- **Gate:** 12 of 800 events (18 bets) on the BC-052 clock.

## Reading 62 — Thu 11-19 12:59 AM CST (06:59Z), window 42 min

- **11-18 has fully settled** (0 started and unsettled): 66 bets / 33 events, +3.90% [-23.3, +31.1]. The DAILY SUMMARY
  for 11-18 is written in `findings_2026-11-18_portfolio_monitor.md`.
  - 30 d: 1,671 bets / 705 events, -7.15% [-12.6, -1.7].
  - 7 d: -3.96% [-15.0, +7.1].
  - The 8 signals are unchanged.
- **No new anomaly.** The same 2 unclassified loads as reading 61, owed by their lanes; neither can move the clock.
  - Endpoints: `live_today` 0.91 s, page 0.16 s.
- **Flow (11-19 board):**
  - plan 2.8 min old: 35 suggested, 16 positions;
  - 12 live ticks, 2 placed (9 `maker_pilot_held`, 6 `axis_held_live`, known guards);
  - orders today 4: 2 filled and 2 maker-pilot posts resting (36 / 27 min, exempt until kickoff); unreconciled 0;
  - cap use 7.6% / 0.8%.
- **Gate:** 12 of 800 events (21 bets) on the BC-052 clock.
- **Pace:** no games until the afternoon; readings go hourly or slower overnight.

## Reading 63 — Thu 11-19 2:00 AM CST (08:00Z), window 61 min

- **Results first.** No change overnight: 30 d -7.15% [-12.6, -1.7] on 705 events; 11-18 +3.90%; nothing open.
- **No new anomaly.** Every endpoint was inside budget: `live_today` 0.86 s, page 0.62 s. The same 2 unclassified
  loads, owed by their lanes.
- **Flow (11-19 board):**
  - plan 0.2 min old: 47 suggested, 20 positions, ceiling used 52.7%;
  - 20 live ticks, 1 placed, 0 failed (known guards: `already_held_other_slate`, `axis_held_live`,
    `maker_pilot_held`);
  - orders today 5: 3 filled and 2 maker-pilot posts resting (96 / 88 min, exempt until kickoff); unreconciled 0;
  - cap use 7.6% / 1.7%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 64 — Thu 11-19 3:00 AM CST (09:00Z), window 60 min

- **Results first.** Unchanged overnight: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **No new anomaly.** Every endpoint was inside budget: `live_today` 0.53 s, page 0.34 s. The same 2 unclassified
  loads, owed by their lanes.
- **Flow (11-19 board):**
  - plan 0.6 min old: 34 suggested, 17 positions;
  - 22 live ticks, 3 placed, 0 failed (`already_held_other_slate` x 11, a known guard);
  - orders today 8: 6 filled and 2 maker-pilot posts resting (156 / 148 min, exempt until kickoff); unreconciled 0;
  - cap use 7.6% / 4.6%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 65 — Thu 11-19 4:00 AM CST (10:00Z), window 60 min

- **Results first.** Unchanged overnight: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **No new anomaly.** Every endpoint was inside budget: page 1.22 s (the slowest overnight), `live_all` 0.84 s. The same
  2 unclassified loads, owed by their lanes.
- **Flow (11-19 board):**
  - plan 1.7 min old: 42 suggested, 15 positions;
  - 18 live ticks, 1 placed, 0 failed;
  - orders today 9: 7 filled and 2 maker-pilot posts resting (216 / 208 min, exempt until kickoff); unreconciled 0;
  - cap use 7.6% / 5.6%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 66 — Thu 11-19 5:00 AM CST (11:00Z), window 60 min

- **Results first.** Unchanged overnight: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **No new anomaly.** Every endpoint was inside budget: `live_today` 0.19 s, page 0.53 s, books 0.55 s. The same 2
  unclassified loads, owed by their lanes.
- **Flow (11-19 board):**
  - plan 2.4 min old: 53 suggested, 17 positions (max gap 14.5 min over 6 h);
  - 20 live ticks, 4 placed, 0 failed;
  - orders today 13: 11 filled and 2 maker-pilot posts resting (276 / 268 min, exempt until kickoff); unreconciled 0;
  - cap use 9.0% / 6.7%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 67 — Thu 11-19 6:00 AM CST (12:00Z), window 60 min

- **Results first.** Unchanged overnight: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **NEW anomaly: Polymarket's live plan has 0 placeable rows. All 329 are refused `aggregator_priced`** (4 AM: 137 of
  444, 3 positions).
  - *Hypothesis, written first:* Polymarket's own quotes went stale or missing, so every row fell back to an
    aggregator price.
  - **Confirmed, and the cause is upstream of the join:**
    - `[live_odds_worker] POLYMARKET_DAILY_BOOK` went from **91 unpriced of 16,258 listed (11:08:32Z) to 16,792 of
      16,797 (11:19:37Z)**. It has stayed there since: 16,925 of 16,929 at 11:59:47Z.
    - Sampled moneyline shapes show `prices='["0","0"]'` (`[polymarket_us_markets] MONEYLINE_YES_LEG_SHAPE`).
    - The board join still matches 488 rows (`POLYMARKET_BOARD_JOIN ... matched=488`), but with no venue price;
      `PAPER2_PLAN_WRITTEN ... venue_priced=0 feed=venue_feed`.
    - `LIVE_PLAN_WRITTEN venue=polymarket` placeable went 14 (11:07:39Z) -> 4 (11:14:36Z) -> **0 (11:18:13Z)**.
  - **First time in the logs on disk (11-15 onward):** 19 runs with > 1,000 unpriced, all since 11:14:05Z.
  - **Only the prices are zero:**
    - balances (`VENUE_BALANCES polymarket=ok`), order reads, settlement reads and the catalogue all work;
    - the market list still grows (16,258 -> 16,929);
    - `outcomePrices` reads "0".
    - That points at Polymarket's side (an outage or a change in the price field), not at our join.
  - **It fails safe:** no order can be priced from a zero, so Polymarket places nothing (`EXECUTION ... placed=0`).
    Existing positions and Kalshi are unaffected.
  - **F21, owner: none open** (`polymarket_us_markets` was held by `live-venue-order-placement`, closed). Watched each
    reading. If it is still out by midday CST, Polymarket will place nothing on tonight's slate; the user is told
    then. A code fix, if the price field moved, gets its own lane.
- **Other flow:**
  - `live_all` 2.28 s (inside its 5 s budget);
  - plan 0.1 min old: 54 suggested, 17 positions (all Kalshi);
  - orders today 15: 14 filled, 1 maker post resting (336 min);
  - cap use 10.0% / 6.7%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 68 — Thu 11-19 6:33 AM CST (12:33Z), window 33 min

- **Results first.** Unchanged: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **F21 (Polymarket zero prices): still out, 1 h 19 min.**
  - `POLYMARKET_DAILY_BOOK` at 12:32:57Z: 17,010 unpriced of 17,012 listed. It now runs about every 2.5 min (it ran
    about every 10 min before the outage).
  - Polymarket live plan: 306 rows, **0 placeable**, all `aggregator_priced`.
  - Execution placed 0 on Polymarket with 0 refusals (nothing reached it). Kalshi is unaffected: 20 placeable, 5
    positions, 2 placed this window.
  - The midday check stands: if it is still out at noon CST, the user is told that Polymarket sits out tonight's
    slate.
- **No other anomaly.** Every endpoint was inside budget: `live_today` 0.17 s, page 0.11 s.
- **Flow:**
  - plan 2.6 min old: 61 suggested, 17 positions;
  - orders today 17: 16 filled, 1 maker post resting (369 min);
  - cap use 11.5% / 6.7%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 69 — Thu 11-19 7:04 AM CST (13:04Z), window 31 min

- **Results first.** Unchanged: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **F21 (Polymarket zero prices): still out, 1 h 50 min.**
  - At 13:03:39Z, 17,067 of 17,069 markets are unpriced.
  - Polymarket's live plan: 304 rows, 0 placeable.
  - Kalshi is unaffected: 31 placeable, 5 positions, 1 placed this window.
- **Marginal anomaly: `live_today` 3.05 s (budget 3.0).**
  - *Hypothesis, written first:* an F14 web recycle.
  - **Wrong:** no recycle and no worker boot in 13:02-13:05Z. The request itself took 2,996 ms server-side
    (13:04:10.05Z), and no other request of 500 ms or more overlapped it.
  - A single marginal slow read with no cause found. Read again only if it repeats.
- **Flow:**
  - plan 0.3 min old: 78 suggested, 14 positions;
  - orders today 18: 17 filled, 1 maker post resting (400 min);
  - cap use 12.6% / 6.7%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 70 — Thu 11-19 7:36 AM CST (13:36Z), window 32 min

- **Results first.** Unchanged: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **F21 RESOLVED by itself (no deploy). Polymarket prices came back between 13:07:17Z and 13:09:45Z.**
  - `POLYMARKET_DAILY_BOOK` unpriced over the recovery:
    - 17,077 of 17,079 (13:07:17Z);
    - 10,037 of 16,879 (13:09:45Z);
    - 1,741 (13:12:26Z);
    - 680 of 16,625 (13:34:16Z).
  - The Polymarket live plan was back to **19 placeable, 4 positions at 13:12:04Z**. Now: 20 placeable, 7 positions;
    2 placed this window.
  - **Outage: 11:14:05Z -> ~13:09Z, about 1 h 55 min (5:14 -> 7:09 AM CST).** No game was in play and the 11-19 slate
    starts in the evening, so the cost was a pre-game window with 0 Polymarket placements. Nothing was mis-priced or
    mis-placed.
  - **Residue to watch:** 680 unpriced against about 90 before the outage, and still falling.
- **Probe fixed (lane `portfolio-monitor`):** `portfolio_monitor_probe.py` now raises **`VENUE FEED <venue>: live
  plan has 0 placeable of N rows, all aggregator_priced`**.
  - It fires for a venue with live execution ticks whose plan has >= 50 rows, 0 placeable and every refusal
    `aggregator_priced`. Novig and ProphetX, aggregator-priced by design, are excluded.
  - The outage raised no anomaly before this; it was caught by reading the plan line.
  - **Replayed on this morning's saved readings:** it fires on exactly the 3 outage readings (12:00, 12:33, 13:04Z)
    and on none of 10:00, 11:00 or 13:36Z.
  - Test added; 21 of 21 pass.
- **No anomaly.** Every endpoint was inside budget: `live_today` 0.19 s, page 0.20 s.
- **Flow:**
  - plan 1.0 min old: 80 suggested, 14 positions;
  - 12 live ticks, 5 placed, 0 failed;
  - orders today 23: 22 filled, 1 maker post resting (432 min);
  - cap use 14.9% / 7.3%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 71 — Thu 11-19 8:37 AM CST (14:37Z), window 61 min

- **Results first.** Unchanged: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **Program since reading 70:** S6 (adverse selection) has run (F22).
  - No entry feature separates the losing orders; the frozen filter is in effect a price cut, TEST D +2.01 pp
    [-0.85, +4.88].
  - The forward test (orders from 11-20, first 150 games, about 11-22/23) decides; the monitor runs it.
  - The fill-time and quote-at-submit logging is mapped and waits on the user approving a loan of
    `execution_ledger.py` / `execute_portfolio.py` from the quiet lane `paper-alongside-live`.
- **No anomaly.** Every endpoint was inside budget: `live_today` 0.34 s, page 0.23 s. The new `VENUE FEED` check is
  quiet.
- **F21 aftermath:** Polymarket is healthy. Its live plan has 18 placeable of 551 rows and 7 positions.
- **Flow:**
  - plan 8.3 min old: 67 suggested, 15 positions;
  - 18 live ticks, 5 placed, 0 failed. `outside_price_band` refusals ran 74 over the window: a known guard, more
    positions mean more checks;
  - orders today 28: 27 filled, 1 maker post resting (493 min);
  - cap use 17.2% / 8.1%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 72 — Thu 11-19 9:37 AM CST (15:37Z), window 75 min

- **Results first.** Unchanged: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **Built since reading 71: fill-quote logging (lane `fill-quote-logging`, user-approved loan), on main `3d636d88e`.**
  - Live rows will carry `venue_quote_at_submit` (Kalshi two-sided plus size at the touch; Polymarket's slate quote)
    and `venue_filled_at`.
  - Not a betting change. It loads at the next role restart (the 11-24 window at the latest) and is verified on the
    first live fills.
- **No anomaly.** Every endpoint was inside budget: page 0.61 s, `live_today` 0.39 s.
- **Checked, not an anomaly:** Polymarket's live plan is 309 rows / 4 placeable (551 / 18 an hour ago), and Kalshi
  has 37 `aggregator_priced` (2-6 usual).
  - The F21 shape was checked first. Polymarket's feed is healthy: 164 unpriced of 16,896 at 15:36:47Z, the
    post-outage residue of 680 now near the ~90 baseline.
  - The board join matched 454-480 markets.
  - The row counts follow the board (4,858 rows now against 5,192 an hour ago).
- **Flow:**
  - plan 3.1 min old: 48 suggested, 18 positions;
  - 26 live ticks, 7 placed, 0 failed;
  - orders today 33: 32 filled, 1 maker post resting (553 min);
  - cap use 19.1% / 8.3%.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 73 — Thu 11-19 10:37 AM CST (16:37Z), window 60 min

- **Results first.** Unchanged: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **Anomaly: `live_today` 6.73 s (budget 3.0)**, server-side 6,649 ms. It is the second slow read of this endpoint
  today (7:04 AM: 2,996 ms, cause not found), so it was investigated.
  - *Hypotheses, written first:* (1) an F14 web recycle; (2) else the request itself stalls on what it reads.
  - **Found: a collision with the cheat-sheet picks client.**
    - `POST /api/intelligence/query` (script client, **4.2 MB response, 6,813 ms**) finished at 16:37:08.7Z.
    - The probe's `/api/portfolio/live` started then and finished at 16:37:14.8Z (6,649 ms).
    - Then pid 978464 soft-recycled (736 MB, 15 requests), and pid 983801 hit its HARD limit at **1,056 MB after 1
      request** (limit 648) and was deferred by the hold.
  - The picks client is the Windows task `SyndicateCheatSheetPicks`, every 15 min at :07 / :22 / :37 / :52 CST
    (`web-silent-worker-kills` identified it as the 4,906-row client).
  - **My readings had drifted onto :37**, so the probe itself was colliding. The 7:04 AM read does not fit this (no
    picks run, no overlap) and stays unexplained.
  - **Fixes:**
    - The probe moves off the picks minutes (next reading about :45). Nothing to change on the fleet from here.
    - F14 updated: a single picks query takes a worker past 1 GB, and any portfolio read in that minute pays for
      it.
- **Flow:**
  - plan 0.8 min old: 47 suggested, 15 positions;
  - 19 live ticks, 3 placed, 0 failed;
  - orders today 36: 35 filled, 1 maker post resting (613 min);
  - cap use 20.0% / 9.4%;
  - Polymarket 5 placeable of 319.
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 74 — Thu 11-19 11:34 AM CST (17:34Z), window 57 min

- **Results first.** Unchanged: 30 d -7.15% [-12.6, -1.7] on 705 events; nothing open.
- **No anomaly.** Taken off the picks minute (:34 instead of :37): `live_today` 0.17 s, page 0.20 s, every endpoint
  inside budget.
- **Flow:**
  - plan 0.6 min old: 74 suggested, 6 positions; 48 `beyond_max_positions`;
  - 20 live ticks, 3 placed, 0 failed;
  - orders today 39: 38 filled, 1 maker post resting (670 min);
  - cap use 20.4% / 11.5%;
  - Polymarket 13 placeable of 519 (feed healthy).
- **Gate:** 12 of 800 events on the BC-052 clock.

## Reading 75 — Thu 11-19 12:37 PM CST (18:37Z), window 66 min

- **Results first.**
  - 30 d: -7.15% [-12.6, -1.7] on 705 events, unchanged. Fees are 3.87% of stake.
  - Last 7 d: -3.96% [-15.0, +7.1] on 177 events. Won 60.1% against a 60.1% breakeven.
  - Yesterday: +3.9% [-23.3, +31.1] on 33 events.
  - CLV over 30 d, net of fees: -0.42 pp (se 0.21).
- **Gate clock reset:**
  - BC-053 loaded at 11:00 AM: board child memory (todo #850).
  - It went in outside a window under the broken-money-path exception (user, 11-19 midday).
  - The gate now stands at 0 of 800 events, against 12 on the BC-052 clock at Reading 74.
- **Did BC-053 do what it was for?** The plan cadence it was meant to restore is back:
  - 56 plan writes in 6 h;
  - the largest gap is 15.4 min, against up to 26 min on the 11-18 evening.
- **No new anomaly.**
  - Every endpoint is inside its budget. `live_all` took 3.72 s against a 5.0 s budget (read at :37, the picks minute).
  - The probe's GATE line is the same 2 unclassified loads the digest lists. Other lanes owe those.
- **Flow:**
  - Plan 3.2 min old: 80 suggested, 13 positions (6 at Reading 74). 53 refused as `beyond_max_positions`.
  - Live ticks: 10 on Kalshi and 10 on Polymarket, 0 placed. All 60 refusals are `outside_price_band` (also seen 11-18).
  - Orders today: 39, of which 38 filled and 1 maker post still resting (734 min).
  - Cap use: 20.4% Kalshi, 11.5% Polymarket.
  - Polymarket: 14 placeable of 560 rows, so its feed is healthy.

## Reading 76 — Thu 11-19 1:31 PM CST (19:31Z), window 54 min

- **Results first.**
  - Unchanged, because nothing has settled since Reading 75.
  - 30 d: -7.15% [-12.6, -1.7] on 705 events.
  - 7 d: -3.96% [-15.0, +7.1] on 177 events.
  - Gate: 0 of 800 on the BC-053 clock.
- **No new anomaly.** All endpoints are fast (`live_all` 0.25 s against 3.72 s at the :37 read). The GATE line is the
  same 2 unclassified loads.
- **Flow:**
  - Plan 0.7 min old: 56 suggested, 10 positions. 58 plan writes in 6 h, max gap 15.4 min.
  - Live ticks: 8 Kalshi and 8 Polymarket; 1 placed on Kalshi. The 31 refusals are all `outside_price_band`.
  - Orders today 40: 39 filled, 1 maker post resting (787 min).
  - Cap use: 20.8% Kalshi, 11.5% Polymarket.
  - Polymarket placeable: 3 of 384 rows (162 `aggregator_priced`, not all).

## Reading 77 — Thu 11-19 2:31 PM CST (20:31Z), window 60 min

- **Results first.**
  - Unchanged, because nothing has settled.
  - 30 d: -7.15% [-12.6, -1.7] on 705 events.
  - 7 d: -3.96% [-15.0, +7.1] on 177 events.
  - Gate: 0 of 800 (BC-053 clock).
- **No new anomaly.**
  - Every endpoint returned in 0.3 s or less.
  - The GATE line is the same 2 unclassified loads.
  - One `in_play_market_fair` refusal appeared (a game is in play), which is expected.
- **Flow:**
  - Plan 0.4 min old: 55 suggested, 14 positions. 59 writes in 6 h, max gap 15.4 min.
  - Live ticks: 10 Kalshi and 10 Polymarket; 1 placed on Kalshi. The 30 refusals are all `outside_price_band`.
  - Orders today 41: 40 filled, 1 maker post resting (847 min).
  - Cap use: 21.2% Kalshi, 11.5% Polymarket.
  - Polymarket placeable: 6 of 367 rows.

## Reading 78 — Thu 11-19 3:31 PM CST (21:31Z), window 60 min

- **Results first.**
  - Unchanged, because nothing has settled.
  - 30 d: -7.15% [-12.6, -1.7] on 705 events.
  - 7 d: -3.96% [-15.0, +7.1] on 177 events.
  - Gate: 0 of 800 (BC-053 clock).
- **No new anomaly.** Every endpoint returned in 0.3 s or less. The GATE line is the same 2 unclassified loads.
- **Flow:** tonight's slate is filling.
  - Plan: 90 suggested, 14 positions. 63 refused as `beyond_max_positions`.
  - Live ticks: 6 placed (3 Kalshi, 3 Polymarket) in 20.
  - Orders today: 47 (41 at Reading 77). 46 filled, 1 maker post resting (907 min).
  - Cap use: 22.7% Kalshi, 12.7% Polymarket.
  - Polymarket placeable: 14 of 519 rows.
  - 61 plan writes in 6 h, max gap 15.4 min.

## Reading 79 — Thu 11-19 4:31 PM CST (22:31Z), window 60 min

- **Results first.**
  - Unchanged, because nothing has settled.
  - 30 d: -7.15% [-12.6, -1.7] on 705 events.
  - 7 d: -3.96% [-15.0, +7.1] on 177 events.
  - Gate: 0 of 800 (BC-053 clock).
- **No new anomaly.** Every endpoint returned in 0.3 s or less. The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 2.7 min old: 103 suggested, 10 positions. 76 refused as `beyond_max_positions`.
  - Live ticks: 3 placed (2 Kalshi, 1 Polymarket) in 18.
  - Orders today: 50 (47 at Reading 78). 49 filled, 1 maker post resting (967 min).
  - Cap use: 25.0% Kalshi, 13.6% Polymarket.
  - Placeable: Polymarket 14 of 510 rows, Kalshi 34 of 1,010.
  - 65 plan writes in 6 h, max gap 15.4 min.

## Reading 80 — Thu 11-19 5:31 PM CST (23:31Z), window 60 min

- **Results first.**
  - Nothing graded yet tonight.
  - 30 d: -7.15% [-12.6, -1.7] on 705 events.
  - 7 d: -3.96% [-15.0, +7.1] on 177 events.
  - Gate: 0 of 800 (BC-053 clock).
  - 2 games have started and are unsettled; none is late.
- **No new anomaly.**
  - Every endpoint returned in 0.31 s or less.
  - The plan was 8.8 min old at the read, because the planner was writing 11-20 at 23:27Z. Max gap tonight 10.7 min.
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan: 105 suggested, 12 positions.
  - Live ticks: 2 placed (1 Kalshi, 1 Polymarket) in 20.
  - Orders today: 52. 51 filled, 1 maker post resting (1,027 min).
  - Cap use: 25.2% Kalshi, 14.4% Polymarket.
  - Kalshi plan rows fell to 483 (1,010 at Reading 79) as games start.

## Reading 81 — Thu 11-19 6:02 PM CST (00:02Z), window 31 min

- **Results first.**
  - Nothing graded yet tonight.
  - 30 d: -7.15% [-12.6, -1.7] on 705 events.
  - 7 d: -3.96% [-15.0, +7.1] on 177 events.
  - Gate: 0 of 800 (BC-053 clock).
  - 5 games have started and are unsettled; none is late.
- **No new anomaly.**
  - Every endpoint returned in 0.28 s or less.
  - First sighting in these readings of the `no_model_edge_pct` refusal: 1 of 100 plan rows (1 Kalshi, 1 Polymarket).
    It is an existing planner refusal (`portfolio_commit` / `layer2_board.py:3413`, in the code since 09-10), not a new
    code path.
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 3.6 min old: 100 suggested, 10 positions.
  - Live ticks: 1 placed on Kalshi in 10.
  - Orders today: 53. 52 filled, 1 maker post resting (1,058 min).
  - Cap use: 26.3% Kalshi, 14.4% Polymarket.
  - Placeable: Polymarket 17 of 576 rows, Kalshi 32 of 1,077.
  - Plan max gap 10.8 min.

## Reading 82 — Thu 11-19 6:33 PM CST (00:33Z), window 31 min

- **Results first.**
  - Nothing graded yet tonight.
  - 30 d: -7.15% [-12.6, -1.7] on 705 events.
  - 7 d: -3.96% [-15.0, +7.1] on 177 events.
  - Gate: 0 of 800 (BC-053 clock).
  - 17 games have started and are unsettled; none is late.
- **Slower but inside budget (watch item, not an anomaly):**
  - `live_today` 2.05 s of a 3.0 s budget (0.23 s at Reading 81).
  - `page` 1.56 s of 3.0 s; `live_all` 1.66 s of 5.0 s.
  - The web log agrees: `/api/portfolio/live` took 2,022 ms server-side.
  - The read landed on a plan write (00:33:07Z) at tip-off for 17 games. Hypothesis: transient load at slate start.
    Re-checked at Reading 83. If it is still above 1.5 s off a plan write, it gets diagnosed.
- **Flow:**
  - Plan 1.1 min old: 41 suggested, 17 positions.
  - 5 rows refused `in_play_market_fair` (games started); 2 rows `no_model_edge_pct`.
  - Live ticks: 3 placed (1 Kalshi, 2 Polymarket) in 10. Kalshi also refused 5 as `game_started`.
  - Orders today: 56. 55 filled, 1 maker post resting.
  - Cap use: 26.8% Kalshi, 16.1% Polymarket.

## Reading 83 — Thu 11-19 7:03 PM CST (01:03Z), window 30 min

- **Results first.**
  - Nothing graded yet tonight.
  - 30 d: -7.15% [-12.6, -1.7] on 705 events.
  - 7 d: -3.96% [-15.0, +7.1] on 177 events.
  - Gate: 0 of 800 (BC-053 clock).
  - 17 games have started and are unsettled; none is late.
- **Reading 82's watch item is closed as transient.**
  - `live_today` is 0.31 s (2.05 s at Reading 82), `page` 0.27 s, `live_all` 0.41 s.
  - The tip-off hypothesis holds: one slow read at slate start, not repeated 30 min later off a plan write.
- **No new anomaly.** The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 3.3 min old: 119 suggested, 9 positions. 86 refused as `beyond_max_positions`; 5 rows `in_play_market_fair`.
  - Live ticks: 0 placed in 10. The 16 refusals are all `outside_price_band`.
  - Orders today: 56, unchanged.
  - Cap use: 26.8% Kalshi, 16.2% Polymarket.
  - Plan max gap 14.4 min.

## Reading 84 — Thu 11-19 7:32 PM CST (01:32Z), window 30 min

- **Results first.**
  - The first of tonight's games have graded: all-time is now 2,094 bets / 1,128 events, -10.82% (2,092 / 1,126,
    -10.85% at Reading 83).
  - The 7 d and 30 d windows end at yesterday, so they are unchanged: 30 d -7.15% [-12.6, -1.7] on 705 events.
  - Gate: 0 of 800 (BC-053 clock).
  - 43 games have started and are unsettled; none is late.
- **No new anomaly.**
  - Today's maker post (resting about 1,120 min) ended `rejected` at kickoff. This is the known kickoff-expiry
    pattern from 11-17 (`venue_canceled`), not a failure. Resting is now 0.
  - Every endpoint returned in 0.41 s or less. The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 2.0 min old: 209 suggested. 132 rows refused `in_play_market_fair` (games in play), and the sim edge share
    fell to 0.24 for the same reason. 12 positions.
  - Live ticks: 0 placed in 6 (11 `outside_price_band`, 3 `game_started`).
  - Orders today: 56. 55 filled, 1 maker expiry.
  - Cap use: 23.0% Kalshi dollars (the expiry released its room), 16.2% Polymarket.

## Reading 85 — Thu 11-19 8:02 PM CST (02:02Z), window 30 min

- **Results first.** One more 11-18 bet graded (a late finish), which moved yesterday and the windows slightly:
  - Yesterday: 67 bets / 34 events, +4.32% [-22.5, +31.1]. Won 65.7% against a 60.5% breakeven.
  - 7 d: -3.88% [-14.9, +7.2] on 178 events.
  - 30 d: -7.14% [-12.6, -1.7] on 706 events.
  - All-time: 2,095 / 1,129, -10.81%.
  - CLV over 30 d, net of fees: -0.41 pp (se 0.21) on 610.
  - Gate: 0 of 800 (BC-053 clock).
  - 45 games are in play; none is late.
- **No new anomaly.**
  - Every endpoint is inside budget, a little slower at the evening peak: `live_today` 0.56 s, `page` 0.75 s, `live_all` 0.72 s.
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 4.8 min old: 187 suggested, 10 positions; 92 rows refused `in_play_market_fair`.
  - Live ticks: 0 placed in 10 (19 `outside_price_band`, 17 `game_started`).
  - Orders today: 58. 57 filled, 1 maker expiry.
  - Cap use: 27.3% Kalshi, 16.0% Polymarket.
  - Placeable: Kalshi 50 of 755 rows, Polymarket 41 of 460.

## Reading 86 — Thu 11-19 8:31 PM CST (02:31Z), window 30 min

- **Results first.**
  - Unchanged since Reading 85: 30 d -7.14% [-12.6, -1.7] on 706 events; 7 d -3.88% [-14.9, +7.2] on 178.
  - Gate: 0 of 800 (BC-053 clock).
  - 47 games are in play; none is late.
- **ANOMALY (new tonight): `live_today` 3.20 s against a 3.0 s budget.** The server logged 2,872 ms for
  `GET /api/portfolio/live` at 02:31:11Z.
  - Hypothesis, written before testing:
    - (a) the endpoint's cost scales with open in-play positions (47 games); or
    - (b) contention in the web worker that served it.
    - Falsifier: if (a), repeat reads stay slow; if (b), they are intermittent.
  - **Result: intermittent, so (a) is falsified.**
    - Six re-reads 10 s apart (02:31:39-02:32:30Z, same 47 games, host load 2.3-3.2): 0.14-0.22 s.
    - The server logged 126-198 ms for them.
  - **The earlier slow read is explained.** Reading 82 (00:33:12Z, 2,022 ms) landed on worker 1147878:
    - it booted at 00:31:37Z after a `WEB_WORKER_MEMORY_RECYCLE` (anon 1,146 MB against a 633 MB limit), so it was
      about 95 s old;
    - an in-process `COMBINED_BOARD_OVERLAY_WARMED` rebuild ran over the request (`build_s=56.79`, finished
      00:33:34Z);
    - that worker was itself recycled at 00:34:08Z (150 s old, 862 MB).
  - **This read is not explained.** Between 02:25 and 02:39Z the web log has no recycle, no worker boot and no
    overlay line. It stays a single unexplained 2.9 s read.
  - **Owner:** lane `board-read-cold-share` (todo #853, `findings_2026-11-19_board_read_cold_share.md`).
    - It measured the same mechanism: per-process combined-board rebuilds and cold reads after memory recycles.
    - Its fix is on main, default-off, queued as CHANGE F of the 11-24 batch.
    - Nothing to fix from this lane. Over the last 3 h the web log shows 319 overlay rebuilds, median 10.0 s,
      max 68.7 s.
  - **Watch:** 2 of 11 portfolio reads tonight were above 2 s. If one goes over 5 s, or 3 or more of 6 reads in a
    window exceed the budget, it goes to that lane with the reads.
- **Flow:**
  - Plan 2.0 min old: 135 suggested, 12 positions; 46 rows refused `in_play_market_fair`.
  - Live ticks: 0 placed in 10.
  - Orders today: 58. 57 filled, 1 maker expiry.
  - Cap use: 27.3% Kalshi, 16.0% Polymarket.

## Reading 87 — Thu 11-19 8:56 PM CST (02:56Z), window 25 min

- **Results first.**
  - The gate clock has started: **2 of 800 events** on BC-053 (the first bets placed after 11:00 AM have graded).
  - Yesterday: 68 bets / 34 events, +4.65% [-21.9, +31.2]. Won 66.2% against a 60.4% breakeven.
  - 7 d: -3.81% [-14.8, +7.2] on 178 events.
  - 30 d: -7.13% [-12.6, -1.7] on 706 events.
  - All-time: 2,101 / 1,133, -10.82%.
  - CLV over 30 d, net of fees: -0.41 pp (se 0.21) on 611.
  - 42 games are in play; none is late.
- **No new anomaly.**
  - `live_today` 0.47 s. The web log's 8 live reads in the window include Reading 86's 2,872 ms and its six
    re-reads; the median is 172 ms.
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 1.8 min old: 130 suggested, 12 positions; 36 rows refused `in_play_market_fair`.
  - Live ticks: 0 placed in 10.
  - Orders today: 58. 57 filled, 1 maker expiry.
  - Cap use: 27.2% Kalshi, 16.0% Polymarket.

## Reading 88 — Thu 11-19 9:27 PM CST (03:27Z), window 31 min

- **Results first.**
  - Gate: **5 of 800 events** (7 bets) on BC-053.
  - All-time: 2,109 / 1,137, -10.79% (2,101 / 1,133, -10.82% at Reading 87). Tonight's grades are coming in
    slightly better than the book's average.
  - 30 d: -7.13% [-12.6, -1.7] on 706 events.
  - 7 d: -3.81% [-14.8, +7.2] on 178.
  - 36 games are in play; none is late.
- **No new anomaly.** Every endpoint returned in 0.41 s or less (`live_today` 0.38 s). The GATE line is the same 2
  unclassified loads.
- **Flow:**
  - Plan 4.0 min old: 88 suggested, 15 positions; 25 rows refused `in_play_market_fair`.
  - Live ticks: 0 placed in 9.
  - Orders today: 58. 57 filled, 1 maker expiry.
  - Cap use: 27.1% Kalshi, 16.0% Polymarket.

## Reading 89 — Thu 11-19 9:57 PM CST (03:57Z), window 30 min

- **Results first.** Tonight's slate is mostly graded.
  - Gate: **8 of 800 events** (12 bets) on BC-053.
  - All-time: 2,134 / 1,142, -10.74% (2,109 / 1,137, -10.79% at Reading 88).
  - Yesterday (late 11-18 grades): 69 bets / 35 events, +3.64% [-22.9, +30.1].
  - 7 d: -3.96% [-15.0, +7.1] on 179.
  - 30 d: -7.15% [-12.6, -1.7] on 707.
  - 11 games are still in play; none is late.
- **No new anomaly.** Every endpoint returned in 0.27 s or less. The GATE line is the same 2 unclassified loads.
- **Noted, not an anomaly:**
  - `/api/portfolio/plan` took 50 requests in the window (2 a reading before), at a steady 2 a minute from 03:27Z.
  - UA `Python-urllib/3.11`, so another session's poller, not this probe.
  - Cheap: median 19 ms, max 193 ms. No action.
- **Flow:**
  - Plan 0.8 min old: 41 suggested, 14 positions.
  - Live ticks: 0 placed in 9.
  - Orders today: 58. 57 filled, 1 maker expiry.
  - Cap use: 27.1% Kalshi, 15.1% Polymarket.

## Reading 90 — Thu 11-19 10:27 PM CST (04:27Z), window 30 min

- **Results first.**
  - Gate: **9 of 800 events** (13 bets) on BC-053.
  - All-time: 2,137 / 1,144, -10.72%.
  - 30 d: -7.15% [-12.6, -1.7] on 707 events.
  - 7 d: -3.96% [-15.0, +7.1] on 179.
  - 9 games are still in play; none is late.
- **No new anomaly.**
  - Every endpoint returned in 0.27 s or less.
  - The plan poller from Reading 89 has stopped (n=2 in this window).
  - The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 5.1 min old: 33 suggested, 13 positions.
  - Live ticks: 0 placed in 10.
  - Orders today: 58. 57 filled, 1 maker expiry.
  - Cap use: 27.1% Kalshi, 15.1% Polymarket.

## Reading 91 — Thu 11-19 10:57 PM CST (04:57Z), window 30 min

- **Results first.**
  - Gate: **11 of 800 events** (15 bets) on BC-053.
  - All-time: 2,140 / 1,146, -10.71%.
  - 30 d: -7.15% [-12.6, -1.7] on 707 events.
  - 6 games are still in play; none is late.
- **No new anomaly.** Every endpoint returned in 0.25 s or less. The GATE line is the same 2 unclassified loads.
- **Flow:**
  - Plan 4.9 min old: 33 suggested, 11 positions.
  - Live ticks: 0 placed in 10.
  - Orders today: 58. 57 filled, 1 maker expiry.
  - Cap use: 27.1% Kalshi, 15.1% Polymarket.

## Reading 92 — Thu 11-19 11:27 PM CST (05:27Z), window 30 min

- **Results first.**
  - No new grades since Reading 91. Gate: 11 of 800 events (15 bets) on BC-053.
  - All-time: 2,140 / 1,146, -10.71%.
  - 30 d: -7.15% [-12.6, -1.7] on 707 events.
  - 6 games are still in play; none is late.
- **Not a failure: a second `rejected` order today.**
  - A Kalshi spreads order went in at 05:21:36Z for a game that began at 02:48Z, and the venue canceled it 0.85 s
    later (`venue_canceled`).
  - This is the known in-play order that did not fill (`is_unfilled_inplay_ioc`), not a failure. The probe already
    excludes it.
  - Today: 59 orders, 57 filled, 1 maker expiry, 1 unfilled in-play order.
- **Watch item, 3rd slow `live_today` tonight: 2.58 s** (inside the 3.0 s budget; the server logged 2,559 ms).
  - The web log puts it right on a memory recycle:
    - `WEB_WORKER_MEMORY_RECYCLE` at 05:27:09.6Z (pid 1323361, anon 966 MB against a 628 MB limit, age 2,058 s);
    - the request finished at 05:27:11.0Z;
    - the other worker was also over its limit (818 MB) and its recycle was deferred for the 30 s spacing;
    - a new worker booted at 05:27:13Z.
  - Overlay rebuilds meanwhile ran every ~31 s at 5.8-7.7 s each.
  - **Tally: 2 of the 3 slow reads tonight (00:33Z, 05:27Z) coincide with a web memory recycle. The third
    (02:31Z) has no logged cause.** Both web workers are running 30-55% over their memory limit.
  - That is the same memory growth that lane `web-silent-worker-kills` named as its follow-up, and the cold read
    that `board-read-cold-share` (#853) measured. Neither is in this lane's scope.
  - The probe's budget was not breached (2 reads above 2 s, 1 above 3 s, in 14 evening reads).
- **Flow:**
  - Plan 1.2 min old: 27 suggested, 13 positions.
  - Live ticks: 0 placed in 12.
  - Cap use: 27.1% Kalshi, 15.1% Polymarket.

## Reading 93 — Thu 11-19 11:58 PM CST (05:58Z), window 31 min

- **Results first.**
  - Gate: **12 of 800 events** (16 bets) on BC-053.
  - All-time: 2,143 / 1,148, -10.70%.
  - 30 d: -7.15% [-12.6, -1.7] on 707 events.
  - 3 games are still in play; none is late.
- **No new anomaly.** `live_today` 0.25 s; every endpoint returned in 0.41 s or less. The GATE line is the same 2
  unclassified loads.
- **Flow:**
  - Plan 6.8 min old: 28 suggested, 13 positions.
  - 1 in-play Kalshi order placed (orders today 60: 58 filled, 1 maker expiry, 1 unfilled in-play order).
  - Cap use: 27.5% Kalshi, 15.0% Polymarket.

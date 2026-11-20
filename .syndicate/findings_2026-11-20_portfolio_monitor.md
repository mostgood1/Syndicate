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

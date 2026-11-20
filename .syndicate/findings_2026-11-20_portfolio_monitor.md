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

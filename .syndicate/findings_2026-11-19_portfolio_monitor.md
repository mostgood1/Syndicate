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

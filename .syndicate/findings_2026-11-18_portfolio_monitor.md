# Findings — lane `portfolio-monitor`, Wed 2026-11-18 (Central)

This continues `findings_2026-11-17_portfolio_monitor.md`, which holds the method, readings 1-24, findings F1-F7
and their fixes. Same probe (`scripts/portfolio_monitor_probe.py`), same page (Portfolio Watch).

## Reading 25 — Wed 11-18 12:11 AM CST (06:11Z), window 32 min

- **The Central date rolled over.** "Today" in the probe is now 11-18: orders today 0, cap use 0%.
  - `plan_commits` now tracks 11-18's plan. Its 6-h series still holds the earlier evening, when 11-18 was the next
    day, so its "max gap 102.6 min" (02:02 -> 03:44Z) is the next-day cadence, not a stall.
  - Read the evening metric from the 11-17 readings.
  - 11-17's last plan write was 05:58:39Z.
- **Plan 0.3 min old (11-18).** 30 suggested -> 24 sized -> 15 positions. Ceiling used 37.1%.
- **Execution, 32 min:** 10 live ticks, 0 placed, 0 failed. Refused: 4 `already_held_other_slate` (11-18 positions
  already held from the 11-17 slate), 1 `outside_price_band`, 1 `game_started`.
- **Settlement:** 7 started and unsettled (from 10), 0 late. These are 11-17's late NBA/NHL games. **11-17's daily
  summary waits for them.**
- **Endpoints:** all 7 read 200, all under 0.25 s. 0 kills. **Gate:** pending BC-041 (count 0).

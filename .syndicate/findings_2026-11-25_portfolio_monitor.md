# Portfolio monitor -- 2026-11-25 (lane portfolio-monitor, session 69d80317)

Counts and percentages only (public repo).

## Today's rollup row is marked `partial` (10:12 AM CST)

User 11-25: "mark today's rollup row as partial". This follows H-R1 (findings_2026-11-24_portfolio_monitor.md). Tooling only.
- `scripts/portfolio_watch/build_history.py`: every row carries `partial`, which is true while the row's date is today in CST. Until midnight, its rolling windows have dropped a full old day for only part of this one.
- `build_dashboard.py`: the history table's Day column reads "<date> (partial)".
- Test: `test_todays_rollup_row_is_partial_and_earlier_days_are_not`; 8 of 8 Portfolio Watch tests pass.
- Installed in the run copy at `C:\SyndicateProd\portfolio_watch` (backup in `backup_before_partial_1125\`) and rebuilt at 10:10 AM CST: 111 rows, 0 partial. That is correct: no 11-25 bet has graded yet, so the newest row is 11-24, now a complete day.
- **11-24 as a complete day:** 8 bets on 5 events. Its 30-day window (10-26..11-24) reads -6.45% [-11.97, -0.93] on 1,642 bets, still wholly below 0. So r30_negative stands on a settled day, not only on a partial one.
- Not changed: dash_chk still reads the LAST row (fleet-watcher's code). It can skip rows with `partial: true`.
- Owed: the first rebuild after an 11-25 bet grades should show the 11-25 row as partial.

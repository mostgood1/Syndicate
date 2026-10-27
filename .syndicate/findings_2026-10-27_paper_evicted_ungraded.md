# Paper bets with no outcome, by GAME date, and why they stay ungraded `[2026-10-27, lane syndicate-decision-engine]`

**User, verbatim (2026-10-27):** "...Then take the paper no-outcome count to close Phase 0."

Phase 0 item 4 (`#736`) asked for the unsettled paper backlog counted by GAME date, with an owner. Two earlier counts
existed: 928 unsettled paper and ladder rows (the plan, 10-26), and 1,896 counted by SUBMIT time (10-26 16:33Z). Both
were stand-ins. This is the count by game date, plus the mechanism behind it.

**Method.** READ-ONLY, on the fleet at nice 19, read at 2026-10-27 16:06Z (11:06 AM CDT).
- Orders come from `execution_ledger.full_history_orders()` (archive plus the live document), loaded with the
  refresh-worker's state env exactly as the 10-26 probe did. That is 19,528 orders, of which 3,000 are in the live
  document.
- A "no-outcome" order is `status == filled` and `outcome` empty.
- Game start is each order's `commence_time`; all 3,719 such orders carry one.
- `settled_at` is NOT settlement. It is stamped at the paper fill (median 82 h BEFORE the game), as
  `paper_settlement.py`'s docstring warns. Scratch scripts: `C:\tmp\phase0_backlog_gamedate.py`, `phase0_backlog_detail.py`
  and `phase0_backlog_mech.py`.

## The count

3,719 filled orders have no outcome: 3,684 paper and 35 live.

| game start vs the read | paper | live |
|---|---|---|
| not started yet (forward bets, not a backlog) | 1,690 | 33 |
| started 12-48 h ago (normal grading lag) | 160 | 1 (NFL in-game) |
| started 48 h-7 d ago | 865 | 1 (soccer) |
| started more than 7 d ago | 969 | 0 |

**The stale paper backlog is 1,834 orders: games that started more than 48 h ago and still have no outcome.**

By sport: NCAAF 1,098, soccer 457, MLB 133, NBA 79, NFL 60, NHL 7.

The largest Central game dates:

| sport | game date: stale orders |
|---|---|
| NCAAF | 10-24: 501; 10-17: 240; 10-10: 191; 10-03: 56; 10-23: 56; 10-09: 48 |
| soccer | 10-24: 102; 10-25: 74; 10-17: 71; 10-10: 55; 10-18: 45 |
| MLB | 10-24: 72; 10-08: 50 |
| NBA | 10-05: 19; 10-08: 20 (preseason) |
| NFL | 10-11: 24; 10-18: 20 |

**By market:**
- NCAAF: h2h 431, spreads 399, totals 208.
- Soccer: `alternate_totals_corners` 224, btts 84, totals 76, h2h 57.

**By book**, across 14 or more books, so it is not one venue:
- fanduel 271
- paper kalshi ladder 214; kalshi 166 + 51
- prophetx 193 + 147
- novig 173 + 106
- paper polymarket ladder 159

None of the 1,834 carries `graded_at`, an `error`, a `settled_value` or any `prior_attempts`. The grader never tried
them.

## Why: they were evicted from the ledger the grader reads

| where the stale order is | selected date vs the grader's window (10-22..10-28) | n |
|---|---|---|
| ARCHIVE | before the window | 1,453 |
| ARCHIVE | inside the window | 354 |
| LIVE document | inside the window | 27 |

**1,807 of 1,834 (98.5%) are in the archive.**
- The live document holds exactly 3,000 orders: `_MAX_RECORDS = 3000`, `syndicate/features/shared/execution_ledger.py:106`.
- When the cap is hit, `_trim_to_cap` (`execution_ledger.py:1137`) moves SETTLED paper rows out first, then UNGRADED
  ones. Its own docstring says: "a row that leaves ungraded can no longer be graded, because settlement writes this
  document, not the archive."
- `paper_settlement.settle_orders` reads only the live document (`_load()`), and only for the selected dates the
  refresh-worker passes it. On 10-27 those were 10-22..10-28, from `[paper_settlement] SETTLED` in `refresh-worker.log`.

**Forward bets are the most exposed.**
- Days from `selected_date` to the game: 0: 231 · 1: 400 · 2: 208 · 3: 200 · 4: 142 · 5: 162 · 6: 468 · 7: 23.
  So 995 of 1,834 (54%) were placed 3 or more days ahead.
- The cap comment sizes 3,000 as "about four days of paper at ~600 orders a day". A bet placed six days ahead
  therefore usually leaves before its game ends.

**The other 27**, still in the live document inside the window, are ungraded with NAMED reasons from the same
`SETTLED` lines:
- `match_not_in_soccer_live_state`
- `ncaaf_team_not_in_registry_or_ambiguous`
- `unmapped_market` (`alternate_totals_corners`, `btts`)
- `no_live_feed`
- `player_not_in_box`

That is a separate, small mechanism.

## Who it affects (believed, not measured per reader)

Every reader of paper outcomes is missing about 1,800 rows, and they are NOT missing at random: NCAAF game lines,
soccer corners, and bets placed days ahead. Readers named in the ledger:
- `#727`'s earned-profile refit (~11-01). Its closest cell is prophetx / NCAAF / spreads / regular, which is exactly
  the evicted population.
- `#724`'s ladder control-arm reading at 400 settled.
- The CLV report and min-ev tuner reads.
- Any paper ROI.

Phase 2's paper track (`decision_policy_paper`) keeps its own book and grader, so it is NOT affected.

## Owner and fix (handed off, not built)

Lane `paper-evicted-grading` (todo `#744`) is opened for pickup. The fix options, for that lane to choose and
pre-register:
1. A grading pass over ARCHIVED, ungraded paper rows whose game is decided. It appends the graded copy to the archive;
   `archived_orders` keeps the last copy per identity (verify), then backfill once from 10-02.
2. Leave the eviction order alone. The 8 MB store cap is real (`#566`-era history in the comment).
3. Booking horizon and volume are policy, so they are the user's call, not a fix here.

Any fleet write (the backfill, or enabling the pass) is a user decision under the deploy locks. Build it default-off,
with a reachability test before correctness.

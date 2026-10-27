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

## Pre-registration: grading the archived rows `[2026-10-27 16:2xZ, lane paper-evicted-grading, session 7833a791, written BEFORE any code or data read]`

**Hypothesis** (the lane's): the stale backlog is eviction, not grading failure. Most stale paper rows sit in the
archive, which `settle_orders` never reads; graded by the same code they would mostly grade.

**Population.** Re-derived at the dry run's own read time, with the 16:06Z definition: `full_history_orders()`,
`mode == paper`, `status == filled`, no `outcome`, `commence_time` more than 48 h before the read. The 16:06Z list was
not saved as identities, so the 1,834 is quoted beside the new count and the gap is stated, not reconciled row by row.
Split by where each row sits: the LIVE document (owned by `settle_orders`, not this pass) vs ARCHIVE ONLY.

**Primary arm, the verdict.** Each archive-only stale row (the last archived copy per identity, identity absent from
the live document) is asked exactly what `settle_orders(selected_date)` would ask had the row stayed in the document:
`_default_resolver(selected_date)`, then `_our_verdict` -> `resolve_bet_status` -> `grade_order`. "Would grade" means a
verdict comes back. Paper rows skip the live-only venue grace and Kalshi-exit steps, exactly as in `settle_orders`.

**Falsification, threshold fixed now.** If FEWER than 50% of the archive-only stale rows would grade under the primary
arm, eviction is not the cause for most of them: the lane re-scopes to the dominant named reasons, and the backfill is
not proposed as the fix. At 50% or more, eviction is confirmed as the dominant cause, and the remainder is reported by
reason as a second mechanism.

**Diagnostic arm, reported separately and NOT part of the verdict.** Rows the primary arm refuses are re-asked with the
resolver bound to the game's kickoff date (Central) instead of the slate date. Why, known before any data: the soccer,
MLB and NBA resolvers read only the slate date's state, while NFL and NCAAF search the kickoff date first
(`bet_status_nfl.order_capture_dates`); and 995 of the 1,834 were booked 3 or more days ahead.

**Read-only.** The dry run writes no ledger and no archive. Resolver side-writes are suppressed and COUNTED: soccer's
`_remember_finals`, the NFL/NCAAF lazy capture (forced to `persist=False`), and any `refresh_state_store` write. External
GETs still happen (ESPN scoreboards on a capture miss, NHL api-web): the same reads settlement already makes.

**Reporting.** Counts by sport and Central game date, every refusal by name, and every rate with its n.

**Mechanism checked in code before building on it.** `archived_orders` keeps the last copy per identity in shard order,
and a graded copy appends to the same month shard (keyed by `selected_date`), so it wins. `_with_archive` lets the live
document beat any archived copy. Both are pinned by tests rather than taken on trust.

## Result: the dry run `[2026-10-27 16:37-16:41Z (11:37-11:41 AM CDT), READ-ONLY, fleet; code 2ec80fe0 from a scratch extract, fleet checkout 84967f75 untouched]`

**Verdict: FALSIFIED as pre-registered, by 2 rows.** 908 of 1,820 archive-only stale rows would grade: 49.9%, against a
threshold of 50% (910). Taken at its word, the rule says eviction is not the cause for most of them, so the backfill is
NOT proposed as the fix.

**Population.** Stale at 16:39Z: 1,850 (1,834 at 16:06Z, net +16). In the live document: 30. Archive only: 1,820
(1,807 at 16:06Z).

**It splits by sport, not at random within each sport:**

| sport | would grade / archive-only stale | why the rest do not |
|---|---|---|
| NCAAF | 868 / 1,092 | `ncaaf_team_not_in_registry_or_ambiguous` 166, `ncaaf_props_not_gradeable_from_scoreboard` 58 |
| NFL | 40 / 60 | `nfl_player_not_in_final_box` 20 |
| soccer | 0 / 467 | `unmapped_market` 310 (`alternate_totals_corners`, `btts`), `match_not_in_soccer_live_state` 102, `no_soccer_live_state_for_date` 50, `no_soccer_player_box_for_match` 5 |
| MLB | 0 / 115 | `no_live_feed` 104, `stat_not_in_feed` 5, `not_decided_yet` 4, `mlb_game_rescheduled_off_slate_date` 2 |
| NBA | 0 / 79 | `no_live_box_for_date` 72 (preseason 10-05..10-12), `player_not_in_box` 3, others 4 |
| NHL | 0 / 7 | player name unmatched or ambiguous 6, `dnp_void` 1 |

For NCAAF and NFL, eviction is the whole story. Soccer, MLB, NBA and NHL would not grade even back in the document: the
refusals are grader coverage gaps, the same names the 27 live-document rows carried at 16:06Z.

**Largest Central game dates** (would grade / stale):
- NCAAF: 10-24 418/495; 10-17 198/240; 10-10 183/191; 10-23 53/56; 10-09 14/48; 10-03 0/56 (54 registry).
- NFL: 10-11 22/24; 10-18 11/20; 10-25 7/7; 10-04 0/8.
- soccer: 10-24 0/102; 10-25 0/84; 10-17 0/71; 10-10 0/55.
- MLB: 10-24 0/54 and 10-08 0/50, all `no_live_feed`.

**Diagnostic arm, reported and NOT used in the verdict.** Re-binding the refused rows to the kickoff date recovers 117,
all soccer, out of soccer's 152 `match_not_in_soccer_live_state` / `no_soccer_live_state_for_date`. So most of soccer's
not-found is a slate-date binding defect: the soccer resolver reads only the slate date's state, and a forward bet's
match is on a later date. No other sport moves. With the arm, the share would be 1,025 / 1,820 = 56.3%; it is not
counted, because the pre-registration put it outside the verdict.

**Read-only, checked.**
- The archive shard's sha256 was identical before and after.
- No lock file was created.
- Suppressed writes: `nfl_capture_persist` 11 and `ncaaf_capture_persist` 5. These are lazy scoreboard captures that a
  real run would persist, as settlement does. Nothing else was suppressed.

**The whole pass**, not only stale rows (`--since 2026-10-02`):
- 1,933 candidates, of which 981 would grade (512 won, 462 lost, 7 push).
- 144 games had not started; 76 rows were left to the live document.

**Blast radius of an apply.** Measured by a second read-only probe at 16:41Z, comparing the full history before and after
the 981 graded copies.
- Writes: 981 graded copies appended to `orders_2026-10.jsonl`. By book: `paper` 384, `paper:novig` 143,
  `paper:prophetx` 134, `paper:kalshi:ladder` 116, `paper:polymarket:ladder` 103, `paper:kalshi` 70,
  `paper:polymarket` 31.
- Stake sizing: no change. `settled_decisions_by_sport` moves NCAAF 1,499 -> 1,586, NFL 862 -> 884, MLB 726 -> 728 and
  NHL 521 -> 523. Every sport was already at credibility 1.000.
- `live_cell_gate`: `evaluate()` is identical before and after. There are no trip or re-arm events, and the 3 tripped
  cells' paper-twin samples do not move: the graded rows predate their `tripped_at`.
- What does change is the analysis readers: paper PNL/ROI lines, CLV, the min-ev tuner (shadow), `#727`'s refit (the
  NCAAF cells) and `#724`'s ladder count (+219 settled ladder rows).
- The remaining gap stays NON-random: after an apply, the missing stale rows are soccer, MLB, NBA and NHL, plus
  NCAAF's registry and prop refusals.

**Re-scope candidates, from the named reasons, by size:**
1. Soccer `unmapped_market` 310: there is no corners or btts mapping.
2. The NCAAF team registry, 166: 10-03 accounts for 54 of 56 and 10-09 for 34 of 48.
3. Soccer slate-date binding, 152: 117 of them are recoverable by kickoff-date binding.
4. MLB `no_live_feed`, 104.
5. NBA preseason `no_live_box_for_date`, 72.
6. NCAAF props 58, NFL `player_not_in_final_box` 20, NHL 7.

Scratch: `C:	mp\peg\` (`dryrun.sh`, `dryrun.log`, `report_20261027T163701Z.json`, `reader_deltas.py`/`.log`).

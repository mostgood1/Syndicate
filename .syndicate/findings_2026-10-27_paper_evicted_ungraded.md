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

Scratch: `C:\tmp\peg\` (`dryrun.sh`, `dryrun.log`, `report_20261027T163701Z.json`, `reader_deltas.py`/`.log`).

## Applied `[2026-10-27 17:20-17:27Z, user-approved, refresh-worker claim; deploys.md has the full entry]`

- **What was written:** 981 graded copies appended to the archive (512 won, 462 lost, 7 push), with a closing mark on all 981 (941 with a CLV).
- **Stale paper count:** **1,906 -> 953**. Archive only 1,875 -> 922; live document 31.
- **By sport (archive only):**
  - NCAAF 1,092 -> 224 and NFL 110 -> 25.
  - Soccer 472, MLB 115, NBA 79 and NHL 7 are unchanged.
- **The 953 that remain are all grader gaps, by name:**
  - soccer `unmapped_market` 314
  - NCAAF registry 166
  - MLB `no_live_feed` 104
  - soccer not-found / no-state 153
  - NBA preseason box 72
  - NCAAF props 58
  - NFL player not in the final box 25
  - plus small tails
- **The threshold flipped between reads:** the same instrument read 50.8% at the apply's own read (17:20Z), against 49.9% at 16:39Z. The pre-registered verdict (the first reading) stands. It sits on the threshold, so the split by sport is the finding, not the verdict.
- **Hourly pass NOT enabled:** its env key loads only at a full supervisor down/up, not at a refresh-worker role restart.

## Enabled, inert until a full up `[2026-10-27 20:54:32Z (3:54 PM CDT), user-approved in this lane's chat; deploys.md has the full entry]`
- `REFRESH_WORKER__SYNDICATE_PAPER_ARCHIVED_GRADING=on` was appended to the fleet env file. Nothing was restarted.
  - sha256 `b9431eb1...198c` -> `67adbf4e...f5ef`. The backup is `local_production.env.bak-archived-grading-20261027T205432Z`.
  - refresh-worker's derived env reads `on`. live-odds-worker and web do not get the key.
- **Inert until** the first full down/up whose commit contains `2ec80fe0`. At 20:56Z the last UP was `0fca3f2b7af4` and the checkout was `84967f755`; neither contains it.
- **Check:** the daily read-only scheduled task `paper-archived-grading-first-line` records the first anchored `[paper_settlement] ARCHIVED_SETTLED` line, then disables itself (hard stop 2026-11-10).
- **Still open:** the 953 rows behind the named grader gaps (above) need the lane re-scoped. Not started.

## Re-scope: the grader gaps -- pre-registration `[2026-10-27 23:20Z, lane paper-evicted-grading, session 7833a791, written BEFORE any code change; user, verbatim: "we need to solve for those"]`

**The population.** 981 stale paper rows: the game started more than 48 h ago and there is no outcome. Read-only on the fleet at 23:15Z, with main `2c8ba8be` from a scratch extract and every write suppressed (0 reached). The count is up from 953 at 17:27Z as more games crossed 48 h. 0 of the 981 grade with today's resolvers.

| sport | refusal | rows | what the rows are |
|---|---|---|---|
| soccer | `unmapped_market` | 322 | `alternate_totals_corners` 233 and `btts` 89, mostly FORWARD bets (slate 10-04, game 10-09/10) |
| soccer | `match_not_in_soccer_live_state` + `no_soccer_live_state_for_date` | 170 | game lines; the slate is days before the game |
| soccer | `no_soccer_player_box_for_match` | 5 | props |
| ncaaf | `ncaaf_team_not_in_registry_or_ambiguous` | 171 | only FIVE pairs: four San Jose State games (147) and LSU v McNeese State (24) |
| ncaaf | `ncaaf_props_not_gradeable_from_scoreboard` | 59 | Receptions 34, Passing TDs 23, Receiving Yards 2 |
| mlb | `no_live_feed` | 122 | two game dates only: 10-08 (50) and 10-24 (72) |
| mlb | tails | 11 | stat 5, not decided 4, rescheduled 2 |
| nba | `no_live_box_for_date` | 72 | ALL game lines, preseason 10-04..10-16; the live box capture starts later |
| nba | tails | 14 | player not in box 7, segment 6, `player_double_double` 1 |
| nfl | `nfl_player_not_in_final_box` | 28 | Receptions 21, Rushing Attempts 5, other 2; e.g. Troy Franklin, Jeremy Ruckert |
| nhl | tails | 7 | ambiguous 4, unmatched 2, `dnp_void` 1 |

**Root causes, as read from the code** (each a hypothesis until the dry run reads it):
- **Soccer binds to the slate date.** It reads match state for `selected_date` only (props: plus or minus 1 day). A forward bet's game is days later. On the fleet, every league's `live_state_<date>.json` for 09-30..10-27 is still on disk. Each holds a `match_box` with `final`, `score_home`/`score_away`, linescores, and `teams.{home,away}.stats.Corners`.
- **Soccer has no corners or btts rule.** Both are readable from the same match box.
- **NCAAF names:** the registry has "San José State" with the accent unfolded, and "McNeese" while OddsAPI sends "McNeese State Cowboys".
- **MLB never fetches.** It reads only the cached `feed_live` (`fetch_if_missing=False`), and nothing captured those two dates.
- **NBA has no source before the live box existed.** Its only source is the live-lens box, which did not run in the preseason.

**Pre-registered predictions and falsification** (the share of each group that grades in a fleet dry run with the fixed code):
- **H1, soccer kickoff-date binding:** at least 85% of the 175 soccer match-state refusals bind to a match-box record within kickoff (UTC date) -1..+1. FALSIFIED below 50%.
- **H2, corners and btts:** with H1's binding, at least 85% of the 322 grade (match final; for corners, both teams' Corners present). FALSIFIED below 50%.
- **H3, NCAAF names:** accent folding (both sides) plus a McNeese State alias resolves all 5 pairs. The registry's unambiguous key set may only GROW; any key that becomes ambiguous falsifies it. At least 90% of the 171 grade.
- **H4, MLB:** a settlement-only fetch of the StatsAPI feed, for games that started more than 6 h ago and memoised per resolver, grades at least 90% of the 122. The board never fetches.
- **H5, NBA preseason:** for a date with no live box, a final-score source grades at least 90% of the 72 game lines.
- **H6, football props (NCAAF 59, NFL 28):** diagnose first. No prediction is made. Absent from a box must never read as zero.
- **Tails** (NBA 14, MLB 11, NHL 7) are not in scope unless they fall out of the above.

**Every fix lands in the per-sport resolver** that `settle_orders`, its straggler dates and the archived pass all share. So each one also closes the gap for the LIVE book going forward. Today, a forward-dated soccer order, any corners or btts order, and any NBA preseason order can never grade.

**What would make this re-scope wrong:** if the dry run grades fewer than 50% of the 981 with all fixes in, the gaps are not what the code reading says.

## Re-scope result: the grader gaps, dry run `[2026-10-27 23:51Z (6:51 PM CDT), READ-ONLY, fleet; main 2c8ba8be extract + the six fixed files; every write suppressed and counted (3 NCAAF capture persists, none reached disk); archive sha256 unchanged]`

**868 of 981 stale rows grade (88.5%)**, up from 0. The re-scope's falsification line was 50%, so it is NOT falsified. Outcomes: soccer 229 won / 263 lost / 2 push, NCAAF 107 / 120, MLB 66 / 56, NFL 1 / 24.

| hypothesis | prediction | read | verdict |
|---|---|---|---|
| H1 soccer kickoff-date binding | >= 85% of 175 | **172 / 175** (98%) | CONFIRMED |
| H2 soccer corners + btts | >= 85% of 322 | **322 / 322** | CONFIRMED |
| H3 NCAAF names | >= 90% of 171, no new ambiguous key | **171 / 171**; index 2,237 -> 2,239 keys, 0 lost, 0 re-owned | CONFIRMED |
| H4 MLB finished-game fetch | >= 90% of 122 | **122 / 122** (Division Series 849832, World Series 849802; both Final on statsapi) | CONFIRMED |
| H5 NBA preseason | >= 90% of 72 | not run: needs a box write (below) | OPEN |
| H6 football props | diagnose first | NFL **25 / 28**, NCAAF **56 / 59** | see below |

**What H1 actually was: a second cause under the first.** Binding to the kickoff date alone graded 25 of 497. The per-league `live_state_<date>.json` files are written to DISK by the poller (`poll_soccer_live_state.py`, `out_path.write_text`). On the fleet's keyvalue backend, though, `read_json_file` asks Redis only, where a dated key lives ten days at most. Reading them through `soccer.sources.live_state_payload` (the store, then the poller's own file) took soccer to 494 / 497. `_load_player_boxes` uses the same reader, so this also explains why fleet soccer props mostly could not grade either.

**Binding audit** (all 151 distinct soccer order matches): 86 matched with exact names and 64 through an alias, every one of them the same club (e.g. Inter Milan -> Internazionale, New York Red Bulls -> Red Bull New York). 0 bound to two records. 1 had no record at all: Rayo Vallecano v Athletic Bilbao, 10-10 12:00Z, 3 rows.

**H6, as diagnosed** (by a subagent; code reviewed here):
- **NFL.** ESPN's summary box lists a player only in a stat group he recorded something in. ESPN's core game roster answered all 11 player-games: 8 played with zeros (`didNotPlay: false` and `gamesPlayed: 1`), 2 were inactive (Tyler Warren, Tyjae Spears: `nfl_player_did_not_play_void`, refused by name as NHL and soccer do), and 1 was a name form ("Zonovan Knight" is ESPN's "Bam Knight").
- **NCAAF.** ESPN's college summary has the NFL box shape, and the capture stores ESPN's `event_id`. 56 graded. The college roster cannot prove who played, so 3 rows still refuse: Beau Pribula 1 and Mark Bowman 2.
- **Network bounds.** Reads happen only for games whose kickoff is more than 6 h old, with a 6 s timeout, never raising. A refusal is memoised process-wide: 6 h for a fact about the player, 1 h for a failed read, 512 entries.

**Still refused, 113 rows, every one by name:**
- **NBA preseason 72** (`no_live_box_for_date`). The live box capture never ran in the preseason. `scripts/backfill_nba_paper_grades.py boxes`, previewed read-only at 23:32Z, found all 57 games on the 11 dates final in ESPN. Writing those 11 files is a fleet data write, so it waits on the user.
- **NBA tails 14.** These include props attached to a game the player was NOT in: LeBron James on 76ers v Bucks, Kawhi Leonard on Timberwolves v Raptors. That is a candidate-join defect upstream of grading, not a grader gap. A follow-up.
- **MLB tails 11:** stat not in the feed 5, not decided 4, rescheduled 2.
- **NHL 7:** two Elias Petterssons, Zack Bolduc traded, 1 DNP.
- **Soccer 3** (Rayo v Athletic), and football 6 (above).

**The fixes go live for the LIVE book as well,** since `settle_orders`, its straggler dates and the archived pass share these resolvers. Until a fleet run of this code: a forward-dated soccer order, any corners or btts order, an NCAAF San José State or McNeese State order, an uncached MLB game, an NFL prop on a player with no catch, and every NCAAF prop cannot grade.

## Re-scope apply `[2026-10-28 12:39Z-13:00Z, fleet, user-approved "Yes, apply both"; deploys.md 12:39:41Z]`

- **NBA preseason boxes:** written as 11 Redis keys (10-day TTL) holding 57 final games and 1,695 player lines. **H5 CONFIRMED: 72 / 72** NBA preseason rows graded.
- **Archive backfill on main `7abbe65c`:** 943 graded copies appended (452 won / 489 lost / 2 push). Closing marks on all 943, 880 with a CLV.
- **Stale paper 988 -> 80.** Archive-only 951 -> 43; still gradeable 0. Across the lane, archive-only stale went 1,875 (10-27 17:20Z) -> 922 -> 43.
- **A failed first attempt, mine:** a `| head -40` in the runner closed the pipe, and Python exited 120 before the append. Nothing was written; it was re-run with a log file.
- **The 43 left are refused by name.** NBA DNPs 12 (see `findings_2026-10-28_nba_prop_wrong_game.md`), MLB 11, NHL 7, other NBA 5, soccer 3, NFL DNP 3, NCAAF 2.
  - The DNP rows (NBA 12, NFL 3, NHL 1) need a paper void outcome, and that is a user decision (`#744` owed (b)).
- **The 37 rows in the live document** are graded by the live `settle_orders` path, which still runs `0fca3f2b`. They wait on a fleet ff plus a full down/up, which is a user decision.

## Void re-scope: pre-registration `[2026-10-28 13:10Z, BEFORE any code; user, verbatim: "Yes, void them", answering "Should paper settle a sat-out prop as a void, stake back and out of ROI?"]`

**The decision.** A paper bet on a player who did not play settles the way a book settles it: void, stake back, out of ROI and hit rate.

**Design, fixed before code:**
- **The outcome.** A void is `outcome = push`, with `pnl_dollars = 0.00` and `void_reason = <the resolver's DNP reason>` stamped on the row. This follows the existing convention: `settlement_identity._void_graded` grades a non-runner as `result: "push"` ("what a book does with a non-runner"). A new outcome value was rejected. 205 sites compare against `"push"`, and some treat anything not won as a loss (`live_cell_scorecard`'s `decided = outcome != "push"`), so a new value would be scored as a loss there.
- **ROI.** The paper P&L summary counts voids in their own column and keeps their stake out of `staked_dollars`, the ROI denominator. `win_pct` already excludes pushes. Every other reader sees a $0 push.
- **Which reasons void.** An explicit allowlist, never a suffix match: `nfl_player_did_not_play_void`, `dnp_void` (NHL), `soccer_player_did_not_appear_void`, and the new `nba_player_did_not_play_void`. Each fires only on a FINAL game. The rule sits in `_our_verdict`, so `settle_orders`, its straggler dates, the archived pass and the venue cross-check all share one copy. Kill switch: `SYNDICATE_PAPER_DNP_VOID=off`. Absent means ON, because the user has decided the policy.
- **NBA detection** (ESPN, read 2026-10-28 13:2xZ on the three known games):
  - The core game roster lists a DRESSED player who sat out with `didNotPlay: true` and no statistics. Kawhi Leonard, 401909864: "LEFT KNEE SWELLING".
  - An INACTIVE player is absent from the summary box, the core game roster AND the current injury list. LeBron James, 401909855; Kyrie Irving, 401909858.
  - So the rule is: match the order's name to ONE athlete on the two clubs' ESPN team rosters, which gives the athlete id; then find that id among the game-roster `playerId`s. In the roster with `didNotPlay: true` and no stats, or absent from both game rosters, means did not play. In the roster with stats means played (a name-form gap with our box), so refuse by name.
  - A name that matches no team-roster athlete refuses and never voids. Absence is judged by ATHLETE ID, never by name.
  - The checks above match ids 6450 / 1966 / 6442 as predicted: present + DNP, absent, absent.
  - Settlement-only: a final game more than 6 h past tip, read through `EspnSettlementFeed` with the NFL path's timeout and its 6 h / 1 h refusal memo.

**Hypotheses, falsifiable on a read-only fleet dry run of the archived pass:**
- **H7 void:** of the 16 archive-only DNP-class rows at 13:00Z (NBA `player_not_in_box` 12, NFL void 3, NHL `dnp_void` 1), at least 14 grade as void.
  - Every other refusal count is unchanged, and won / lost counts on previously graded rows are untouched (the pass skips rows with an outcome).
  - FALSIFIED if fewer than 14, or if any non-DNP reason's count moves.
- **H8 NBA detection:** of the 12 NBA `player_not_in_box` rows, at least 10 resolve `nba_player_did_not_play_void`, and every voided row's player has 0 minutes in ESPN's summary for that game.
  - FALSIFIED if any voided player recorded minutes. That would be a wrongful void, which the athlete-id rule exists to make impossible.

## Void re-scope: result `[2026-10-28 13:18Z-13:19Z, READ-ONLY fleet dry run; main 7abbe65c extract + the three changed files; every write suppressed (0 reached); archive sha256 unchanged]`

| hypothesis | prediction | read | verdict |
|---|---|---|---|
| H7 void | >= 14 of the 16 DNP-class archive-only rows; no other reason moves | **16 / 16** (NBA 12, NFL 3, NHL 1). Every non-DNP count is unchanged: MLB 11, NBA 5, NCAAF 2, NHL 6, soccer 3 | **CONFIRMED** |
| H8 NBA detection | >= 10 of 12 `nba_player_did_not_play_void`; 0 voided players with minutes | **12 / 12.** 7 sat out while dressed (ESPN summary `didNotPlay`), 5 were inactive (absent from ESPN's summary box). **0 played.** | **CONFIRMED** |

**The NBA twelve**, each checked against ESPN's own summary for that game:
- Inactive: LeBron James (1966), Kyrie Irving ×2 (6442), Keegan Murray (4594327), Ausar Thompson (4684742).
- Sat out while dressed: Kawhi Leonard ×4 (6450), VJ Edgecombe ×3 (5124612).

**What the archived pass would append: 18 voids.** That is the 16 stale rows plus 2 archive-only rows that are final but not yet 48 h past start.
- Stale total 80 -> 64. Archive-only 43 -> 27.

**Regression:** 859 passed across the 29 test files that touch the changed modules, plus the new `tests/test_paper_dnp_void.py` (25 tests, reachability first).

**Known simplification.** The void is venue-agnostic, applied as the books' rule. An exchange's own contract terms for a player who doesn't play may differ; none of the 18 is on an exchange venue in this read. Not yet checked per row.

## Void apply `[2026-10-28 14:37Z-14:41Z, fleet, user-approved "Yes, apply voids"; deploys.md 14:39:05Z]`

- **Applied from main `a0d23665`:** 18 voids appended, every one `push` at $0.00 with `void_reason`. NBA 12, NFL 5, NHL 1.
- **Stale 45 -> 29.** Archive-only 43 -> 27; still gradeable 0. The 14:02Z fleet down/up (coordinator 332cb014) had already taken the live-document rows 37 -> 2.
- **CORRECTION to "Void re-scope: result" above.** It says "none of the 18 is on an exchange venue in this read". **That was wrong.**
  - 10 of the 18 are `paper:kalshi:ladder` (NBA 8, NFL 2). The line was written without reading the `venue` field.
- **Kalshi's rule for those 10** (public market API, read 14:41:31Z):
  - All 9 distinct tickers are `finalized`, result `scalar`, settled at $0.41-$0.65.
  - The rule text: "If a player is inactive, or active but never takes the court, the market settles to a fair price."
  - So a Kalshi-ladder paper bet on a player who did not play gains or loses the gap between that fair price and its entry price. It is not a void.
- **Size:** at Kalshi's prices the 10 rows are **+$0.596 gross, +$0.225 net of the assumed fees, on $10** (8 up, 2 down; per row -$0.063 to +$0.102 net).
  - The voids hold them at $0.00, with $10 out of the ROI denominator.
- **What the fix looks like:**
  - For a `paper:kalshi:*` row with a DNP reason, read the market by `venue_ticker`. When it is `finalized` and `scalar`, settle at `settlement_value_dollars`: gross = stake x (fair / entry - 1).
  - The 8 book-style `paper` voids stay as they are.
  - A corrected copy supersedes each void (readers take the last copy per identity).
  - Polymarket ladders are unread; none of the 18 is on one.

## Kalshi fair-price re-scope: pre-registration `[2026-10-28 16:02Z, BEFORE any code; user, verbatim: "Yes, build it", answering "Settle Kalshi-ladder paper bets on players who didn't play at Kalshi's fair price?"]`

**The decision.** On a Kalshi venue, a bet on a player who did not play settles the way Kalshi settles it: at the market's published fair price, not as a void. Books and the other exchanges keep the void.

**Design, fixed before code:**
- **Scope.** Orders whose venue names Kalshi (`kalshi`, `paper:kalshi`, `paper:kalshi:ladder`; the same `"kalshi" in venue` test `settle_orders` uses for exits) with a reason in `DNP_VOID_REASONS`.
- **The read.** Kalshi's public market by `venue_ticker`, through `kalshi_client._get` and its base URLs.
  - It settles only when `result == "scalar"`, `status` is finalized or settled, and `settlement_value_dollars` reads inside [0, 1].
  - Anything else refuses by name and never voids or guesses:
    - not settled yet (it waits);
    - a yes/no result, meaning ESPN and Kalshi disagree on whether he played;
    - unreadable;
    - no ticker on the order.
- **The leg.** `kalshi_orders._side_to_kalshi(side, market, line)`, the order builder's own mapping. A YES leg is worth the fair value, a NO leg 1 minus it. An unmappable side refuses.
- **The money.**
  - Entry per contract = 1 / (1 + `profit_per_dollar(fill_price)`), which handles both units in the column.
  - Gross = stake x (leg value / entry - 1). Net = gross - `fees_dollars` (paid at execution; Kalshi does not refund it).
- **The shape.**
  - `outcome = push`, since it is neither a win nor a loss, which keeps it out of hit rate. `pnl_dollars` is the net.
  - `fair_price_reason = "kalshi_dnp_fair_price"` and `venue_fair_value` are stamped on the row, with NO `void_reason`. So the stake stays IN the ROI denominator, as the Kalshi account would show it.
  - Tally key `fair_price`.
- **Superseding the 10 voids.** The archived pass also takes, as a candidate, a last copy that carries `void_reason` on a Kalshi venue. The re-graded copy drops `void_reason`. Readers take the last copy per identity.
- **Live Kalshi fallback.** A live order the venue left ungraded past its grace gets the same verdict. A SOLD exit plus a fair price refuses by name, because `exit_adjusted_pnl` would settle a push at cost.
- **Rollback:** the same `SYNDICATE_PAPER_DNP_VOID=off` (DNP rows refuse again on every venue).

**Hypotheses, falsifiable on a read-only fleet dry run of the archived pass with the new code:**
- **H9 fair price:** all 10 `paper:kalshi:ladder` voids re-grade as `fair_price`.
  - Gross total +$0.596 and net +$0.225 (+/- $0.005), from the 14:4xZ hand computation off Kalshi's settlement values.
  - Every row's gross agrees with its hand figure to $0.001.
  - FALSIFIED if any of the 10 refuses, or any row is off by more than $0.001.
- **H10 nothing else moves:** the 8 book-style voids are not candidates, the 27 named refusals are unchanged, candidates = 37, and graded = 10.
  - FALSIFIED on any other count change.

**The apply is NOT authorised by this.** "Yes, build it" covers the code. Superseding the 10 on the fleet archive is a separate decision, asked with the dry run's numbers.

## Kalshi fair-price re-scope: result `[2026-10-28 16:07Z-16:10Z, READ-ONLY fleet dry run; main a0d23665 extract + the new paper_settlement.py; 0 writes; code on main 3f9be985]`

**The fleet moved under this lane.** Coordinator 332cb014's ff to `5f813c4d` at 15:12:28Z named `a0d23665` as a ride-along to the user, so the void rule went live there.
- Since then the hourly archived pass has appended 5 more voids: 2 more Kalshi-ladder rows (Chet Holmgren assists and Cason Wallace threes, 10-26) and 3 book rows.
- The archive now holds 23 voids: Kalshi 12, book 11. The live document holds 0 (read 16:10Z).

| hypothesis | prediction | read | verdict |
|---|---|---|---|
| H9 fair price | all 10 Kalshi-ladder voids re-grade `fair_price`; gross +0.596 / net +0.225; each row within $0.001 of its hand figure | **10 / 10**, every row within $0.001, **+0.596 gross / +0.225 net**. The 2 new Kalshi voids grade `fair_price` too (Holmgren -0.0356 gross, Wallace +0.1289). All 12: **+$0.690 gross / +$0.250 net on $12** | **CONFIRMED** |
| H10 nothing else moves | candidates 37, graded 10, the 27 refusals unchanged, book voids not candidates | candidates **41**, graded **12**. The +2 graded are the 2 new Kalshi voids. The other +2 candidates are `actual_is_full_game_not_h1` rows that left the live document (stale there 2 -> 0, archive-only 27 -> 29). The 27 pre-registered refusals have identical counts. The 11 book voids are not candidates: outcomes are `{fair_price: 12}` only | **FALSIFIED AS WRITTEN, by the population moving, not by the rule.** Restated on the pre-registered population, it holds |

**Added after the dry run:** `settle_orders` also re-grades a stale Kalshi void sitting in the LIVE document, once. There are 0 there today; a test pins it.

**Regression:** 871 passed across the 28 test files that touch the changed modules, plus `tests/test_venue_settlement.py` and the new `tests/test_paper_kalshi_dnp_fair_price.py` (reachability first).

**No manual apply is needed once the code is on the fleet.** The archived pass has been armed since 14:02Z (`PAPER_ARCHIVED_GRADING=on`). On its first tick after an up it supersedes every Kalshi void in its 14-day window: today, the 12 above. The fleet window that carries the code is lane `syndicate-decision-engine`'s held one, whose trigger is this fix on main. A Kalshi DNP it settles from then on gets the fair price directly.

**Also fixed by this:** a LIVE Kalshi order on a player who did not play. `venue_settlement.grade_kalshi_settlement` refuses `scalar`, so before this the 24 h fallback had nothing to settle it with. Now it settles at the same fair price from the order's own fill. A SOLD exit refuses by name (`exit_fair_price_unsupported`).

**Still unread:** the DNP rules of Polymarket, ProphetX and Novig. Those venues keep the void. Today none of the 23 voids is on them.

## Kalshi fair price: live reading `[2026-10-28 17:10:59Z, READ-ONLY; deploys.md 17:10:59Z]`

- **The fleet window carried `3f9be985`.** Lane syndicate-decision-engine's window put `6d6e729d` on all three roles at 16:44:45Z. The armed archived pass ran at 16:57:30Z: `appended=12 outcomes={'fair_price': 12}`.
- **The 12 last copies** sum to **+$0.6898 gross / +$0.2496 net on $12**, equal to the dry run row by row. None still carries `void_reason`; all 11 book voids are untouched.
- **#744's Kalshi voids are closed:** 0 Kalshi-venue last copies are still void.
- **Live path:** 0 voids of either kind since the up, 0 in the live document. That is a null on a 26-minute window, so it carries no weight on its own (see deploys).

## Double-double rule and the exchanges' did-not-play rules `[2026-10-29 13:36Z-13:50Z, READ-ONLY fleet reads; code on main 1ec1eb2d]`

Asked by lane syndicate-decision-engine on 10-29, relaying the user's "proceed next steps across sessions".

### `player_double_double`: graded

- **The gap:** every archived pass logged `ARCHIVED_UNMAPPED_MARKETS {'player_double_double': 1}`. That is the archive's only one: Nikola Jokic, NBA 10-24, side `Yes`, `line` NaN, -680, $28.32 on venue `paper`. One more sits in the live document (Jokic, 10-28, Yes, -620, $8.85).
- **The rule (`bet_status_nba`):** count how many of PTS, REB, AST, STL and BLK reached 10. A double needs 2 and a triple 3. The resolver restates the line as `needed - 0.5`, the same way `game_line_bet` restates a spread, so Yes reads as an over and No as an under. A missing category refuses `stat_not_in_box`.
- **Not added to `is_monotone_market`:** the bet settles only at the final, never early in the game. That keeps the shared module out of the change.
- **Dry run 13:40Z** (read-only): fleet code `6d6e729d` against the same code plus the new `bet_status_nba.py`.
  - **Base:** both rows refuse `unmapped_market`. Pass: candidates 38, graded 0.
  - **New code:** both rows grade **won**. Jokic had a triple-double both nights (`settled_value` 3, line 1.5). Archive row **+$4.1647** on $28.32 at -680; live row +$1.4274 on $8.85 at -620. Pass: candidates 38, graded **1**, `outcomes {'won': 1}`, `unmapped_markets {}`.
  - **The other 37 refusals:** identical counts by reason. Archive shard 23,369 lines before and after; `suppressed_writes {}`.
- **Regression:** 1003 passed across the 32 test files that import the changed modules. 8 new tests in `tests/test_bet_status_nba.py` cover reachability, the count, steals, exactly 10, the triple, not decided mid-game, a missing category, and a grade through `paper_settlement._our_verdict`.
- **It applies itself.** The armed hourly archived pass grades the 10-24 row on its first tick after a fleet up that carries 1ec1eb2d. `settle_orders` grades the 10-28 row on the live path. Not on the fleet yet; that needs a window.

### Exchange did-not-play rules

**Reachable population today: 0.** Every exchange player-prop row on these three venues is MLB or WNBA (323 archived, 32 live), and every archived one is already graded won or lost. Neither the MLB nor the WNBA grader issues a did-not-play verdict, so neither the void nor any venue rule can fire on them. So the rules are recorded here and **no code was written for them**. A branch that no row can reach is the inert-feature pattern `model_engine_standard.md` warns about.

| venue | rule (primary text where found) | computable for our rows? | today |
|---|---|---|---|
| **Polymarket US** (the venue we trade: `api.polymarket.us`, `astatc-...` slugs) | The official Sports FAQ (docs.polymarket.us/faqs/sports-faqs), MLB section: "If the player doesn't participate at all, the Contract settles at LFMP." LFMP is "the prevailing fair market price on the Exchange at a specified moment in time", "typically the moment an official announcement is made", and "not the last traded price at market close". The FAQ has **no** player-not-playing sentence for NBA, WNBA, NFL, NHL or soccer. | **Yes, as with Kalshi.** `GET https://gateway.polymarket.us/v1/markets/{slug}/settlement` is public and returns `settlement` (a decimal price). 91 / 102 `paper:polymarket` and 54 / 55 `paper:polymarket:ladder` player rows carry the slug. | Keeps the void. Fair price is owed only when a did-not-play verdict can first reach a Polymarket row: an NBA/NFL/NHL/soccer prop there, or an MLB did-not-play verdict. |
| polymarket.com (global, NOT our venue) | Resolves **No**, per a third-party guide (about.darkhorseodds.com, "checked September 30, 2026"). No primary text read. | n/a | n/a |
| **Novig** | support.novig.com, "How settlement works -- grading, disputes, and voided trades": "A trade is voided if the event is cancelled, a player doesn't participate, or other conditions in the Market Rules apply. When a trade is voided, you will be paid out at the Fair Market Value." The FVS article (updated September 2, 2026) prices from "the 30 minutes of trading immediately before the Reference Time". Its worked example blends margin-free independent markets with Novig's time-weighted mid, and it publishes no formula. | **No.** Paper rows carry no Novig market id (0 / 102), and the formula is not published. | Keeps the void, the nearest stake-neutral reading of a fair-value settlement. |
| **ProphetX** | **Not found.** prophethelp.zendesk.com returns HTTP 403 to automated reads. The parlay-rules page defers to "House Rules", which could not be read. Search found only sportsbook practice and a June 2026 CFTC filing for MLB season-long contracts. | n/a | **Keeps the void: rule unread.** |

Sources: docs.polymarket.us/faqs/sports-faqs.md; docs.polymarket.us/api-reference/markets/get-market-settlement.md; support.novig.com/en/articles/10336135; support.novig.com/en/articles/16163706; support.novig.com/en/articles/9612523 (contracts now govern, at ludlowexchange.com); about.darkhorseodds.com/guides/kalshi-polymarket-market-rules.

### What #744 leaves

**37 named refusals**, from the 13:40Z dry run on the new code. Each is logged by `ARCHIVED_SETTLED` every hour, so none is silent.

- **15 NBA period bets** (`actual_is_full_game_not_{q1,q2,q3,q4,h1,h2}`, all venue `paper`). The box is whole-game. This one RECURS: every NBA quarter or half paper bet lands here.
- **6 NHL name matches:** 2 unmatched, 4 ambiguous in the box.
- **5 MLB `stat_not_in_feed`**, **4 `not_decided_yet`** and **2 MLB rescheduled off the slate date.**
- **3 soccer matches not in the live state.**
- **2 NCAAF players not in the final box.**

**Lane `paper-evicted-grading` CLOSED.**
- **Its goal is met:** stale paper fell from 1,906 to 38, then to 37 once the double-double rule is live.
- **No residual has an owner yet.** The NBA period box is proposed as its own task, being the only one that recurs. The rest stay listed here.

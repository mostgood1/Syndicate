# NBA quarter and half paper bets graded from the daily linescore (`#745`)

Lane `nba-period-paper-grading`, session 35e11968. Opened 2026-10-29 from `#744`'s residual: NBA period bets are the largest group of its 37 named refusals, and the only one that recurs.

## The gap `[2026-10-29 20:20Z, READ-ONLY fleet read; fleet code 6d6e729d; 0 writes]`

`bet_status_nba` called `segment_refusal(order)` before anything else. Every q1..q4/h1/h2 order refused `actual_is_full_game_not_<seg>` forever, game lines and props alike.

- **Archive (last copies):** 15 NBA segment rows, 0 graded. By segment: q4 4, h1 4, q1 3, q2 2, q3 1, h2 1. Markets: h2h 6, totals_alt 5, spreads_alt 2, spreads 1, totals 1. All `mode=paper`, `venue=paper`.
- **Books on the 15:** DraftKings 7, FanDuel 6, Pinnacle 1, BetMGM 1.
- **Live document:** 11 more NBA segment rows, 0 graded (h2h 8, totals_alt 2, spreads 1). Books: DraftKings 6, BetMGM 2, FanDuel 1, Pinnacle 1, Bovada 1.
- **Dates:** on all 26, `selected_date` equals the Central date of `commence_time`.

## The data was already on the fleet

`scripts/fetch_basketball_linescores.py` runs as scheduled job `basketball-linescores` at 10:35Z and covers the previous Central date. It writes `nba_source/data/processed/linescores_<date>.json`: completed games only, keyed by ESPN event id, each with `away`/`home` ESPN codes and `away_periods`/`home_periods`.

- **Fleet disk:** 20 files, 10-07..10-28, each fetched at 10:35Z the next morning. The 10-13 file was fetched 10-14 12:48Z.
- **Empty files:** 10-17, 10-18 and 10-19 hold 0 games.
- **Overtime games:** IND@OKC 10-13, BOS@PHI 10-16, MIL@IND 10-16, NO@DEN 10-24, MIN@CLE 10-26, BKN@BOS 10-27, SA@UTAH 10-28. Each is 5 periods on both sides.
- **None of the 15 archived rows is on an overtime game.** Two live-document games went to overtime (BKN@BOS, SA@UTAH), but their rows are q1/q2/q3/h1, which overtime cannot reach.
- **Team codes:** `canonical_team("nba", ...)` resolves 30 of the 31 ESPN codes in the files. `LON` (a non-NBA preseason opponent) does not, so it never joins.
- **The store trap.** The fleet's state backend is `keyvalue`, and `_keyvalue_backed(<this path>)` is True. So `read_json_file` would read Redis, while the producer writes the file with plain file IO. The resolver reads the file from disk.

## Overtime: each book's own rule `[read 2026-10-29]`

"Check, don't assume." The platform's football convention (`segment_actuals`: q4 alone, h2 + every OT) is wrong for at least one NBA book.

| book | q4 includes OT | h2 includes OT | primary text |
|---|---|---|---|
| DraftKings | **yes** | yes | MA house rules 8.18.25, basketball: "Bets on 4th Quarter Markets and 2nd Half Markets include overtime statistics for settlement purposes." |
| FanDuel | no | yes | MA house rules 7.30.26, "Overview of Specific Markets - NBA, NCAA and WNBA Basketball": "Quarter Markets: Resulted on score for relevant quarter - overtime does not count." "Second Half Markets: Resulted on score for second half, inclusive of overtime." |
| BetMGM | no | yes | MA house rules 3.28.25, Basketball Wagers: "Fourth quarter wagers do not include overtime periods unless otherwise stated." "Overtime periods are counted in the Second Half score". |
| Pinnacle | no | yes | pinnacle.com/en/future/betting-rules: "Bets on the Game and 2nd-Half periods include all overtimes played in their result." General rule: "Bets on a specific period count only the scoring in that period." |
| Bovada | **unread** | **unread** | No primary text found. |

**Readings stated, not assumed:**
- **DraftKings' exception.** Its general basketball rule excepts "4th Quarter/Moneyline Markets". In the same document "1st To Score/Moneyline" is a COMBINED market (scores first AND wins the game). So that exception is a combo market, and a plain fourth-quarter moneyline is one of DraftKings' "4th Quarter Markets", which include overtime.
- **BetMGM's other sentence.** "All second half and fourth quarter market selections do include overtime periods" sits under BetMGM's "(For Same Game Parlay)" heading. Paper bets are straight bets, so the straight-bet sentence governs.
- **A third-party note discounted.** An oddspapi.io post says Pinnacle prices fourth quarters on the overtime clock. That contradicts Pinnacle's own rules page, and the snippet search returned from its help desk says the 4th quarter excludes overtime. The primary text is used.
- **A two-way segment moneyline that ends level is a push.** DraftKings: "settled as Push". Pinnacle: "bets on both teams will be voided". Both return the stake, which is what `segment_scores_view` (`draw_possible=False`) already does.

**The rule in code:**
- q1, q2, q3 and h1 can never include overtime, so they grade for any book.
- q4 and h2 on a game with no overtime grade for any book: every rule gives the same answer there.
- q4 and h2 on an overtime game use the book's row. A book not in the table refuses `nba_overtime_rule_unread:<book>`.

Sources: massgaming.com/wp-content/uploads/DraftKings-House-Rules-8.18.25.pdf; massgaming.com/wp-content/uploads/FanDuel-House-Rules-7.30.26.pdf; massgaming.com/wp-content/uploads/BetMGM-House-Rules-3.28.25.pdf (the Commission lists a newer 11.24.25 approval, not read); pinnacle.com/en/future/betting-rules.

## Pre-registration: the fleet dry run `[2026-10-29 20:3xZ, written BEFORE the dry run]`

**Arms (same instant, back to back):**
- **base:** a `git archive` extract of origin/main `00be7350`, which contains the double-double fix `1ec1eb2d`.
- **new:** base plus this lane's `bet_status_nba.py`.

Both run read-only from WSL `~/Syndicate`'s git, with the refresh-worker's derived env. The archive shard's line count and sha256 are read before and after.

- **H1, the archived rows grade:** under new, all 15 archived NBA segment rows grade won, lost or push. 0 still refuse `actual_is_full_game_not_*`. Each row's settled value equals an independent sum of its periods from the fleet file, computed outside the resolver.
  - FALSIFIED if any of the 15 refuses (each named) or any value disagrees with the independent sum.
- **H2, nothing else moves:** the backfill dry run's archived pass under new equals base, except that `graded` rises by the number of H1 rows in its window and their `actual_is_full_game_not_*` refusals leave `ungraded`. Every other refusal reason has an identical count in both arms. `suppressed_writes` is `{}` in both.
  - FALSIFIED on any other count change.
- **H3, the live document (diagnostic, `settle_orders`' job, not this pass's):**
  - 10 of the 11 rows grade: the 10-27 and 10-28 games.
  - MEM@POR 10-29 q4 refuses `no_nba_linescore_for_date`. That date's file is first written 10-30 10:35Z.

**Read-only.** No `--apply`. The fleet checkout, env and archive are untouched. Fleet ff/restart and any archive write are the USER's decision under the deploy locks. The armed hourly archived pass applies the grades by itself after the next fleet up that carries the code.

## Leads, not this lane's

- **WNBA linescore path collision (file backend only).** `fetch_basketball_linescores.py --leagues wnba` writes `wnba_source/data/processed/linescores_<date>.json` with `games` as a dict keyed by event id. `build_wnba_boxscores.write_linescores` writes the SAME path through `write_json_file` with `games` as a list, and `bet_status_wnba._load_linescores` requires a list.
  - On the fleet's keyvalue backend they do not meet: WNBA's writer and reader use Redis, and the fetcher writes disk.
  - On a file backend the last writer wins. If the fetcher wins, WNBA segment grading falls back to its refusal silently.
  - Unverified on any live host. The WNBA season is over.
- **NBA linescores are not in `HOT_ARTIFACT_PATTERNS`.** Settlement runs on the fleet, where the job and the refresh-worker share `~/syndicate-prod/data` (measured above), so grading does not need it. A host that settles without running the job would refuse `no_nba_linescore_for_date`, by name.

## Result: the fleet dry run `[2026-10-29 20:36:28Z-20:36:52Z (3:36 PM CDT), READ-ONLY; base = main 682ec056 extract, new = base + bet_status_nba.py sha256 f53d1650...; fleet checkout 6d6e729d untouched; 0 writes]`

**The shard did not move.** `orders_2026-10.jsonl` read 23,737 lines, `graded_from:archive` 2,033 and sha256 `28e8a39ebc90c112` both before and after. `suppressed_writes` was `{}` in both arms, for the per-row re-ask and for the backfill.

| hypothesis | prediction | read | verdict |
|---|---|---|---|
| H1 archived rows grade | 15 / 15 grade; values equal the independent sums | **15 / 15**: 4 won, 9 lost, 2 push. Every row's segment score equals the sum taken from the fleet file by a separate hand-keyed join (15 / 15 `agree=True`). Base: 15 / 15 `actual_is_full_game_not_*` | **CONFIRMED** |
| H2 nothing else moves | only `graded` rises and the six `actual_is_full_game_not_*` reasons leave | Pass candidates **44 -> 44**, graded **1 -> 16**. Outcomes `{won: 1}` -> `{lost: 9, push: 2, won: 5}`. The 1 is the double-double, already on main. The ONLY ungraded changes: `_q1` 3 -> 0, `_q2` 2 -> 0, `_q3` 1 -> 0, `_q4` 4 -> 0, `_h1` 4 -> 0, `_h2` 1 -> 0. The other seven reasons have identical counts (not_decided_yet 10, stat_not_in_feed 5, nhl ambiguous 4 / unmatched 2, ncaaf box 2, mlb rescheduled 2, soccer match 3). Stale 38 in both arms; would-grade 1 -> 16 | **CONFIRMED** |
| H3 live document (diagnostic) | 10 / 11 grade; MEM@POR 10-29 refuses `no_nba_linescore_for_date` | **10 / 11**: 4 won, 4 lost, 2 push, each equal to its independent sum. MEM@POR q4 refuses `no_nba_linescore_for_date` | **CONFIRMED** |

**Money:**
- **The 15 archived rows:** -$15.4782 on $67.48 staked. Won 4 (+$17.9918 on $26.12), lost 9 (-$33.47), push 2 ($7.89 returned).
- **The 10 live-document rows:** -$20.7993 on $68.11. Those are graded by `settle_orders`, not by this pass.

**Overtime decided none of these grades.** Two live-document games went to overtime: BKN@BOS 10-27 (5 rows) and SA@UTAH 10-28 (1 row). Every one of those rows is on q1, q2, q3 or h1, which overtime cannot reach. The q4/h2 overtime rule is exercised only by the hermetic tests so far.

**Two-way segment moneylines that ended level pushed** (HOU@SA q4 29-29; CHI@BOS q2 33-33; BKN@BOS q2 30-30, twice). That is DraftKings' and FanDuel's own rule for a two-way market, and Pinnacle voids, which also returns the stake.

**Regression:** across the 38 test files that import `bet_status_nba`, `paper_settlement`, `segment_actuals` or the linescore fetcher, 1,071 passed and 26 failed. All 26 are NCAAF (`test_bet_status_ncaaf.py` 11, `test_bet_status_football_props.py` 15). Each fails because `resolve_ncaaf_team_id("Michigan")` returns None: the registry lives under `data/`, which this worktree omits by design. None of those tests touches the NBA path. The 21 new tests fail on the unchanged resolver (mutation check) and pass on the new one.

**Apply: none needed, and none made.** The armed hourly archived pass (`PAPER_ARCHIVED_GRADING=on`, 14-day window) grades the 15 on its first tick after a fleet up that carries this code. `settle_orders` grades the live-document rows on the same up. Fleet ff/restart is the USER's decision under the deploy locks.
- **Reading owed after that up:** one `ARCHIVED_SETTLED` whose `ungraded` has no `actual_is_full_game_not_*` key, with `graded` >= 15 on the first tick.
- **Window:** the rows are 10-23..10-26, so they leave the 14-day window from 11-06. An up after that date needs `scripts/backfill_archived_paper_grades.py --apply` instead.

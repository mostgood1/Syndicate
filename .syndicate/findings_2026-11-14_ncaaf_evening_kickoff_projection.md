# NCAAF games kicking off at or after 00:00Z carry no model, pregame or live (todo #801)

- **Found** 2026-11-14 12:55 AM CST, by lane `live-totals-prob-scale`'s #780 reading. Tonight's NCAAF half had 0 rows
  to judge, and the null was checked rather than taken as a quiet night.
- **Status: TRACED, NOT FIXED.** The fix is the user's decision. Read-only throughout (fleet, nice 19).

## Measured

**The live ledger, 11-13** (`ncaaf_source/data/live_gameline_ledger/live_gameline_ledger_2026-11-13.jsonl`):
- 3 games live: FSU @ Pitt (kickoff 00:05Z), Illinois @ UCLA (02:00Z) and Houston @ Colorado (03:25Z).
- 1,438 full-game rows, all `game_state` live, from 00:10Z to 06:01Z.
- **0 priceable.** 1,423 rows were `no_two_sided_market_price` and 15 `live_resim_published_no_distribution_for_this_market`.
- Game identity matches the feed: the same OddsAPI `event_id` and the same team names, with 15-28 books on each row.

**Capture is fine** (`ncaaf_source/tracking/book_quotes/2026-11-13.jsonl`): each game has 1,967-2,849 in-play
sportsbook rows per market, and quotes run to each game's end.

**Priced share per night** (full-game totals / spreads / h2h):

| nights | priced |
|---|---|
| weeknights 10-27, 10-29 | 74%, 71% |
| weeknight 10-30 | 50% (the 02:48Z kickoff priced 0) |
| weeknights 11-03, 04, 05, 06, 10, 11, 12, 13 | **0% on every night** |
| Saturday 10-31 | 54%: 39 games priced; the 5 first seen at 00:14Z or later priced 0 |
| Saturday 11-07 | 44%: 13 of the 14 games that priced 0 were first seen at 00:41Z or later |

**The served board, 11-14** (`/api/board/book-grid?sport=ncaaf&date=2026-11-14`, read 06:5xZ; 2,000 of 2,962 rows,
the server's cap). Full-game h2h / spreads / totals rows:
- **Kickoff on 11-14 UTC** (before 6 PM CST): 262 of 262 carry a `projection`.
- **Kickoff on 11-15 UTC** (6 PM CST or later): **0 of 112**. That is 18 of tonight's games: 11 at 00Z, 3 at 02Z,
  3 at 03Z and 1 at 04Z.

**Why "since 11-03":** daylight saving time ended on 11-01. Weeknight 7 PM ET kickoffs moved from 23:00Z to 00:00Z,
which is the next UTC date.

## Cause (traced to file:line, not yet reproduced in a test)

1. `syndicate/features/shared/board_enrichment.py:2029-2037` builds the NCAAF index with
   `load_ncaaf_game_projections(selected_date)`, then calls `attach_ncaaf_game_projections(grid, index,
   selected_date=selected_date)`. `selected_date` is the board's Central date.
2. `syndicate/features/ncaaf/game_projections.py:701-704` skips any row whose UTC `commence_time[:10]` is not
   `selected_date`, **before** `index.lookup`.
   - A game kicking off at or after 00:00Z sits on the next UTC date, so it is skipped.
   - Yet the index holds it: `load_ncaaf_game_projections` keeps every game within ±1 day
     (`_KICKOFF_DATE_TOLERANCE_DAYS`, :228), keyed on CFBD's own date.
   - The filter's docstring says "ATTACHMENT IS UNCHANGED by this: a skipped row would have failed `index.lookup`
     on that date anyway". That is false for exactly these rows.
3. With no `projection`, there is no `market_fair_prob_over` (`_price_against_market`, :639). The live join reads
   its market price from there (`live_gameline_join.py` :2568 / :2583 / :2634) and refuses
   `no_two_sided_market_price` (:1434 / :1726).
4. **Introduced** by `a81bf816b` (2026-09-03, "ncaaf: scope the projection counters to the call's date"), a
   counters fix.
5. **The segment join has the same filter:** `syndicate/features/ncaaf/segment_projections.py:435-437`.

## Size

- **Since 09-03:** every NCAAF game kicking off at or after 00:00Z has shown prices with no model on the board
  (Proj / Edge empty), and its live lines have priced 0. That covers full game and segments.
  - Before 11-01, that was 8 PM ET and later.
  - Since 11-01, it is 7 PM ET and later, which is every weeknight game.
- **Picks:** NCAAF picks are suppressed by `football/pick_gate.py` anyway, so no pick changes. What is lost is the
  board's model view and every live NCAAF price for those games.
- **#780:** the NCAAF half of the reading can only come from games kicking off before 6 PM CST until this is fixed.

## Fix shape (not built)

Filter on the date the INDEX matched rather than the row's UTC date: keep the per-date counter scoping, but let a row
through when its UTC date is within the index's tolerance and `index.lookup` resolves it to a game on
`selected_date`. Apply the same change to `segment_projections.py:435-437`.

Tests:
- off != on, with a 00:05Z kickoff on a Central-date board;
- the 7-day-gap miss (`test_lookup_is_date_scoped`) still holds;
- a row is not counted on two dates.

Loading it needs a fleet ff and a refresh-worker restart, which is where the board build runs.

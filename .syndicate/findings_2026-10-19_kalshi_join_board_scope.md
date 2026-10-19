# Kalshi join scope: shortlist-only vs every fixture's game lines (design note, "cause B") — 2026-10-19

Session 436c79e2. Design note only: no code changed. Follows the UEFA Kalshi-join diagnosis
(`log/2026-10-19.md`, "cause B") and Fix A (`71631544`, lane `kalshi-event-scoped-codes`).

## The design today

`venue_odds_loop._maybe_kalshi_board_coverage` (every 600 s, `SYNDICATE_KALSHI_BOARD_COVERAGE_SECONDS`) and
`intelligence_state`'s fast capture call `kalshi_odds_refresh.join_to_board(markets, rows)` with
`rows = read_layer2_shortlist(day)["rows"]` for today .. +2. The join has three side effects, and all of them
inherit the shortlist's scope:

1. `_capture_kalshi_quotes`: matched Kalshi prices -> `book_quotes` -> the book grid / board. **A fixture with no
   shortlist row for that market never gets a Kalshi price.**
2. `_record_board_demand`: which series the next Kalshi refresh fetches and how the working set is trimmed.
3. The `[kalshi_odds] BOARD_JOIN` coverage line and `portfolio_commit`'s Kalshi resolvers (`join_kalshi_to_board`
   is called there separately, against the rows it commits).

## Measured (fleet replay, read-only)

Kalshi markets fetched 2026-10-19 18:45:02Z (8,645). The fleet checkout was `71631544` (includes Fix A).
Real `join_kalshi_to_board`, run under the worker's own environment. Scope: **game lines only** (h2h,
totals, spreads); props were not measured. Scripts: `C:/tmp/scope_replay.py` (`.sh`).

### Arm 1: shortlist vs shortlist + the served book grid's game-line rows (every sport)

| day | shortlist rows | + grid rows | matches | gained | lost | join time |
|---|---|---|---|---|---|---|
| 10-19 | 4,214 | 529 | 570 -> 739 | **+169** | 0 | 4.8-8.0 s -> 6.6-7.5 s |
| 10-20 | 4,617 | 632 | 397 -> 567 | **+170** | 0 | 4.8-7.2 s -> 4.9-6.7 s |
| 10-21 | 2,734 | 617 | 511 -> 642 | **+131** | 0 | 4.4-5.4 s -> 6.8-7.5 s |

- **Gains by sport** (10-20): soccer +134, NFL +36. By market: h2h 92, totals 67, spreads 11.
- **New fixtures that gained any Kalshi match:** 10-19 soccer 28, NFL 1; 10-20 soccer 25, NFL 13; 10-21 soccer 15, NFL 13.
- MLB / NHL / WNBA: +4 / 0 / 0. NBA / NCAAF / NCAAB: the grid served 0 rows today, so they were not measured.
- **Cost: inside run-to-run noise.** Two runs per arm overlap, and the join stays at about 5-8 s.
- The grid is itself a NARROWED pool. For UEFA it holds only rows Kalshi already joined, so this arm understates the gain.

### Arm 2 (the UEFA ceiling): shortlist + EVERY UEFA fixture's OddsAPI game lines

These are the 492 side rows of `{ucl,uel,uecl}/api/odds/game_odds_current.csv`.

| day | UEFA fixtures with a Kalshi match, shortlist -> all fixtures | UEFA matches |
|---|---|---|
| 10-20 | UCL 15 -> **18**, UEL 11 -> **18**, UECL 11 -> **17** (of 18 each) | 55 -> **299** |
| 10-21 | UCL 6 -> 9, UEL 10 -> **18**, UECL 14 -> **17** | 43 -> 254 |

- The only UEFA fixture still missing is Red Star v Copenhagen: Kalshi's `Crvena Zvezda` / `Copenhagen` have no alias.
- UCL on 10-21 is partial because most UCL games are on 10-20/21 and fall outside that day's date window. That is the join's date rule, not a scope miss.
- New refusals rise as expected and are all correct refusals:
  - `three_way_no_leg_is_not_a_board_bet` +212: a NO leg is never a board bet;
  - `moneyline_other_club_has_its_own_contract` +105;
  - `spread_line_orientation_mismatch` +16.

## Options

- **(a) Keep it shortlist-only (today).** UEFA fixtures that the shortlist does not carry stay without a Kalshi price on the board.
- **(b) Game-line rows from every fixture, all sports, behind a flag.**
  - What: hand `join_to_board` the shortlist PLUS one side row per (event, market, line, side) for h2h / totals / spreads, built from each sport's current game-odds rows. Props stay shortlist-only.
  - Measured: +23-43% Kalshi matches, 0 lost, no measurable join-time cost.
  - Unmeasured: the effect on `_record_board_demand` (more series demanded -> more Kalshi fetch volume and a larger working set) and on `book_quotes` growth (+~150 rows per join cycle, every 600 s).
- **(c) Same as (b), soccer / UEFA only.** Smaller blast radius, but the NFL gain is about as large per fixture as soccer's.

## Recommendation

**(b), default OFF** (`SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES`), tested off != on.

- Turn it on only after the `_record_board_demand` effect is read off one fleet cycle: series demanded and the Kalshi working-set size, before and after.
- Files: `pipeline/venue_odds_loop.py` (unclaimed) builds the row set.
- `pipeline/intelligence_state.py` (held by `min-ev-tuner-shadow`) carries the fast-capture caller; that one can stay shortlist-only, or be borrowed later.
- `odds_book_quotes.py` is held by `book-quotes-splice-repair`, but the change should need no edit there.

## What this does NOT establish

- **Props:** not measured.
- **NBA / college basketball / NCAAF:** no grid rows today.
- **The served-board effect:** this is a replay of the join, not of the board.
- **Whether more Kalshi prices on non-shortlisted rows change any recommendation:** they become price-shopping
  inputs, not picks.

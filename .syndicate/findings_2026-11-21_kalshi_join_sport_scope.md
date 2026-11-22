# Kalshi join sport scope — build + PRE-REGISTRATION (lane `kalshi-join-sport-scope`, 11-21)

User, in this session's chat, 11-21 about 6 PM CST: "Yes, build it" (to "Build the fix for Kalshi markets matching
the wrong sport's game?"). That covers **building**. Loading `on` is a **BETTING CHANGE** (it changes which live bets
are placed). It loads only in a betting-change window, on the user's yes. Counts only (the repo is public).

## Why (F27, `findings_2026-11-21_portfolio_monitor.md` 3:08 PM and 3:32 PM)

- Live order `373a43d7` was a men's NCAAB bet (UC Irvine @ San Diego, tip 21:30Z). It went to
  `KXNCAAWBGAME-26NOV21UCIUSD-UCI`, the WOMEN'S market (tip 03:00Z). It was retired unfilled at 21:32:16Z (venue
  canceled, 0 contracts), and no cancel request came from any role.
- **Cause:** `kalshi_board_join._resolve_event` matched the market's club blob against `_distinct_games(board_rows)`.
  That is every game on the cross-sport board, with no sport. The sport only picked the club map.
  - With only the men's game on the board, the women's market resolved `ok` onto it.
  - With both games on the board, it read `ambiguous`, and the right bet was refused.
- The quote fan-in already scopes by sport (`venue_quote_fanin._distinct_games(rows, sport)`). Only the order join
  did not.

## Baseline, measured before predicting

- **Same sport vocabulary on both sides.** Over every archived Kalshi order row on the fleet
  (`execution_ledger_archive/orders_2026-*.jsonl`, `book == kalshi`), the row's `sport` and
  `sport_for_series(<ticker series>)` agree on **21,349** rows in 9 sports (soccer as `soccer`, women's college
  basketball as `wncaab`). They differ on **3**, all `ncaab` rows on `KXNCAAWBGAME`, paper. Add the 1 live row above.
  11,064 rows have a series that a bare process cannot map (discovered prop series), and the scope leaves those alone.
- **The ceiling on what `on` can newly resolve.** refresh-worker `KALSHI_BOARD_JOIN`, 11-21 22:56Z to 11-22 00:18Z:
  `event_matches_two_games` read **13 to 23** markets per build. That is about 17,300 markets, 322 to 1,226 matched.
  Some of those are doubleheaders or collided club codes, not cross-sport pairs, so it is an upper bound.

## What was built

- **Code:** `syndicate/features/shared/kalshi_board_join.py`.
  - `_distinct_games` carries each game's `sport`.
  - `_resolve_event` runs one body (`_match`) over either list.
  - `_own_sport_games` keeps the market's sport plus any game with no sport. A market with no sport filters nothing.
  - `_sport_scope_would` gives the `report` comparison.
  - `join_kalshi_to_board` counts per market, returns `sport_scope`, and prints one line per build:
    `[kalshi_board_join] SPORT_SCOPE mode=... would_change=N by_kind={...}` (plus `samples=` when N > 0).
- **Switch:** `SYNDICATE_KALSHI_JOIN_SPORT_SCOPE`.
  - `report`: absent, blank and unknown all read report. Today's answer, byte-identical, plus what `on` would do.
  - `on` / `1` / `enforce`: scoped.
  - `off` / `0`: no check.
  - The mode is part of the resolver's memo key.
- **Report only pays for a second match where the answer can differ:**
  - `other_sport_game`: today's `ok` lands on another sport's game.
  - `ambiguous_across_sports`: today's `ambiguous`, on a board holding another sport's games.
  - Narrowing the list cannot turn `no_match` into a match. Nor can it move an `ok` that is already on the market's
    own sport.
- **Cost:** `match_event_blob` over a 400-game board takes 5.7 ms per blob (local). `on` matches a subset, so it is
  cheaper than today.
- **Tests:**
  - `tests/test_kalshi_join_sport_scope.py`: 23 pass.
    - The 11-21 tickers both ways.
    - The both-games pair.
    - Own-sport untouched in every mode.
    - The memo.
    - Join-level `off != on` (matched 1 -> 0, and the ambiguous pair 0 -> 1 on the right game).
    - `report` pairs exactly what `off` pairs.
  - `tests/test_kalshi_join_resolve_memo.py`: one key-set assertion gains `sport`.
- **Regression set** (32 Kalshi join / fan-in / venue suites): 24 failures, the same 24 with main's own copy of the
  file. They are pre-existing and not this lane's:
  - `test_engine_paper_m3` 13;
  - `test_kalshi_board_join` 5, including the moneyline coupling test;
  - `test_kalshi_fanin_college_naming` 3;
  - `test_venue_fanin_game_identity` 2;
  - `test_kalshi_series_competition_identity` 1.

  Nothing else changed: the one new failure was the key-set test, now updated.
- **Betting change of the code as landed: no.** The default `report` places exactly today's bets.

## Predictions: `report`, at the first fleet load that carries this commit (refresh-worker)

- R1: every build prints `SPORT_SCOPE mode=report`. **If it is absent, the code is not loaded.**
- R2: `by_kind.other_sport_game` is <= 5 markets per build on a normal slate. This is the F27 class: 4 rows in 21k
  archived, all one game.
- R3: `by_kind.ambiguous_across_sports` <= the same build's `event_matches_two_games`. It cannot exceed it, by
  construction.
- R4: `matched` and `reasons` are unchanged by the load. The tests prove this exactly; on the fleet only the ranges can
  be compared, because the board moves between builds.

## Predictions and kill rules: the `on` load (a betting-change window, on the user's yes)

Env: one GLOBAL line `SYNDICATE_KALSHI_JOIN_SPORT_SCOPE=on` in `local_production.env`, so every role that joins
(refresh-worker's commit, the odds refresh, the shadow scripts) has the same scope. Then a drained `down`/`up`, and a
preflight with `--betting-change yes`. Read at +24 h and +7 d.

- P1, the defect is gone: **0** new Kalshi rows, live or paper, whose row `sport` differs from the sport of their
  ticker's series. Same query as the baseline, rows with `submitted_at` after the load. **KILL** (remove the line,
  drained `down`/`up`) on any.
- P2, the gain is bounded: per build, `matched` rises by at most the last pre-load `ambiguous_across_sports`, and
  `event_matches_two_games` falls by about that.
- P3, nothing of its own sport is lost: `event_not_on_our_board` rises by at most the last pre-load
  `other_sport_game`. **KILL** if `matched` falls by more than that across 3 consecutive builds on a comparable
  slate.

**Revert:** remove the line, then a drained `down`/`up`. Absent is `report`, which is today's behaviour.

## Log

- 11-21 6:32 PM CST: built and tested locally. The pre-registration was written before any load. Landed on main
  default `report`. The fleet is unchanged until someone fast-forwards it.

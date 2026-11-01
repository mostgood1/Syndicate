# NHL never reaches the paper book: no NHL DecisionRecord carries a Kalshi or Polymarket price `[2026-10-31, lane nhl-venue-price-gap, session e32fef1a]`

**User, verbatim:** "proceed next steps". The lead is from log 2026-10-30 23:15Z: "no NHL bet in any strategy, although Fair v1 passed NHL game and NHL props".

**Nothing was changed.** This was a read-only diagnostic: fleet files and logs, plus Kalshi's public, unauthenticated market API. It changed no code, env or fleet setting, and spent 0 OddsAPI credits.

## Hypothesis (recorded in the lane before testing) and result

- **Hypothesis:** "NHL Layer 2 rows never receive `quote.book_prices` kalshi or polymarket because the venue price fan-in or board join does not cover NHL (series not registered, or the join refuses NHL rows), NOT because the venues list no NHL markets."
- **Result: CONFIRMED, with two mechanisms.**
  - NHL props are blocked at Kalshi SERIES REGISTRATION.
  - NHL game lines are blocked at the Kalshi QUOTE CAPTURE.

## Per-stage counts

All readings were taken on 2026-10-31 between 22:08Z and 22:18Z. Fleet HEAD was `87ecf730`.

| # | Stage | NHL | For comparison |
|---|---|---|---|
| 1 | **Kalshi lists** (public API, `status=open`) | `KXNHLGAME` 94, `KXNHLSPREAD` 66, `KXNHLTOTAL` 137; **`KXNHLPTS` 200+, `KXNHLGOAL` 200+, `KXNHLAST` 200+** (page cap 200; today's games, e.g. `KXNHLPTS-26OCT31BUFLA-...`) | |
| 2 | **Series registered and fetched** (`kalshi_catalogue`) | game, spread and total series YES; **prop series NO**. The refresh-worker log never names `KXNHLPTS`, `KXNHLGOAL` or `KXNHLAST`. | NBA and NFL props are fetched |
| 3 | Kalshi refresh keeps (`TRIM_BY_SPORT` 22:12:49Z) | 546 (demand 943) | NFL 1,184, NBA 911 |
| 4 | Fan-in offered to Layer 2 (`VENUE_REPRICE_KEYS` 21:28:38Z) | Kalshi 91 keys, period totals only (`totals_p1`); Polymarket 425 (h2h, totals) | NFL Kalshi 1,335 (player props) |
| 5 | Layer 2 stamped (`selected_by_sport`) | Polymarket 25, Kalshi 0. A stamp sets `price_source`; it does **not** write `book_prices`. | NFL Polymarket 60, Kalshi 19 |
| 6 | Kalshi `QUOTE_CAPTURE` to `book_quotes` (22:10:36Z) | matches include NHL; **appended 0**. Game lines are captured only for `_GAME_LINE_CAPTURE_SPORTS = {"soccer"}`. | soccer 14 that tick |
| 7 | `book_quotes` exchange rows (shards 10-31 and 11-01) | **0 of 71,341** (14 books, no kalshi, polymarket, prophetx or novig) | NFL Kalshi props 3,433; NBA Kalshi props 806; NCAAF 161,723 via OddsAPI `us_ex`; soccer 11,726 |
| 8 | DecisionRecord venue price (`quote.book_prices`, `decision_record._prices` l.770-779) | **0 of 618** (606 props, 12 game rows) | NFL 158 of 1,056; NCAAF 222 of 963; soccer 112 of 1,120; NBA 59 of 1,072 |
| 9 | Paper candidates (`ev_lb_funnel_read.py`, the paper job's own path, 2 newest record files) | **0 of 1,230** | NFL 379; soccer 342; NCAAF 328; NBA 59 |

**First zero stage:**
- NHL props: **stage 2**.
- NHL game lines: **stage 6**. They also never get `us_ex` from OddsAPI, so NHL game lines carry no Pinnacle either (`state_venues.md` table).

## Mechanism 1: NHL prop series are never registered (`kalshi_catalogue.py`)

- `auto_series_from_catalogue` registers a player-prop series only when its SERIES title matches `_PLAYER_PROP_TITLE`, i.e. ends in `player <stat>`.
- Kalshi's own titles, read 22:17Z from `/series/<ticker>`:

  | Series | Title |
  |---|---|
  | `KXNBAPTS` | "NBA Player Points" (passes) |
  | `KXNFLREC` | "Pro Football Player Receptions" (passes) |
  | **`KXNHLPTS`** | **"Pro Hockey Points"** |
  | **`KXNHLGOAL`** | **"NHL Goalscorer"** |
  | **`KXNHLAST`** | **"Pro Hockey Assists"** |

- None of the three NHL titles says "Player", and `SERIES_SPORT` hand-registers no NHL prop series.
- The market titles are the usual player-threshold grammar ("Zach Benson: 3+ points", "Zach Metsa: 1+ goals", "Joel Armia: 2+ assists").
- `market_keys._HOCKEY` already maps points, assists and goals. Its 08-25 note expected `KXNHLPTS` / `KXNHLANYGOAL` / `KXNHLSAVES`; today `KXNHLANYGOAL`, `KXNHLSOG` and `KXNHLSAVES` list 0 open markets, and the live goal series is `KXNHLGOAL`.
- This is the same shape as the gaps those files already record: a gate on a series TITLE that the venue's wording misses, which reads as "the venue lists nothing".

## Mechanism 2: Kalshi NHL game lines are matched but never written (`odds_book_quotes.py:169`)

- `_GAME_LINE_CAPTURE_SPORTS = frozenset({"soccer"})`.
- The props-only bound exists so that a direct venue row cannot alternate with OddsAPI's copy of the same market. Its own note says the premise is sport-specific and false where OddsAPI writes no exchange rows for the sport.
- **NHL meets that condition today:** 0 exchange rows of any kind in 71,341 NHL quotes.

## What fixing it is worth

- **NHL props carry Pinnacle all window** (`state_venues.md`; NHL's own ten-book list includes Pinnacle). So every NHL prop paper bet would be sharp-gradable, unlike 72% of today's graded bets.
- Today's shortlist holds 606 NHL prop records and 12 NHL game records.
- NHL's paper volume after a fix is NOT estimated here. It depends on how many NHL rows clear `ev_lb` / `net_floor_719` at Kalshi's prices, and that is unread.

## Fix options (none made)

**F1, NHL props (0 OddsAPI credits):**
- Hand-register `KXNHLPTS`, `KXNHLAST` and `KXNHLGOAL` as `nhl` in `kalshi_catalogue.SERIES_SPORT`, each with its seen date and title, the file's documented pattern.
- Then check every downstream hop with a test:
  - the join's market key for NHL board rows ("POINTS" / "ASSISTS" / "GOALS");
  - `book_quote_prop_market("nhl", ...)`, so that Kalshi rows share a key with the Pinnacle rows the grader reads;
  - the `TRIM_BY_SPORT` bound of 6,000, which these series would compete for with other sports' markets.
- Nothing claims `kalshi_catalogue.py`.

**F2, NHL game lines (0 OddsAPI credits):**
- Add `nhl` to `_GAME_LINE_CAPTURE_SPORTS`, keeping the stated re-check condition.
- `odds_book_quotes.py` is claimed by lane `book-quotes-splice-repair`, so this needs a section claim or a loan.

**F3, optional, costs credits:** NHL game-line regions `eu` (Pinnacle) and/or `us_ex` (OddsAPI's Kalshi/Polymarket copies). Adding `us_ex` would re-create exactly the collision F2 relies on being absent, so F2 and F3's `us_ex` are alternatives, not a pair.

**Live-money note:**
- Once NHL rows carry Kalshi prices, the LIVE portfolio commit can also price, and so order, NHL Kalshi markets, inside every existing cap.
- That is a live behaviour change. A fleet deploy needs the user's yes, and its first `STAKE_BAND` / order lines on NHL should be read.

## Not checked

- Polymarket NHL props: Polymarket offered NHL game markets only (h2h, totals).
- Whether NHL Kalshi props are liquid enough to fill.
- NHL paper grading end to end.

## Fix on main, 2026-11-01 (`4520b47ae`); NOT on the fleet

**User, verbatim:** "Yes, build both", on "Build the two NHL fixes?". The same message said the game-line fix needs a claim on part of `odds_book_quotes.py`.

**What changed:**
- **F1, props** (`kalshi_catalogue.SERIES_SPORT`): `KXNHLPTS`, `KXNHLGOAL` and `KXNHLAST` are registered as `nhl`. Titles and sample markets were re-read 2026-11-01T15:52Z from the public listing:

  | Series | Title | Sample market | Open |
  |---|---|---|---|
  | `KXNHLPTS` | 'Pro Hockey Points' | 'Tim Stutzle: 3+ points' | 200+ |
  | `KXNHLGOAL` | 'NHL Goalscorer' | | 200+ |
  | `KXNHLAST` | 'Pro Hockey Assists' | | 143 |

- **F1 needed a second edit, found while building it.** NHL's `book_quotes` shard files props under the grid CODE: on the fleet 11-01 all 10,700 prop rows (Pinnacle's included) read `POINTS` 2,639, `GOALS` 2,480, `ASSISTS` 1,591, `SOG` 3,986, `SAVES` 4. The Kalshi capture would have written `player_points`. That is the NFL 2026-09-10 defect: a one-book grid row beside Pinnacle's instead of a cell in its row.
  - `book_quote_prop_market` now relabels NHL props to those codes. The source is `nhl.prop_projections._MARKET_CODES` mapped through `market_keys`.
  - NFL's labels are unchanged.
- **F2, game lines** (`odds_book_quotes._GAME_LINE_CAPTURE_SPORTS`): now `{soccer, nhl}`.
  - Both the Kalshi capture and the Polymarket capture (`portfolio_commit`) read this one predicate, so Polymarket NHL game lines are captured too.
  - The re-check condition is restated in the comment: adding `us_ex` to NHL game-line regions means removing `nhl` here.
  - Borrowed from lane `book-quotes-splice-repair` (its owner session is gone). Scope: the game-line set and the prop relabel only.
- **Guard** (`kalshi_odds_refresh._capture_kalshi_quotes`): a match from a period series (`segment_for_series != "full"`) is skipped, and the count is logged as `segment_skipped=` on `QUOTE_CAPTURE`.
  - Why: a match carries no segment and `_normalize` defaults one to "full", so a first-half total would be logged as a full-game total.
  - Fleet log 10-31 08:44Z..11-01 15:51Z: the only segment matches were `h1->KXNCAAF1HTOTAL`, in 95 of 389 joins, and NCAAF game lines are not captured. So this drops nothing today.

**Tested** (`tests/test_kalshi_nhl_venue_prices.py`, 23 tests; every check runs both with the change and without it):
- registration, and that the title gate alone registers none of the three;
- classification of the real titles;
- the join against board rows spelled `POINTS` / `GOALS` / `ASSISTS`;
- the `build_book_grid` merge with Pinnacle (the control reproduces the split);
- capture of NHL props and NHL h2h, with MLB h2h still dropped;
- the segment guard, mutation-checked: with the guard off, the 1.5 half total is written.

374 related tests pass.

**Fleet facts read 2026-11-01 15:45-15:51Z (fleet `87ecf730`):**
- `QUOTE_CAPTURE` lists `nhl` in `sports` every tick on the today-board, with no `nhl` in `appended_by_sport`. These matches are game lines, since no NHL prop series was registered.
- `TRIM_BY_SPORT`: NHL demand 642 and kept 559, within a full 6,000.

**NOT measured, owed after a fleet update:**
1. `TRIM_BY_SPORT kept_by_sport.nhl` and whether the prop series survive the trim. They compete for the 6,000 bound, which was full at every read.
2. `QUOTE_CAPTURE appended_by_sport.nhl` > 0.
3. Kalshi NHL rows in `book_quotes`, and whether they merge with the sportsbook rows on the grid.
4. NHL DecisionRecords with a venue price (> 0 of N).
5. NHL paper candidates.
6. The first live `STAKE_BAND` / order line on NHL.

**Live-money note (unchanged):** once live, the portfolio commit can price, and so order, NHL Kalshi markets, inside every existing cap. An ff to any SHA at or after `4520b47ae` therefore needs the user's yes.


## Fleet reading, 2026-11-01 17:18Z (fleet `18090e38e`, refresh-worker restarted 16:53Z)

The fix is LIVE. It reached the fleet in another lane's ff and loaded in another lane's claimed restart. The full entry is in `deploys.md` 2026-11-01 17:18Z.

**The six owed checks:**

| # | Check | Result |
|---|---|---|
| 1 | Trim | Props fetched 16:59:25Z (659 markets). NHL kept 908 then 555: they live in the leftover pass, and the working set at 17:05Z held all 659. NCAAF lost slots (1,107 -> 754) but gained venue-priced records. |
| 2 | Capture | NHL appended 22 (game), then 61 and 340; Polymarket NHL 7. `segment_skipped=0`. |
| 3 | Grid | 423 Kalshi rows under `GOALS` / `POINTS` / `ASSISTS` / h2h / spreads. 352 grid rows carry a venue price: 349 alongside sportsbooks, 140 alongside Pinnacle, 3 venue-only (spreads). |
| 4 | DecisionRecords | NHL **329 of 486** with a venue price (was 0 of 608). |
| 5 | Paper | 329 candidates, 200 eligible. **0 qualify under `ev_lb`** (best -0.33%); 80% have no raw edge at Kalshi's price. Paper-job bookings not yet read. |
| 6 | Live | No NHL sizing or orders to 17:17Z. |

**What this settles:** "no paper strategy can book NHL" was a plumbing defect, and it is fixed. Whether NHL gets booked is now the strategies' call, on prices. On this first build, `ev_lb` declines all of it.

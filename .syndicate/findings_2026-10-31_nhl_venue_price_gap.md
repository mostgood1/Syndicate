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

# Venue prop closing marks: the close was captured, and lost at RESOLUTION

Lane `venue-prop-close-coverage`, session aba784f3 (side session of local_81601787), 2026-10-22.
Fix: `aa06d5a1` on origin/main. **NOT on the fleet** (fleet checkout `36eb357b`; ff + refresh-worker restart = user decision).

## Question

Settled Kalshi / Polymarket MLB prop orders almost never carried a same-book `closing_mark.clv_pct`
(2026-10-19: kalshi 49 of 266, polymarket 1 of 95; NCAAF 182 of 359 and 119 of 245). Lane
`min-ev-tuner-shadow` and the `#704` sizing reads grade cells on same-book CLV, so those cells could
never move. Which stage loses the close: venue prop capture, the opening key join, or close resolution?

## Substrate

- **Ledger:** `execution_ledger.full_history_orders()` on the fleet, read 2026-10-22 ~11:35 CDT,
  in WSL under the refresh-worker's derived env (`local_production.derive_role_env`) at `nice -n 19`.
  Read-only. Subset kept: mlb / ncaaf / nfl.
- **Closes:** the fleet's own odds history (`load_odds_history_payload_for_sport`), clv openings, and
  `odds_book_quotes` shards plus state sidecars, all read from `~/syndicate-prod/data`.
- **Replay:** `order_clv.clv_for_orders` run per `selected_date` over every settled `paper*` MLB order
  (901 orders, 14 dates, 10-03..10-18). It ran twice on the same inputs: once on the fleet code
  (`~/Syndicate`, `36eb357b`) and once on the fix (worktree, content identical to `aa06d5a1`).
  The old-code replay reproduces the stamped ledger to within 1 to 6 rows per cell. The drift comes
  from sidecar `last_seen` confirmations made after the original stamps.
- **Coverage:** MLB venue orders settled on 13 dates (kalshi 10-03..10-18, polymarket 10-03..10-15).
  No MLB venue order has settled since 10-18. The World Series games are the forward population
  (17 `paper:kalshi:ladder` orders pending for 10-23).

## Before: stamped reason breakdown (fleet ledger, settled MLB)

| venue | kind | n | same-book | of which at the order's own book | main refusals |
|---|---|---|---|---|---|
| paper:kalshi | prop | 209 | 5 | 5 | no_pregame_observation 106, book_agnostic_close 61, line_mismatch 19, no opening 14 |
| paper:kalshi | game | 57 | 44 | 34 | no opening 6, opened_in_play 3 |
| paper:polymarket | prop | 89 | 0 | 0 | book_agnostic_close 36, no_pregame_observation 33, no opening 14, line_mismatch 6 |
| paper:polymarket | game | 6 | 1 | 0 | opened_in_play 3, no opening 2 |
| **paper:kalshi total** | | **266** | **49** | **39** | |
| **paper:polymarket total** | | **95** | **1** | **0** | |

(For comparison, NCAAF: kalshi 183/363, polymarket 119/245. NCAAF has no odds history, so it has always
gone straight to the quote log.)

## The stage, named: CLOSE RESOLUTION

1. **Capture: present.** `odds_book_quotes` holds `source=venue_direct` Kalshi and Polymarket prop quotes
   keyed by the opening's own identity fields. Example: Ozzie Albies hits over 0.5, 2026-10-03, has
   thirteen pregame Kalshi quotes, the last at 13:59Z (-156) before the 20:00Z first pitch.
2. **Opening join: mostly fine.** 181 of 209 kalshi and 75 of 89 polymarket prop orders join an opening.
   The rest are a separate residual (below).
3. **Resolution: lost here.** `compute_clv_for_date` asked the quote log only when odds history had
   **no market at all** (`_QUOTE_FALLBACK_REASONS = {"no_market_in_history"}`). Odds history keys a
   prop as `player_name=ozzie albies|market=batter_hits|selection=over`, with no event and no book.
   So for a prop it always "has the market", and its best possible answer is `book_agnostic_close`,
   which the headline never counts. On 10-03 the series started at 22:13Z, two hours after first
   pitch, which produced `no_pregame_observation`.
   - **Proof by direct probe** (`_quote_closes_for_openings` on the stamped orders' own openings):
     - Kalshi: the quote log held a same-book KALSHI close for 97 of the 106 `no_pregame_observation`
       rows, 55 of the 61 book-agnostic rows, and 17 of the 19 `line_mismatch` rows.
     - Polymarket: it held a same-book close for 31 of 33, 34 of 36, and 6 of 6.

A second defect surfaced on the way, in the same signal:

4. **`order_clv` called a cross-book pair "same-book".** For a game market at a book that history does
   not track, the opening resolves same-book through `book_prices`: our DraftKings price against
   DraftKings' close. That pairing is unbiased for the OPENING. But `order_clv` grades the ORDER's own
   fill (at Kalshi, Novig, ProphetX) against that DraftKings close and kept the label `same_book`.
   - Ledger-wide: 110 of 5,729 same-book marks were cross-book.
   - On settled MLB: paper:kalshi 10 of 49, paper:novig 33 of 38, paper:prophetx 26 of 48,
     paper 36 of 96.
   - `min_ev_tuner._clv` counts every same-book mark as unbiased evidence.

## Fix (`aa06d5a1`)

- **`clv_join`:** closes are RANKED: same-book at the opening's own book > same-book at another book
  we priced > a biased scope.
  - The quote log is asked whenever history's best is below own-book. That covers props history
    refused (except the clock refusals `opened_in_play` / `not_started`), book-agnostic props, and
    game markets resolved through another book or a different-book close.
  - It replaces history only with a STRICTLY higher rank whose close was observed after the opening.
  - A market history lacks still takes the quote log's answer whole, exactly as before.
  - The report's `book_quotes_fallback.replaced_history` counts what each replacement displaced.
- **`order_clv._order_scope`:** a same-book close at a book other than the order's fill book is
  `different_book_close` for the order.
- **Tests:** `tests/test_clv_join_venue_props.py` (12) and 4 added to `tests/test_order_clv.py`.
  - On the old code, 5 of the 12 venue-prop tests and 2 of the 4 order tests fail.
  - Two mutations were caught: dropping the arrow-of-time guard, and a `>=` rank comparison (the
    tie test).
  - 468 passed across the clv / paper_settlement / min_ev_tuner / position_marks / portfolio_commit
    suites.

## After: replay on the fixed code (same 901 orders, same inputs)

| venue | kind | n | same-book before (own-book) | same-book after (all own-book) |
|---|---|---|---|---|
| paper:kalshi | prop | 209 | 5 (5) | **174** |
| paper:kalshi | game | 57 | 44 (34) | 44 |
| paper:polymarket | prop | 89 | 0 (0) | **71** |
| paper:polymarket | game | 6 | 1 (0) | 1 |
| **paper:kalshi total** | | **266** | 49 (39) | **218 (82%)** |
| **paper:polymarket total** | | **95** | 1 (0) | **72 (76%)** |
| paper:novig | game | 54 | 38 (5) | 52 |
| paper:prophetx | game | 66 | 48 (22) | 51 |
| paper (unrestricted) | all | 420 | 96 (60) | 345 |

Remaining kalshi props (35 of 209):
- 14 have no opening recorded (residual 1).
- 12 have a different-book close only (no Kalshi quote for that line).
- 4 are `quotes_unchanged_since_open`.
- 4 are `opened_in_play`.
- 1 is book-agnostic.

Remaining polymarket props (18 of 89):
- 14 have no opening recorded.
- 2 are `quotes_unchanged_since_open`.
- 2 are book-agnostic.

Same-book CLV on the 245 venue prop rows now graded: mean **+1.74 pt**, median +0.94, 131 of 245 beat
the close. **Descriptive only:** not event-clustered, paper fills at the quoted price, and not a
verdict on any cell.

Cost: the quote pass per MLB date took 0.3 to 1.8 s and parsed at most 102,530 rows (10-03, two
shards), against about 0.3 to 0.7 s before. It runs on the settlement path and on board builds for
started games only.

## Residuals (not fixed here)

1. **No opening is ever recorded** for 78 settled MLB orders: paper 33, kalshi 20, polymarket 16,
   prophetx 9. 36 of them fall on 10-11, and the rest are spread out. None appears in any openings
   file within ±3 days. Example: a Kalshi `totals` first5 3.5 order whose event has openings at other
   books and lines. This is the opening-key-join stage, and a different mechanism: the venue book
   placed a (market, line, book) the board never published as an opening.
2. The 90 settled LIVE `polymarket` MLB orders (08-25..09-24) carry NO `closing_mark` at all. They
   predate the stamp and lie outside the 14-day straggler window. History only.

## Owed

- **Load (user decision):** fleet ff `36eb357b` -> `aa06d5a1` plus a refresh-worker restart (settlement
  stamps closing marks there).
- **Re-mark (user decision):** existing marks are final. A mark with a `clv_pct` is never re-stamped,
  and `no_close_for_market` stops at 4 attempts. So the 361 MLB venue rows keep their old marks unless
  re-stamped (precedent: the `#719` re-mark, 15 rows).
- **Forward reading:** same-book coverage on MLB venue orders that settle after the load (World Series,
  10-23 onward), with denominators, against 39 of 266 own-book (kalshi) and 0 of 95 (polymarket).

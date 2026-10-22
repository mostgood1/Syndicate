# Orders with no recorded CLV opening: the openings file hits its ceiling, and venue orders name a book it never records

Lane `venue-order-opening-gap`, session 70a0dbdf (side session of local_7f1cc8f8), 2026-10-22.
This is residual 1 of `.syndicate/findings_2026-10-22_venue_prop_close_coverage.md` (todo `#729`).
Fix: `order_clv` on origin/main (commit in the lane block). **NOT on the fleet.**

## Question

78 settled MLB paper orders had no CLV opening in any openings file within +-3 days. `order_clv`
stamped each one `no_close_for_market` with `no_close_reason` None. The task asked three things:

- Why does the venue book place a (market, line, book) the board never records as an opening?
- Why is 10-11 so concentrated?
- Do NCAAF and NFL orders have the same gap?

## Substrate

- **Ledger:** `execution_ledger.full_history_orders()` on the fleet, read 2026-10-22 ~17:10-17:45Z.
  - Read in WSL under refresh-worker's derived env (`local_production.derive_role_env`), at `nice -n 19`. Read-only.
  - Population: filled `paper*` orders with an outcome, for mlb / ncaaf / nfl. That is **7,777 orders**:
    mlb 901, ncaaf 5,909, nfl 967.
- **Openings:** `~/syndicate-prod/data/reports/intelligence/clv_openings/*.jsonl`, 2026-09-30..10-23.
- **Quotes:** `odds_book_quotes` shards and state sidecars on the fleet's own data root.
- **"Opening-less":** the order's `opening_key` is in no openings file within +-3 days of its
  `selected_date`.

## Before: the gap, all three sports

| sport | venue | opening-less | of settled |
|---|---|---|---|
| mlb | paper | 33 | 420 |
| mlb | paper:kalshi | 20 | 266 |
| mlb | paper:polymarket | 16 | 95 |
| mlb | paper:prophetx | 9 | 66 |
| mlb | paper:novig | 0 | 54 |
| ncaaf | paper | 122 | 2,205 |
| ncaaf | paper:kalshi (+ladder) | 88 (+7) | 363 (+11) |
| ncaaf | paper:polymarket (+ladder) | 36 (+2) | 245 (+9) |
| ncaaf | paper:prophetx | 57 | 1,921 |
| ncaaf | paper:novig | 23 | 1,155 |
| nfl | paper | 80 | 828 |
| nfl | paper:kalshi | 12 | 109 |
| nfl | paper:polymarket | 18 | 30 |
| **total** | | **523** | **7,777** |

- **The MLB 78 reproduce exactly.**
- **NCAAF and NFL have the same gap**, and it is larger: 335 of 5,909 and 110 of 967.
- Every one of the 523 was stamped `no_close_for_market` / None.

## Mechanism 1: the openings file stops at 32 MiB (330 of 523)

`clv_opening_ledger._MAX_LEDGER_BYTES = 32 MiB` is one file per date, shared across sports.
`record_openings` stops writing when a file reaches it. 6 of 24 dates hit it:

| date | bytes | last opening written |
|---|---|---|
| 10-04 | 33,553,702 | 10-04 23:25Z |
| 10-10 | 33,553,975 | 10-10 23:46Z |
| **10-11** | 33,553,605 | **10-11 19:03Z** |
| 10-17 | 33,554,076 | 10-17 22:37Z |
| 10-18 | 33,553,554 | 10-18 19:50Z |
| 10-21 | 33,553,793 | 10-22 03:24Z |

Any bet first seen after its date's file filled has no opening. **330 of the 523 were placed after
their `selected_date` file stopped growing** (mlb 62, ncaaf 181, nfl 87).

**Why 10-11.** 50 of the 78 MLB orders have `selected_date` 10-11 (13 more are on 10-10). The
file is shared by every sport. On Sunday 10-11 it was full by 19:03Z, before that night's LCS
games, and every MLB order on those games was placed after it stopped. Which sport's rows filled it
was not measured. The full dates are the weekend ones (Sat 10-10, 10-17; Sun 10-04, 10-11, 10-18)
plus Wed 10-21. They produce the NCAAF clusters (10-10: 120, 10-17: 94) and the NFL ones
(10-18: 78, 10-11: 15).

## Mechanism 2: venue orders name a book the board never records (193 of 523)

All 193 orders that the ceiling does not explain are **venue-scoped**. None is an unrestricted
`paper` order.

- The board records an opening keyed on its **best** book at first sighting.
- `venue_scope.scope_rows_to_venue` rewrites `quote.bookmaker` to the venue. A venue order's
  `opening_key` therefore names (line, venue), and that key exists only if the venue was once the
  board's best book for that line.

| what the 193 look like | n |
|---|---|
| the same bet is recorded at another book, never at the venue | 166 |
| the key exists, but in a file more than 3 days from `selected_date` (forward-dated NCAAF/NFL orders) | 27 |
| the bet is in no file at all | 0 |

Of the 193, 37 were placed in play.

**Why a fix at the opening (option a) was not taken.** Recording an opening at order time would
write to the same capped file, so on a ceiling day it is lost the same way. Every order already
carries the quote log's whole match key. Its own `submitted_at` is the honest open clock: it is
when WE took the price.

## Fix (option b): `order_clv` resolves an opening-less order from the quote log

- **Which orders.** An order whose key the resolver never saw: no close row and no named refusal.
  It gets an opening-shaped record built from its own fields: `event_id, market, segment, side,
  player_name, line, book`, open clock `submitted_at`, and `commence_time`.
- **How it is resolved.** Through `clv_join._quote_closes_for_openings`, one stream per shard for
  all such orders. That function applies the opened-in-play rule, the not-started rule, and the
  same-book-first rule. `compute_clv_for_date`'s arrow-of-time refusal is then applied
  (`quotes_unchanged_since_open`).
- **Labels.** A failure is named `no_opening:<reason>` instead of None. The row and the stamped
  `closing_mark` carry `opening_source=order`; `paper_settlement._CLOSE_FIELDS` gained that one
  field. `open_clv_pct` is None.
- **Unchanged.** An order whose opening exists, resolved or refused, is untouched. A caller that
  injects `clv_rows` without `quote_rows` gets the old behaviour and no disk read.
- **Tests:** `tests/test_order_clv_opening_less.py`, 13 tests.
  - 10 fail on origin/main's `order_clv.py`. The 3 that pass are guards that must hold both ways.
  - Two mutations were caught: dropping the arrow-of-time check, and re-resolving an opening the
    resolver had refused.
  - A reachability test runs the un-injected path, as `stamp_closing_marks` calls it.
  - 481 passed across the clv / paper_settlement / min_ev_tuner / position_marks / portfolio_commit suites.

## After: fleet replay (same inputs, before vs after)

**Method.**
- For each (`selected_date`, sport), `compute_clv_for_date` ran once on the fix's code: the
  worktree, which includes `aa06d5a1`.
- **before** = `clv_for_orders` with those rows injected and no quote pass. That is exactly the old
  behaviour.
- **after** = the same rows plus the production quote loaders.

**Opening-less orders (n = 523):**

| sport | venue | n | resolved after | same-book after |
|---|---|---|---|---|
| mlb | paper | 33 | 7 | 7 |
| mlb | paper:kalshi | 20 | 14 | 6 |
| mlb | paper:polymarket | 16 | 4 | 4 |
| mlb | paper:prophetx | 9 | 5 | 5 |
| ncaaf | paper | 122 | 4 | 4 |
| ncaaf | paper:kalshi (+ladder) | 88 (+7) | 46 (+5) | 11 (+0) |
| ncaaf | paper:polymarket (+ladder) | 36 (+2) | 20 (+1) | 8 (+1) |
| ncaaf | paper:prophetx | 57 | 25 | 25 |
| ncaaf | paper:novig | 23 | 3 | 3 |
| nfl | paper | 80 | 1 | 1 |
| nfl | paper:kalshi | 12 | 5 | 0 |
| nfl | paper:polymarket | 18 | 9 | 0 |
| **total** | | **523** | **149** (was 0) | **75** (was 0) |

- The other 74 resolved closes are `different_book_close`. They are labelled as such and the headline
  never counts them.
- Same-book CLV on the 75: mean +0.46 pt, median +0.24, 40 of 75 beat the close. This is
  **descriptive only**: not event-clustered, and paper fills at the quoted price.

**Residual: 374 of 523 still have no close, each now named:**

| reason | mlb | ncaaf | nfl | total |
|---|---|---|---|---|
| `no_opening:opened_in_play` (a live bet has no pregame close, by definition) | 41 | 192 | 85 | 318 |
| `no_opening:quotes_unchanged_since_open` | 7 | 39 | 4 | 50 |
| `no_opening:quotes_no_pregame_quote` | 0 | 0 | 6 | 6 |

**The MLB 78:** 30 now resolve (22 same-book, 8 different-book). The residual is 48: 41 placed in
play and 7 `quotes_unchanged_since_open`. **Excluding the in-play bets, MLB's pregame opening-less
orders resolve 30 of 37.**

**All settled orders (n = 7,777):** resolved 6,250 -> 6,541 and same-book 6,227 -> 6,437.
- 216 rows outside the opening-less set changed too. These are orders whose opening exists, but
  only in another date's file. `compute_clv_for_date` reads `selected_date`'s file only, so before
  they also had no row. 142 of them now resolve.
- Every change is from the old `no_close_for_market` / None. A row that was resolved before cannot
  change.

Venue totals (same-book, before -> after):

| sport | venue | n | same-book before | same-book after |
|---|---|---|---|---|
| mlb | paper:kalshi | 266 | 218 | 224 |
| mlb | paper:polymarket | 95 | 72 | 76 |
| ncaaf | paper:kalshi | 363 | 183 | 214 |
| ncaaf | paper:polymarket | 245 | 119 | 142 |

(The MLB "before" numbers already include `aa06d5a1`.)

**Cost.**
- The quote pass re-streams shards that `compute_clv_for_date` has already streamed. In the replay
  it took ≤ 0.6 s on MLB dates and up to 9.4 s on an NCAAF date (10-09, 368 orders), where
  `compute_clv_for_date`'s own quote pass took ~22 s.
- In-play and not-started orders never open a shard.
- It runs on the settlement path, and on `portfolio_commit`'s board-build `order_clv` diagnostic for
  today's started pregame orders.

## Owed / not done

- **Load (user decision):** a fleet ff to a commit carrying this, plus `aa06d5a1`, plus a
  refresh-worker restart. Stamped marks are final, so the 523 existing rows keep `None` unless
  re-marked. That is the same decision `#729` already holds for the 361 MLB venue rows.
- **The ceiling itself is the larger defect, and it is not fixed here.**
  - On 6 of 24 dates, every opening after the cut is missing from the CLV report too, not only from
    orders.
  - On 10-11, everything after 19:03Z is missing, for every sport.
  - The fix belongs in `clv_opening_ledger`: per-sport files, or a ceiling sized to a Saturday.
  - Proposed as a follow-up session.
- **Lead, unmeasured:** an order placed in play whose OPENING was recorded pregame is graded against
  the pregame close at its in-play fill price. That pairing is not CLV. Count before deciding anything.

# "Only one book quotes it" — when 10 do: the book grid's relative staleness rule — 2026-10-16

User 2026-10-16, on the Nick Martinez OVER 2.5 STRIKEOUTS (+138) card ("KALSHI · 1 BK", case against "Only one book
quotes it, so the fair rests on one price"): "we also need to look into this saying theres only one book pricing
this". READ-ONLY investigation; nothing changed. Times US Central.

## The case (measured on the fleet)

- Book-quote shard, MLB 10-16, Martinez strikeouts 2.5 OVER: **10 books** -- DK +123, Bovada +120, BetOnline +115,
  FanDuel +114, Fanatics +110, BetMGM +110, Hard Rock +110, ESPN Bet +105, MyBookie +101, Kalshi +150 (UNDER at 10
  books too, -140..-160).
- Live grid row (`/api/board/book-grid?sport=mlb&date=2026-10-16&limit=5000`, generated 4:21:43 PM): `books_quoting`
  **1** (kalshi), `books_quoting_including_stale` **10**. Every sportsbook cell `stale: true`: `seen_age` 3,168.6 s
  (last SEEN in the 3:28 PM props fetch), Kalshi's 1,144.4 s (its own, more frequent capture) -> `seen_lag` 2,024 s >
  `_STALE_BEST_LAG_SECONDS` 900. The grid itself then refuses the consensus: `market_basis.servable: false`, "1 book
  quoting: a consensus needs at least 2".
- The pick (`l2_bfa47717e5cda893`, promoted 4:07:19 PM) carried `books: 1`, `book: kalshi`, fair 0.4375 / +129 --
  from the board card's `quote.books_quoting` and `quote.fair_probability`. The board's other cards show the same
  shape (e.g. Rocchio RBIs: `books_quoting 1`, `book_age_source kalshi`, `fair_devig_method shin` on Kalshi's own two
  sides). Board cards do not carry `books_quoting_including_stale`, so nothing downstream can tell 1 from 10.

## The mechanism

`syndicate/features/shared/book_grid.py:143-160, 600-645`: a cell is stale when it was last SEEN more than 15 min
before the most recently SEEN book on that market (the 2026-10-06 fix moved this from "last moved" to "last seen",
which was right). But books reach the grid through DIFFERENT captures on different clocks -- the sportsbook props
fetch (MLB postseason: ~hourly, e.g. 3:28 PM), exchange pollers (Kalshi, ProphetX), per-book fetches -- so whenever
ONE book was captured more than 15 min after the others, every other book flips stale although all are still posting.
The best price and the consensus are chosen from FRESH quotes only (#S1b), so the line is priced against that one
venue's own two sides.

## Scale (live grid, 4:29 PM CT 10-16): sides with 1 fresh book while >= 2 books quote

| sport (date) | sides |
|---|---|
| NFL (10-18) | **546 of 2,389 (23%)** |
| NCAAF (10-17) | **416 of 3,090 (13%)** |
| MLB (10-16) | 59 of 484 (12%) |
| NBA (10-16) | 32 of 2,162 |
| NHL (10-16) | 10 of 735 |
| soccer (10-17) | 17 of 2,322 |

The lone "fresh" book: ESPN Bet 220, Kalshi 157, Hard Rock 133, BetRivers 114, BetMGM 106, BetOnline 89, ProphetX 80,
FanDuel 68 -- whichever was captured last. **20 of the board's 66 suggested picks at 4:25 PM showed `books_quoting
1`** (NCAAF spreads/totals at ProphetX, MLB props at Kalshi, an NFL rushing-attempts prop at Fanatics, NBA totals at
BetRivers, a soccer corners alt at FanDuel). This is very likely a large part of the "only 3-5 books" complaint the
fetch-side fix (#props-book-coverage) did not cover.

## Fix options (NOT applied: `book_grid.py` belongs to OPEN lane `published-negative-ev`, session 4ab694ed; and the
standing rule is no board changes during the MLB postseason)

1. **Staleness per capture, not per market:** a quote is current when it was seen in its own feed's latest snapshot
   -- e.g. compare a cell's `seen_age` against the freshest seen age AMONG BOOKS OF THE SAME FEED (sportsbooks vs each
   exchange), or an absolute pregame ceiling at the sport's fetch cadence (e.g. 75 min pregame) with the 15-min
   relative rule kept for live. Restores the count AND the consensus everywhere (board, sheets, cards).
2. **Never promote a pick whose consensus the grid refused** (`market_basis.servable: false` / `books_quoting < 2`):
   today such a pick's "edge" is one venue's price against its own de-vig -- its hold asymmetry, not a market edge.
3. Carry `books_quoting_including_stale` on the board card so the sheet and the cards can state both numbers.

Card-side only (lanes `cheat-sheets` / `play-cards`, mine): until (1) lands, the card must not say "Only one book
quotes it" when the sheet's own row shows the line at N books.

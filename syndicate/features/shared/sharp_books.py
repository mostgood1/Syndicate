"""THE ONE OWNER of "which books are a sharp reference price".

WHY THIS FILE EXISTS. The sharp set lived as `live_gameline_ledger._SHARP_BOOKS`,
a private frozenset used only to REPORT coverage (`sharp_books` / `has_pinnacle`
on each ledger record). The pricing plane (`layer2_board._fair_by_side`) is now
allowed to ANCHOR the board's fair probability on one of these books instead of
taking the median over all ~44, and that needs the same set. Two copies of a
book list drift -- `learnings.md` forbids a module holding its own -- so the
ledger imports this one and holds no second copy.

TWO TIERS, IN THE ORDER THEY ARE TRIED
--------------------------------------
`SHARP_ANCHOR_PRIORITY` -- bookmakers that post BOTH sides of a market with
their own margin, and whose margin is small and symmetric enough that a
power de-vig of that one book is a better fair than the soft-book median.
Pinnacle is the only one we capture (via OddsAPI region `eu`); Circa is not in
the feed.

`EXCHANGE_ANCHOR_PRIORITY` -- two-sided venues whose de-vigged pair is a MID,
not a bookmaker's opinion. Ordered by depth: the OddsAPI-carried exchanges
(`betfair_ex_eu` back prices, `matchbook`, then the US exchanges `novig`,
`prophetx`), then the venues this platform reads DIRECTLY (`kalshi`,
`polymarket`). The direct-venue names are `book_shortlist.DIRECT_FEED_BOOKS`,
which is what `venue_quote_fanin._VENUE_BOOK_NAME` maps the adapter source
`polymarket_us` onto before a venue quote becomes a `cells[book]` entry -- so
the keys here are the keys a grid row actually carries.

THE EXCHANGE TIER'S FILL RISK IS NOT PRICED HERE. An exchange's posted pair is
what you could HIT at that instant for some size; the mid de-vigged from it is a
reference, not an executable price, and nothing in this module or in
`_fair_by_side` accounts for depth, commission or the chance the order does not
fill. `venue_fees` and `venue_basis_edge` own that, on the EXECUTION side.

`SHARP_BOOKS` is the union the ledger reports coverage on. It is deliberately
NOT extended with the direct venues: `state.md [sharp-reference-price]` measured
100% game-line coverage on exactly this five-book set, and a record's
`sharp_books` field is compared against that measurement.
"""

from __future__ import annotations

from syndicate.features.shared.book_shortlist import DIRECT_FEED_BOOKS

#: Tier 1. Tried first, in this order. A bookmaker, not an exchange.
SHARP_ANCHOR_PRIORITY: tuple[str, ...] = ("pinnacle",)

#: Tier 2. Tried after every tier-1 book has failed to quote both sides fresh.
#: The direct-feed venues come LAST and are appended from the registry rather
#: than spelled here, so a venue renamed there cannot leave a stale key behind.
EXCHANGE_ANCHOR_PRIORITY: tuple[str, ...] = (
    "betfair_ex_eu",
    "matchbook",
    "novig",
    "prophetx",
) + tuple(sorted(DIRECT_FEED_BOOKS))

#: The coverage set `live_gameline_ledger` reports on. Unchanged membership --
#: see the module docstring for why the direct venues are not in it.
SHARP_BOOKS: frozenset[str] = frozenset({"pinnacle", "betfair_ex_eu", "matchbook", "novig", "prophetx"})


def is_sharp_book(book: object) -> bool:
    """Is this a book the ledger counts as sharp coverage? Blank/unknown is False."""
    if book is None:
        return False
    return str(book).strip().lower() in SHARP_BOOKS

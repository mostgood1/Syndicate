"""Pin the enumeration of places a Polymarket outcome array is paired with its
price array positionally.

`polymarket_board_join`'s header documents that every Polymarket price in the
system rests on `outcomes[i]` naming the club that `outcomePrices[i]` prices --
an assumption tested ONCE, on a totals market, at ~0.11 separation. The value of
that comment is entirely in its list being complete, and it was not: it said
THREE and omitted `kalshi_polymarket_arb`, the only site that decides a trade
across both legs rather than pricing a row for display.

**These tests also encode a correction to the first version of this file.** I
asserted `_polymarket_sides` zips ONCE and wrote that into the comment. It zips
TWICE -- my earlier count came from an `awk` window that truncated a 165-line
function. The original "twice" was right; only the missing arb site was wrong.
So: 4 call sites across 3 functions.
"""

import inspect
import pkgutil
import re

from syndicate.features.shared import (
    kalshi_polymarket_arb,
    polymarket_board_join,
    venue_quote_adapters,
)

#: Modules that pair the two arrays positionally, with the number of pairings.
KNOWN_SITES = {
    "polymarket_board_join._outcome_probabilities": 1,
    "venue_quote_adapters._polymarket_sides": 2,
    "kalshi_polymarket_arb": 1,
}
TOTAL_SITES = 4
TOTAL_FUNCTIONS = 3

#: Modules that touch `outcomePrices` for reasons that are NOT a name<->price
#: pairing, each with the reason. Listed so the sweep below stays meaningful.
NOT_PAIRING_SITES = {
    # field lists and docstrings only; its `outcomes[0]` references are about
    # the SEPARATE "outcomes[0] is the YES leg" claim, which it measured FALSE
    "polymarket_us_markets": "field lists + the YES-leg claim it disproved",
    # `yes_outcome_index()` -- leg identity, not club<->price
    "polymarket_us_orders": "leg identity via yes_outcome_index()",
    # `_outcome_prices` returns (raw[0], raw[1]) without touching `outcomes`
    "venue_daily_odds": "price order only, never paired with outcome names",
    # the client documents the index-matching contract; it does not consume it
    "polymarket_client": "documents the contract",
}


def _zips(obj):
    return len(re.findall(r"\bzip\(", inspect.getsource(obj)))


def test_outcome_probabilities_pairs_once():
    assert _zips(polymarket_board_join._outcome_probabilities) == 1


def test_polymarket_sides_zips_TWICE_as_the_original_comment_said():
    """My first pass claimed ONCE and was wrong.

    An `awk NR<=s+140` window truncated the 165-line function and found one of
    two. The lesson is in the test name: the original enumeration was right
    about this and I nearly "corrected" it into a falsehood.
    """
    assert _zips(venue_quote_adapters._polymarket_sides) == 2, (
        "the number of positional zips here changed; update "
        "polymarket_board_join's enumeration, KNOWN_SITES and TOTAL_SITES "
        "together")


def test_the_arb_resolver_pairs_by_INDEX_which_a_zip_grep_cannot_find():
    """Site 3 -- the omitted one, and why grepping for `zip` misses it."""
    src = inspect.getsource(kalshi_polymarket_arb)
    assert "outcomes[0]" in src and "outcomes[1]" in src
    assert "price_a" in src and "price_b" in src
    assert _zips(kalshi_polymarket_arb) == 0


def test_the_totals_reconcile():
    assert sum(KNOWN_SITES.values()) == TOTAL_SITES
    assert len(KNOWN_SITES) == TOTAL_FUNCTIONS


def test_the_comment_states_BOTH_numbers_and_names_every_site():
    """The stale total survived because the arithmetic was invisible.

    The original said "three" and named a function "twice" in prose, so a
    reader could not see 1 + 2 + 1. The comment must now carry the explicit
    totals and every site.
    """
    src = inspect.getsource(polymarket_board_join)
    head = src[:src.index("def _classify_alignment")]
    assert "FOUR call sites" in head
    assert "4 call sites across 3 functions" in head
    for dotted in KNOWN_SITES:
        symbol = dotted.split(".")[-1]
        assert symbol in head, "%s is a known site and the comment omits it" % symbol
    assert "kalshi_polymarket_arb" in head


def test_the_comment_cross_references_the_MEASURED_counterexample():
    """The sibling positional claim was measured false and cost real money.

    `polymarket_us_markets` says so in those words. A reader of this assumption
    must see that, or "tested once" reads as "nobody has looked".
    """
    head = inspect.getsource(polymarket_board_join)
    head = head[:head.index("def _classify_alignment")]
    assert "COST REAL MONEY" in head
    assert "3 of 8 settled" in head
    assert "polymarket_us_orders" in head


def test_no_FIFTH_pairing_site_has_appeared():
    """The guard this file exists for.

    Any module pairing `outcomePrices` with `outcomes` is a site. A new one must
    join the comment and KNOWN_SITES in the same change -- the same rule that a
    new `select_shortlist` counter must reach the API payload in the same commit.
    """
    import syndicate.features.shared as shared

    known = {d.split(".")[0] for d in KNOWN_SITES}
    offenders = []
    for mod in pkgutil.iter_modules(shared.__path__):
        name = mod.name
        if name in known or name in NOT_PAIRING_SITES:
            continue
        try:
            module = __import__("syndicate.features.shared.%s" % name,
                                fromlist=["_"])
            src = inspect.getsource(module)
        except Exception:
            continue
        if "outcomePrices" not in src:
            continue
        if "zip(" in src or re.search(r"outcomes\[\s*\d", src):
            offenders.append(name)
    assert not offenders, (
        "a new positional pairing appeared in %s -- add it to "
        "polymarket_board_join's enumeration and KNOWN_SITES, or to "
        "NOT_PAIRING_SITES with the reason" % offenders)

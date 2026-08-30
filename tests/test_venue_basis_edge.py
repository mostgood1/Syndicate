"""The venue basis: an in-play exchange price against the book consensus.

The tests that matter here are the REFUSALS. This module's whole justification
is that it is allowed live where `market_basis_edge` is not, and every guard is
the reason that permission is not a licence.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared.venue_basis_edge import (
    MAX_ANCHOR_AGE_SECONDS,
    MAX_VENUE_QUOTE_AGE_SECONDS,
    MIN_BOOKS_FOR_CONSENSUS,
    MIN_EDGE_PCT_TO_DISPLAY,
    venue_basis_edge,
)

NOW = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)


def _side(books=5, consensus=-110, stale=False):
    return {
        "books_quoting": books,
        "consensus_vigged_price": consensus,
        "price": consensus,
        "all_quotes_stale": stale,
        "suspect_stale": False,
    }


def _call(**kw):
    args = dict(
        best_side=_side(),
        venue="kalshi",
        venue_price=-110,
        venue_quote_age_seconds=10.0,
        book_quote_age_seconds=60.0,
        kalshi_fee_multiplier=0.5,
        is_live=True,
        now=NOW,
    )
    args.update(kw)
    return venue_basis_edge(args.pop("best_side"), **args)


def test_a_real_gap_is_displayed_with_the_fee_priced_in():
    """The happy path -- and the fee must be visible on it.

    A venue edge quoted without its commission is not auditable: a reader
    cannot tell a real gap from one the exchange has already eaten.
    """
    # book consensus -110 (0.524); venue +120 (0.4545) -> venue much cheaper
    out = _call(venue_price=120)
    assert out.displayable is True
    assert out.edge_pct > 0
    assert out.venue_fee_per_contract is not None and out.venue_fee_per_contract > 0
    assert out.anchor_books == 5
    assert out.consensus_probability == pytest.approx(0.5238, abs=0.001)


def test_it_is_NEVER_servable():
    """Ships display-only, deliberately.

    The claim -- that venue-vs-book disagreement during a game is real edge --
    has never been scored against results, and this platform has already
    shipped and backed out one unmeasured live edge that read +36.5% on props
    whose over had ALREADY WON.
    """
    out = _call(venue_price=120)
    assert out.displayable is True
    assert out.servable is False, "a displayable venue edge must not be servable"
    assert "DISPLAY ONLY" in out.reason


def test_a_PREGAME_row_is_refused_to_market_basis():
    """Two modules answering the same pregame question with different
    arithmetic is how a board comes to disagree with itself."""
    out = _call(is_live=False)
    assert out.edge_pct is None
    assert "market_basis_edge" in out.reason


def test_a_SPORTSBOOK_cannot_anchor_a_live_comparison():
    """THE GUARD THIS MODULE EXISTS FOR.

    Anchoring live on another book is exactly the staleness trap
    `market_basis_edge` documents -- ten quotes on the same line within 115s,
    +1200 against +175, because some books stopped updating. An unknown venue
    must REFUSE, never default to allowed.
    """
    for name in ("draftkings", "fanduel", "", "novig"):
        out = _call(venue=name, venue_price=120)
        assert out.edge_pct is None, f"{name!r} was allowed to anchor a live comparison"
        assert "in-play exchange" in out.reason


def test_a_venue_quote_naming_ANOTHER_FIXTURE_is_refused():
    """`#603`. Measured: 26 of 28 live Polymarket totals quotes were shared
    across games, `over 7.5 @ -400` on four at once where one was worth ~2% and
    another had already won. That would read as a spectacular edge here."""
    out = _call(
        venue="polymarket",
        venue_price=400,
        venue_game_token="san diego padres+tampa bay rays",
        row_game_token="atlanta braves+colorado rockies",
    )
    assert out.edge_pct is None
    assert "#603" in out.reason


def test_a_stale_venue_quote_is_refused_on_a_TIGHTER_bar_than_pregame():
    """A 300s-old price is fine pregame and is two innings on a live market."""
    fresh = _call(venue_price=120, venue_quote_age_seconds=MAX_VENUE_QUOTE_AGE_SECONDS - 1)
    stale = _call(venue_price=120, venue_quote_age_seconds=MAX_VENUE_QUOTE_AGE_SECONDS + 1)
    assert fresh.displayable is True
    assert stale.edge_pct is None
    assert "game state" in stale.reason


def test_an_ageless_venue_quote_is_refused_rather_than_assumed_fresh():
    out = _call(venue_price=120, venue_quote_age_seconds=None)
    assert out.edge_pct is None
    assert "no age" in out.reason


def test_a_one_or_two_book_consensus_is_not_a_consensus():
    """Guard 4, inherited from `market_basis_edge`: with one book the
    'consensus' IS that book and the arithmetic is an echo."""
    for books in range(0, MIN_BOOKS_FOR_CONSENSUS):
        out = _call(best_side=_side(books=books), venue_price=120)
        assert out.edge_pct is None, f"{books} books produced a number"
        assert out.anchor_books == books


def test_a_stale_book_side_is_refused():
    out = _call(best_side=_side(stale=True), venue_price=120)
    assert out.edge_pct is None
    assert "stale" in out.reason


def test_agreement_inside_the_noise_floor_is_not_a_finding():
    """A venue and a book within a quarter point during a live game agree.

    NOTE the fixture: an IDENTICAL venue price is NOT agreement once the
    commission is added -- at -110 on a half-rate Kalshi series the fee alone
    is 0.87 pts, which the module correctly reports as the books being cheaper.
    To land inside the floor the venue must be cheaper by about the fee.
    """
    out = _call(venue_price=-106)   # 0.5146 + 0.0087 fee = 0.5233 vs 0.5238
    assert out.edge_pct is None, f"got {out.edge_pct} / {out.reason}"
    assert "noise floor" in out.reason
    # And the refusal still carries what makes it auditable.
    assert out.venue_fee_per_contract is not None
    assert out.consensus_probability is not None


def test_an_IDENTICAL_venue_price_is_reported_as_the_BOOKS_being_cheaper():
    """The direction matters and must be stated, not left to a sign.

    Same nominal price on both sides is not parity: taking the venue side costs
    its commission on top, so the books really are cheaper.
    """
    out = _call(venue_price=-110)
    assert out.displayable is True
    assert out.edge_pct < 0
    assert "BOOKS are cheaper" in out.reason


def test_kalshi_without_its_SERIES_multiplier_assumes_the_FULL_rate_and_says_so():
    """Unknown resolves to the CONSERVATIVE side, not to a refusal.

    Nothing writes `fee_multiplier` into `kalshi_markets.json`, so refusing
    would make this module inert on the venue whose in-play depth is actually
    measured. Assuming the full 0.07 rate can only make an edge look SMALLER --
    every MLB game series is half rate -- so it cannot invent one.

    The bound must be VISIBLE. A reader told a bound is a measurement has been
    misled in the direction that matters least, but still misled.
    """
    assumed = _call(venue="kalshi", venue_price=120, kalshi_fee_multiplier=None)
    known = _call(venue="kalshi", venue_price=120, kalshi_fee_multiplier=0.5)
    assert assumed.displayable is True, assumed.reason
    assert assumed.fee_is_upper_bound is True
    assert assumed.as_payload()["fee_is_upper_bound"] is True
    # CONSERVATIVE, and demonstrably so: the assumed fee is larger and the edge
    # it yields is smaller than the one the real half-rate series produces.
    assert assumed.venue_fee_per_contract > known.venue_fee_per_contract
    assert assumed.edge_pct < known.edge_pct
    # And a KNOWN multiplier is never mislabelled as a bound.
    assert known.fee_is_upper_bound is False


def test_polymarket_is_never_an_upper_bound():
    """Its 150bps is measured and price-independent; nothing is assumed."""
    out = _call(venue="polymarket", venue_price=120, kalshi_fee_multiplier=None)
    assert out.displayable is True
    assert out.fee_is_upper_bound is False


def test_the_FEE_actually_moves_the_verdict():
    """off != on for the commission.

    If the fee were ignored this edge would clear the floor; priced in, it does
    not. A module that computed the same answer with and without the fee would
    not be pricing it at all.
    """
    # Polymarket: flat 0.015/contract. Consensus 0.5238; venue 0.5100 ->
    # raw gap +1.38 pts, but +0.5100 + 0.0150 = 0.5250 -> -0.12 pts, inside the floor.
    out = venue_basis_edge(
        _side(), venue="polymarket", venue_price=-104,
        venue_quote_age_seconds=5.0, book_quote_age_seconds=60.0, is_live=True, now=NOW,
    )
    raw_gap = (0.5238 - 0.5100) * 100
    assert raw_gap > MIN_EDGE_PCT_TO_DISPLAY, "fixture must clear the floor BEFORE fees"
    assert out.edge_pct is None, "the commission must have eaten it"
    assert "noise floor" in out.reason


def test_polymarket_and_kalshi_price_the_same_row_DIFFERENTLY():
    """The two fee SHAPES differ and it shows at the tails.

    Kalshi's is a parabola that vanishes at the tails; Polymarket's is flat and
    does not. At a tail price Polymarket costs several times more, so the same
    venue quote is a different effective price depending on where it is taken.
    """
    tail = dict(venue_price=-1500, venue_quote_age_seconds=5.0,
                book_quote_age_seconds=60.0, is_live=True, now=NOW)
    k = venue_basis_edge(_side(consensus=-2000), venue="kalshi", kalshi_fee_multiplier=0.5, **tail)
    p = venue_basis_edge(_side(consensus=-2000), venue="polymarket", **tail)
    # Both must REPORT the fee even where the verdict differs -- the refusal
    # path carries it too, which is what makes this comparison possible at all.
    assert k.venue_fee_per_contract is not None and p.venue_fee_per_contract is not None
    assert p.venue_fee_per_contract > k.venue_fee_per_contract * 3, (
        f"polymarket {p.venue_fee_per_contract} should dwarf kalshi {k.venue_fee_per_contract} "
        "at a tail price"
    )


def test_the_payload_carries_what_makes_it_auditable():
    out = _call(venue_price=120)
    payload = out.as_payload()
    for key in ("basis", "edge_pct", "venue", "venue_probability", "consensus_probability",
                "venue_fee_per_contract", "anchor_books", "servable", "reason"):
        assert key in payload, f"payload is missing {key}"
    assert payload["basis"] == "venue"
    assert payload["servable"] is False


def test_a_PREGAME_BOOK_CONSENSUS_cannot_anchor_a_LIVE_venue_price():
    """GUARD 5 -- the one this module was first written without.

    This is the failure mode most likely to have shipped a spectacular fiction:
    `_reprice_live_benchmark` measured a live ~0.90 against a pregame ~0.55 on a
    team three runs up in the 7th. That 35-point number is entirely the gap
    between two clocks and is shaped EXACTLY like a huge in-play edge.

    Note the fixture carries NO staleness flag, because the real one did not
    either -- when every book stopped updating at first pitch, none of them is
    stale relative to its peers.
    """
    two_hours = MAX_ANCHOR_AGE_SECONDS + 6_000
    out = _call(venue_price=-900, book_quote_age_seconds=two_hours)
    assert out.edge_pct is None, f"vintage gap reported as an edge: {out.edge_pct}"
    assert "two clocks" in out.reason
    # And prove the fixture COULD have produced the fiction -- a zero from a
    # population that cannot produce a one is not evidence of a guard.
    unguarded = _call(venue_price=-900, book_quote_age_seconds=60.0)
    assert unguarded.displayable is True
    assert unguarded.edge_pct < -30, (
        f"fixture must reproduce the ~35-point vintage artifact, got {unguarded.edge_pct}"
    )


def test_an_UNAGED_book_consensus_is_assumed_pregame_not_assumed_fine():
    """Unknown must not fall onto the permissive branch."""
    out = _call(venue_price=120, book_quote_age_seconds=None)
    assert out.edge_pct is None
    assert "assumed PREGAME" in out.reason

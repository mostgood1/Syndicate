"""`paper2` -- the same board restricted to one venue's prices.

The failure that would make this whole exercise worthless is a scoped plan that
silently keeps the BEST BOOK's economics while wearing the venue's name. Most of
these tests are about that.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.venue_scope import (
    REASON_NO_EV_PCT,
    REASON_UNUSABLE_VENUE_PRICE,
    REASON_VENUE_NOT_QUOTING,
    scope_rows_to_venue,
    venue_scope_report_line,
)


def _row(best=-110, book_prices=None, ev_pct=4.0, **overrides):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "h2h",
        "segment": None,
        "side": "home",
        "line": None,
        "player_name": None,
        "ev_pct": ev_pct,
        "model_edge_pct": 2.0,
        "score": {"score": 60.0, "price_reliability": 0.9},
        "quote": {
            "bookmaker": "draftkings",
            "price": best,
            "book_prices": book_prices if book_prices is not None
            else {"draftkings": best, "kalshi": -130},
        },
    }
    row.update(overrides)
    return row


# --- the point of the exercise --------------------------------------------


def test_a_worse_venue_price_produces_a_worse_EV_not_the_inherited_one():
    """THE LOAD-BEARING TEST. +4.0% at -110 is NEGATIVE at -130. Inheriting the
    best book's EV would size a losing bet at a price we did not get."""
    scoped, _ = scope_rows_to_venue([_row(best=-110, ev_pct=4.0)], "kalshi")
    assert len(scoped) == 1
    assert scoped[0]["ev_pct"] < 0
    assert scoped[0]["quote"]["price"] == -130
    assert scoped[0]["quote"]["bookmaker"] == "kalshi"


def test_a_better_venue_price_produces_a_better_EV():
    scoped, _ = scope_rows_to_venue(
        [_row(best=-130, ev_pct=1.0, book_prices={"draftkings": -130, "kalshi": -105})],
        "kalshi",
    )
    assert scoped[0]["ev_pct"] > 1.0


def test_an_equal_venue_price_reproduces_the_original_EV():
    """The algebra must be an identity when nothing changes, or every other
    number it produces is suspect."""
    scoped, _ = scope_rows_to_venue(
        [_row(best=-110, ev_pct=4.0, book_prices={"draftkings": -110, "kalshi": -110})],
        "kalshi",
    )
    assert scoped[0]["ev_pct"] == pytest.approx(4.0, abs=1e-6)


def test_the_unrestricted_numbers_are_kept_beside_the_scoped_ones():
    """The gap between them IS the price cost of the restriction, which is half
    of what the comparison is for."""
    scoped, _ = scope_rows_to_venue([_row(best=-110, ev_pct=4.0)], "kalshi")
    row = scoped[0]
    assert row["unrestricted_price"] == -110
    assert row["unrestricted_ev_pct"] == 4.0
    assert row["unrestricted_bookmaker"] == "draftkings"


def test_model_edge_carries_over_untouched():
    """`model_edge_pct` is the model's deviation from the market's fair
    probability -- a property of the market, not of the book quoting it."""
    scoped, _ = scope_rows_to_venue([_row()], "kalshi")
    assert scoped[0]["model_edge_pct"] == 2.0


# --- refusals --------------------------------------------------------------


def test_a_row_the_venue_does_not_quote_is_refused_never_repriced():
    """No fallback to a neighbouring book: the whole question is what THIS
    venue offers, and a substituted price answers a different one."""
    scoped, refusals = scope_rows_to_venue(
        [_row(book_prices={"draftkings": -110, "fanduel": -115})], "kalshi"
    )
    assert scoped == []
    assert refusals[REASON_VENUE_NOT_QUOTING] == 1


def test_venue_coverage_is_the_headline_refusal():
    """How much of the board the venue does not offer IS the Stage D answer, so
    it is counted rather than silently skipped."""
    rows = [_row(), _row(book_prices={"draftkings": -110}), _row(book_prices={"draftkings": -110})]
    scoped, refusals = scope_rows_to_venue(rows, "kalshi")
    assert len(scoped) == 1
    assert refusals[REASON_VENUE_NOT_QUOTING] == 2


def test_a_row_with_no_ev_is_refused_by_the_sizers_own_name():
    scoped, refusals = scope_rows_to_venue([_row(ev_pct=None)], "kalshi")
    assert refusals[REASON_NO_EV_PCT] == 1


def test_a_zero_venue_price_is_refused():
    scoped, refusals = scope_rows_to_venue(
        [_row(book_prices={"draftkings": -110, "kalshi": 0})], "kalshi"
    )
    assert refusals[REASON_UNUSABLE_VENUE_PRICE] == 1


def test_every_row_is_accounted_for():
    """scoped + refusals == rows_in, or the pass is not a measurement."""
    rows = [
        _row(),
        _row(book_prices={"draftkings": -110}),
        _row(ev_pct=None),
        "not a mapping",
    ]
    scoped, refusals = scope_rows_to_venue(rows, "kalshi")
    assert len(scoped) + sum(refusals.values()) == len(rows)


def test_book_matching_is_case_insensitive():
    scoped, _ = scope_rows_to_venue(
        [_row(book_prices={"DraftKings": -110, "KALSHI": -105})], "kalshi"
    )
    assert len(scoped) == 1


def test_book_prices_survive_scoping():
    """The marks and the CLV join both read `book_prices`; trimming it would
    make a scoped order un-markable for a reason unrelated to the venue."""
    scoped, _ = scope_rows_to_venue([_row()], "kalshi")
    assert scoped[0]["quote"]["book_prices"]


def test_scoping_does_not_mutate_the_input_row():
    """The unrestricted plan is built from these same rows, in the same run."""
    row = _row()
    scope_rows_to_venue([row], "kalshi")
    assert row["quote"]["bookmaker"] == "draftkings"
    assert row["quote"]["price"] == -110
    assert row["ev_pct"] == 4.0


def test_report_line_carries_coverage():
    scoped, refusals = scope_rows_to_venue(
        [_row(), _row(book_prices={"draftkings": -110})], "kalshi"
    )
    line = venue_scope_report_line("kalshi", 2, len(scoped), refusals)
    assert "VENUE_SCOPE" in line
    assert "venue=kalshi" in line
    assert "coverage=0.5" in line


# --- the two books must stay separable ------------------------------------


def test_the_two_books_produce_DIFFERENT_idempotency_keys():
    """If they collided, paper2 would silently suppress the main book's orders
    rather than fail visibly -- the worst possible failure for a comparison."""
    from syndicate.features.shared.execution_ledger import OrderRequest, idempotency_key

    common = dict(
        position_key="p1",
        selected_date="2026-08-22",
        sport="mlb",
        event_id="evt-1",
        market="h2h",
        side="home",
        requested_price=-110,
        requested_stake_dollars=5.0,
    )
    main = idempotency_key(OrderRequest(venue="paper", **common))
    paper2 = idempotency_key(OrderRequest(venue="paper:kalshi", **common))
    assert main != paper2


def test_a_scoped_row_sizes_through_the_unmodified_pipeline():
    """paper2 is not a different pipeline -- it is the same one fed the price we
    could actually get, so every gate and refusal name still applies."""
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    scoped, _ = scope_rows_to_venue(
        [_row(best=-130, ev_pct=1.0, book_prices={"draftkings": -130, "kalshi": -105})],
        "kalshi",
    )
    plan = commit_portfolio(scoped, selected_date="2026-08-22")
    positions = plan.get("positions") or []
    assert positions, plan.get("refusals")
    assert positions[0]["book"] == "kalshi"
    assert positions[0]["price"] == -105

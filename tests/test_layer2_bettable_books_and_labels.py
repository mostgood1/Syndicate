"""`#444`/`#445` -- the board may only recommend a price you can actually take,
and it must never name a team for a bet that is AGAINST that team.

Every number in these tests came off the served board on 2026-08-16T16:20:21Z
(108 rows), not off a fixture:

    best book outside the operator's list     27 of 108   25.0%
    of those, h2h_lay with no bettable book    9
    prop cards attributing the player to away 56 of 108
"""
from __future__ import annotations

from syndicate.features.shared import book_shortlist
from syndicate.features.shared.layer2_board import (
    _pick_label,
    _row_team,
    build_layer2_rows,
    layer2_rows_to_board_cards,
)


def _row(**overrides):
    row = {
        "sport": "mlb",
        "kind": "game",
        "event_id": "evt-1",
        "market": "h2h",
        "segment": "full",
        "line": None,
        "player_name": None,
        "home_team": "Los Angeles Dodgers",
        "away_team": "Milwaukee Brewers",
        "commence_time": "2026-08-16T20:10:00Z",
        "sides": ["home", "away"],
        "books_quoting": 4,
        "game": {"state": "pregame", "status_token": "3:10P CT"},
        "best": {
            "home": {"price": 120, "bookmaker": "betopenly", "age_seconds": 20.0, "books_quoting": 4},
            "away": {"price": -110, "bookmaker": "betopenly", "age_seconds": 20.0, "books_quoting": 4},
        },
        "cells": {
            "betopenly": {"home": {"price": 120}, "away": {"price": -110}},
            "draftkings": {"home": {"price": 114}, "away": {"price": -118}},
        },
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------
# book_shortlist -- the one owner
# --------------------------------------------------------------------------


def test_unknown_book_is_not_bettable():
    """Unknown must not default permissive -- it would readmit what this removes."""
    assert book_shortlist.is_bettable("draftkings") is True
    assert book_shortlist.is_bettable("betopenly") is False
    assert book_shortlist.is_bettable(None) is False
    assert book_shortlist.is_bettable("") is False
    assert book_shortlist.is_bettable("  DraftKings  ") is True


def test_best_bettable_ignores_a_better_unbettable_price():
    """+205 at a book you cannot use is not better than +184 at one you can."""
    got = book_shortlist.best_bettable({"betopenly": 205, "pinnacle": 184})
    assert got == ("pinnacle", 184)


def test_best_bettable_is_none_when_no_listed_book_quotes():
    """The `h2h_lay` case: exchanges only, so there is no price to fall back to."""
    assert book_shortlist.best_bettable({"betfair_ex_eu": 108, "matchbook": 105}) is None
    assert book_shortlist.best_bettable({}) is None
    assert book_shortlist.best_bettable(None) is None


def test_ties_resolve_by_list_order_not_dict_order():
    """A recommendation that changes book between identical builds reads as a line move."""
    forward = book_shortlist.best_bettable({"fanduel": 150, "draftkings": 150})
    backward = book_shortlist.best_bettable({"draftkings": 150, "fanduel": 150})
    assert forward == backward == ("draftkings", 150)


# --------------------------------------------------------------------------
# the candidate build
# --------------------------------------------------------------------------


def test_the_recommended_price_comes_from_a_bettable_book():
    result = build_layer2_rows([_row()])
    assert result["opportunities"], "the row has a bettable book and must survive"
    for candidate in result["opportunities"]:
        assert candidate["quote"]["bookmaker"] == "draftkings"
    assert result["repriced_to_bettable"] == 2


def test_the_unrestricted_best_is_kept_so_the_cost_is_readable():
    """A filter that silently changes the headline price cannot be audited."""
    result = build_layer2_rows([_row()])
    home = next(c for c in result["opportunities"] if c["side"] == "home")
    assert home["quote"]["price"] == 114
    assert home["quote"]["best_any_book"] == {"bookmaker": "betopenly", "price": 120}


def test_a_row_no_listed_book_quotes_is_dropped_not_repriced():
    """9 served rows were exchange-only lay markets. There is no fallback price."""
    row = _row(
        market="h2h_lay",
        best={
            "home": {"price": 108, "bookmaker": "betfair_ex_eu", "age_seconds": 20.0, "books_quoting": 2},
            "away": {"price": 110, "bookmaker": "betfair_ex_eu", "age_seconds": 20.0, "books_quoting": 2},
        },
        cells={
            "betfair_ex_eu": {"home": {"price": 108}, "away": {"price": 110}},
            "matchbook": {"home": {"price": 105}, "away": {"price": 107}},
        },
    )
    result = build_layer2_rows([row])
    assert result["opportunities"] == []
    assert result["no_bettable_book"] == 2


def test_a_row_with_no_book_information_at_all_is_kept():
    """Absent evidence is not evidence of absence -- the filter must not delete
    rows it has nothing to judge. This is the shape that broke 8 tests: a
    hand-built row carrying `best` but no `cells`."""
    row = _row(cells={}, best={"home": {"price": 120, "age_seconds": 20.0, "books_quoting": 4}}, sides=["home"])
    result = build_layer2_rows([row])
    assert result["sides_priced"] == 1
    assert result["no_bettable_book"] == 0, "nothing was known about the book, so nothing was proven against it"
    assert result["candidates"] == 1, "the row reached the gate instead of being deleted by the book filter"


# --------------------------------------------------------------------------
# labelling
# --------------------------------------------------------------------------


def test_a_lay_bet_never_renders_as_a_bare_team_name():
    """The most dangerous string this board can emit: not vague, INVERTED."""
    label = _pick_label({"market": "h2h_lay", "side": "home", "home_team": "Los Angeles Dodgers"})
    assert "Los Angeles Dodgers" in label
    assert label != "Los Angeles Dodgers"
    assert "LAY" in label


def test_a_back_bet_is_unchanged_by_the_lay_rule():
    assert _pick_label({"market": "h2h", "side": "home", "home_team": "Los Angeles Dodgers"}) == (
        "Los Angeles Dodgers"
    )


def test_a_prop_is_still_the_player():
    assert _pick_label({"market": "batter_rbis", "side": "over", "player_name": "Andy Pages"}) == "Andy Pages"


def test_a_prop_is_not_attributed_to_the_away_team():
    """Andy Pages is a Dodger; the served card said 'Milwaukee Brewers'."""
    row = {"side": "over", "player_name": "Andy Pages"}
    assert _row_team(row, "Los Angeles Dodgers", "Milwaukee Brewers") is None


def test_a_game_side_still_resolves_its_team():
    assert _row_team({"side": "home"}, "Los Angeles Dodgers", "Milwaukee Brewers") == "Los Angeles Dodgers"
    assert _row_team({"side": "away"}, "Los Angeles Dodgers", "Milwaukee Brewers") == "Milwaukee Brewers"


def test_cards_carry_no_team_for_a_prop_rather_than_the_wrong_one():
    cards = layer2_rows_to_board_cards(
        [
            {
                "sport": "mlb",
                "kind": "prop",
                "market": "batter_rbis",
                "side": "over",
                "player_name": "Andy Pages",
                "home_team": "Los Angeles Dodgers",
                "away_team": "Milwaukee Brewers",
                "ev_pct": 5.0,
                "quote": {"price": 215},
                "score": {"score": 3.8},
            }
        ]
    )
    assert cards[0]["team"] is None
    assert cards[0]["selection"] == "Andy Pages"


# --------------------------------------------------------------------------
# the sim's view (`#445`) -- labelled, never suppressed
# --------------------------------------------------------------------------


def test_the_three_sim_states_are_distinguishable():
    """'disagrees' and 'no view' need different fixes, so they need different words."""

    def view(model_edge):
        cards = layer2_rows_to_board_cards(
            [
                {
                    "sport": "mlb",
                    "market": "h2h",
                    "side": "home",
                    "ev_pct": 2.0,
                    "model_edge_pct": model_edge,
                    "quote": {"price": 120},
                    "score": {"score": 1.5},
                }
            ]
        )
        return cards[0]

    assert view(-3.1)["sim_view"] == "disagrees"
    assert view(-3.1)["sim_disagreement_pct"] == -3.1
    assert view(2.4)["sim_view"] == "agrees"
    assert view(None)["sim_view"] == "none"
    assert "sim_disagreement_pct" not in view(2.4)


def test_a_disagreeing_row_is_still_served():
    """Suppressing would be a weight of -infinity smuggled in as a rule, on a
    model whose `settled` count is 0."""
    result = build_layer2_rows([_row(projection={"edge_vs_market_pct": -4.0})])
    assert result["opportunities"], "the row is labelled, not removed"

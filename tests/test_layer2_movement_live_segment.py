"""`#372` re-enabled, live projections joined, and interval lines labelled.

Every number here came off the served board on 2026-08-16, not off a fixture:

    live rows carrying a PREGAME projection      54 of 54
    rows with a non-`full` segment               30 of 102
    movement keys on any served row               0
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.shared.clv_opening_ledger import _opening_key
from syndicate.features.shared.layer2_board import movement_join_key
from syndicate.features.shared.layer2_board import (
    _live_projection_columns,
    _movement_from_opening,
    _segment_label,
    build_layer2_rows,
)
from syndicate.features.shared.opportunity_signals import blended_score

NOW = datetime.now(timezone.utc)


def _row(**over):
    row = {
        "sport": "mlb",
        "event_id": "e1",
        "market": "totals",
        "segment": "full",
        "side": "over",
        "line": 8.5,
        "quote": {
            "price": -105,
            "bookmaker": "draftkings",
            "book_prices": {"draftkings": -105, "fanduel": -108},
        },
    }
    row.update(over)
    return row


def _openings(row, *, price=-105, line=8.5, minutes=20, books=None):
    # `movement_join_key`, not `_opening_key` (`#446`). The production index is
    # built with the stable key -- one that excludes `line` and `bookmaker` --
    # because keying movement on those means only UNMOVED rows can match their
    # own opening. A fixture keyed the old way tests a join production no
    # longer performs.
    key = movement_join_key(row)
    return {
        key: {
            "key": key,
            "captured_at": (NOW - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
            "price": price,
            "line": line,
            "bookmaker": "draftkings",
            "book_prices": books if books is not None else {"draftkings": price},
        }
    }


# --------------------------------------------------------------------------
# `#372`: movement must do NO IO. That is the property that makes it safe.
# --------------------------------------------------------------------------


def test_movement_does_no_io(monkeypatch):
    """The old implementation loaded a ~20MB shard per row and stalled the
    build for 70 minutes with no exception. Any read here is that defect."""
    import builtins

    opened = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda *a, **k: (opened.append(a[0]), real_open(*a, **k))[1])
    row = _row()
    _movement_from_opening(row, _openings(row))
    assert opened == [], f"movement opened files: {opened}"


def test_absence_is_reported_never_blank():
    """`#368` exists because 'we do not track this' and 'it has not moved'
    rendered identically as a dash and the column read as broken."""
    assert _movement_from_opening({"market": "batter_rbis"}, {})["movement_state"] == "not_tracked"
    assert _movement_from_opening({"market": "totals"}, None)["movement_state"] == "no_openings"
    row = _row()
    assert _movement_from_opening(row, {"other": {}})["movement_state"] == "no_opening_for_row"
    assert _movement_from_opening(row, _openings(row))["movement_state"] == "flat"


# --------------------------------------------------------------------------
# Direction. The line half is SIDE-DEPENDENT and the first version got it wrong.
# --------------------------------------------------------------------------


def test_price_direction_is_side_independent():
    """A larger American number always pays more, in both signs."""
    row = _row(market="h2h", side="home", line=None)
    got = _movement_from_opening(row, _openings(row, price=-125, line=None, books={"draftkings": -125}))
    assert got["movement_price_delta"] == 20.0
    assert got["movement_direction"] == "toward"


def test_line_direction_is_side_aware():
    """9.0 -> 8.5 is FAVOURABLE to an over and hostile to an under. The first
    version compared the raw delta and called both 'against'."""
    over = _row(side="over", line=8.5)
    under = _row(side="under", line=8.5)
    assert _movement_from_opening(over, _openings(over, line=9.0))["movement_line_direction"] == "toward"
    assert _movement_from_opening(under, _openings(under, line=9.0))["movement_line_direction"] == "against"
    over_up = _row(side="over", line=9.0)
    under_up = _row(side="under", line=9.0)
    assert _movement_from_opening(over_up, _openings(over_up, line=8.5))["movement_line_direction"] == "against"
    assert _movement_from_opening(under_up, _openings(under_up, line=8.5))["movement_line_direction"] == "toward"


def test_price_delta_prefers_same_book_and_says_which():
    """The board publishes the best of N and the best book can change between
    builds; differencing across a switch measures the switch, not the market."""
    row = _row()
    same = _movement_from_opening(row, _openings(row, price=-125, books={"draftkings": -125}))
    assert same["movement_basis"] == "same_book" and same["movement_book"] == "draftkings"
    switched = _movement_from_opening(row, _openings(row, price=-115, books={"betmgm": -115}))
    assert switched["movement_basis"] == "best_of_n"


# --------------------------------------------------------------------------
# Steam needs BOTH a size and a clock.
# --------------------------------------------------------------------------


def test_steam_requires_a_sharp_move_in_a_short_window():
    row = _row()
    fast = _movement_from_opening(row, _openings(row, price=-125, minutes=25, books={"draftkings": -125}))
    assert fast["steam"] is True and "25 min" in fast["steam_reason"]
    slow = _movement_from_opening(row, _openings(row, price=-125, minutes=300, books={"draftkings": -125}))
    assert "steam" not in slow, "a 20-point drift over five hours is not steam"
    small = _movement_from_opening(row, _openings(row, price=-108, minutes=10, books={"draftkings": -108}))
    assert "steam" not in small


# --------------------------------------------------------------------------
# The score: capped, so movement breaks ties and never dominates.
# --------------------------------------------------------------------------


def test_movement_is_capped_not_merely_weighted():
    """The failure mode that killed `_SCORE_SIM_WEIGHT` was DOMINATION
    (ev ~ -5 against model_edge ~ +12). A cap is the structural fix."""
    base = dict(ev_pct=4.0, books_quoting=6, book_age_seconds=100, price=-105, fair_prob=0.52)
    big = blended_score(**base, movement_price_delta=60)
    mid = blended_score(**base, movement_price_delta=20)
    assert big["movement_component"] == mid["movement_component"] == 1.0
    assert big["movement_capped"] is True and mid["movement_capped"] is False
    # A materially better price still wins against a maximal move.
    assert blended_score(**dict(base, ev_pct=12.0))["value_pct"] > big["value_pct"]


def test_zero_movement_is_distinguishable_from_no_movement_data():
    base = dict(ev_pct=4.0, books_quoting=6, book_age_seconds=100, price=-105, fair_prob=0.52)
    assert blended_score(**base, movement_price_delta=0)["movement_component"] == 0.0
    assert blended_score(**base)["movement_component"] is None


def test_the_scored_movement_is_the_one_the_card_shows():
    """Ranking on a number the card does not display is `#364`'s unit mismatch."""
    grid_row = {
        "sport": "mlb", "kind": "game", "event_id": "e1", "market": "totals",
        "segment": "full", "line": 8.5, "player_name": None,
        "home_team": "H", "away_team": "A", "commence_time": "2026-08-16T20:00:00Z",
        "sides": ["over", "under"], "books_quoting": 4,
        "game": {"state": "pregame"},
        "best": {
            "over": {"price": -105, "bookmaker": "draftkings", "age_seconds": 10.0, "books_quoting": 4},
            "under": {"price": -105, "bookmaker": "draftkings", "age_seconds": 10.0, "books_quoting": 4},
        },
        "cells": {"draftkings": {"over": {"price": -105, "line": 8.5}, "under": {"price": -105, "line": 8.5}}},
    }
    over = _row(side="over", line=8.5)
    result = build_layer2_rows([grid_row], openings=_openings(over, price=-125, books={"draftkings": -125}))
    scored = [c for c in result["opportunities"] if c["side"] == "over"]
    assert scored, "the over side should survive"
    candidate = scored[0]
    assert candidate["movement"]["movement_price_delta"] == 20.0
    assert candidate["score"]["movement_component"] == 1.0


# --------------------------------------------------------------------------
# Live projections: the PREGAME number must never be copied into the live cell.
# --------------------------------------------------------------------------


def test_a_pregame_projection_never_fills_the_live_column():
    """54 of 54 live rows carried `source: game_simulation`, a FULL-GAME
    pregame distribution. Showing 10.5 beside a live total in the 5th is a
    full-game number against a remaining-game line."""
    assert _live_projection_columns({"projection": {"source": "game_simulation", "projected": 10.5}}) == {}


def test_the_live_column_is_filled_only_from_live_keys():
    got = _live_projection_columns({"projection": {"live_projected": 7.2, "live_model_prob_over": 0.61}})
    assert got["live_projection"] == 7.2
    assert got["live_total"] == 7.2, "game lines resolve live_total, props resolve live_projection"
    assert got["live_model_probability"] == 0.61


def test_the_gameline_block_is_a_fallback_source():
    got = _live_projection_columns({"live_gameline": {"live_projected": 4.4}})
    assert got["live_projection"] == 4.4 and got["live_aware"] is True


# --------------------------------------------------------------------------
# Interval / alt lines.
# --------------------------------------------------------------------------


def test_full_game_is_not_labelled():
    """Labelling the common case adds noise to every row to disambiguate a
    minority."""
    assert _segment_label("full") is None
    assert _segment_label(None) is None


def test_interval_segments_are_named_in_words():
    assert _segment_label("first5") == "1st 5 innings"
    assert _segment_label("first1") == "1st inning"
    assert _segment_label("h1") == "1st half"
    assert _segment_label("q4") == "4th quarter"
    assert _segment_label("p2") == "2nd period"


def test_an_unknown_segment_is_shown_not_swallowed():
    """A segment this map has not seen is exactly where the reader most needs
    telling the line is not full-game."""
    assert _segment_label("first7_alt") == "first7 alt"


# ---------------------------------------------------------------------------
# `#446`: movement was keyed on the thing it measures.
#
# Found by asking why opening coverage FELL (31% -> 29%) instead of rising as
# the ledger accumulated. It was not thin data -- `clv_opening_ledger._opening_key`
# includes `line` and `bookmaker`, so a row could only match its own opening if
# it had NOT moved. Measured across two artifacts 20 min apart: stable key
# matched 20, full key matched 14, and of the 20 the line changed on 6 and the
# book on 5. The dropped third were exactly the rows with something to report.
# ---------------------------------------------------------------------------


def _mv_opening(**over):
    base = {
        "event_id": "e1", "market": "spreads", "player_name": None, "segment": "full",
        "side": "home", "line": -1.5, "price": -110, "bookmaker": "draftkings",
        "captured_at": "2026-08-16T19:00:00Z",
        "book_prices": {"draftkings": -110, "fanduel": -108},
    }
    base.update(over)
    return base


def _mv_row(**over):
    base = {
        "event_id": "e1", "market": "spreads", "player_name": None, "segment": "full",
        "side": "home", "line": -1.5,
        "quote": {"price": -110, "bookmaker": "draftkings",
                  "book_prices": {"draftkings": -110, "fanduel": -108}},
    }
    base.update(over)
    return base


def test_the_join_key_survives_a_line_move():
    """The whole defect in one assertion."""
    from syndicate.features.shared.layer2_board import movement_join_key

    assert movement_join_key(_mv_opening()) == movement_join_key(_mv_row(line=-2.5))


def test_the_join_key_survives_a_best_book_switch():
    from syndicate.features.shared.layer2_board import movement_join_key

    moved = _mv_row(quote={"price": -135, "bookmaker": "fanduel", "book_prices": {"fanduel": -135}})
    assert movement_join_key(_mv_opening()) == movement_join_key(moved)


def test_a_row_that_moved_line_AND_book_is_still_measured():
    """The production case. Under the old key this row was invisible."""
    from syndicate.features.shared.layer2_board import _movement_from_opening, movement_join_key

    opening = _mv_opening()
    moved = _mv_row(
        line=-2.5,
        quote={"price": -135, "bookmaker": "fanduel",
               "book_prices": {"draftkings": -140, "fanduel": -135}},
    )
    out = _movement_from_opening(moved, {movement_join_key(opening): opening})

    assert out["movement_state"] == "tracked"
    assert out["movement_line_delta"] == -1.0
    # Same-book via `book_prices`, NOT best-of-N across a book switch.
    assert out["movement_basis"] == "same_book"
    assert out["movement_book"] == "fanduel"
    assert out["movement_price_delta"] == -27.0


def test_that_same_row_now_reaches_the_steam_threshold():
    """Steam was structurally suppressed, not merely untested.

    A sharp move usually comes WITH a line move or a book switch -- the exact
    conditions that broke the old key. So the moves large enough to be steam
    were the ones most reliably erased before the detector saw them.
    """
    from syndicate.features.shared.layer2_board import (
        _STEAM_PRICE_POINTS,
        _movement_from_opening,
        movement_join_key,
    )

    opening = _mv_opening(captured_at=_recent_iso())
    moved = _mv_row(
        line=-2.5,
        quote={"price": -135, "bookmaker": "fanduel",
               "book_prices": {"draftkings": -140, "fanduel": -135}},
    )
    out = _movement_from_opening(moved, {movement_join_key(opening): opening})
    assert abs(out["movement_price_delta"]) >= _STEAM_PRICE_POINTS
    assert out.get("steam") is True
    assert "fanduel" in (out.get("steam_reason") or "")


def test_the_old_full_key_would_have_missed_all_of_the_above():
    """Guards the fix by proving the OLD behaviour was broken.

    Without this, a future change could silently reinstate the full key and
    every test above would still pass on unmoved rows.
    """
    from syndicate.features.shared.clv_opening_ledger import _opening_key

    old_open = _opening_key({**_mv_opening(), "quote": {"bookmaker": "draftkings"}})
    old_now = _opening_key(
        _mv_row(line=-2.5, quote={"price": -135, "bookmaker": "fanduel"})
    )
    assert old_open != old_now, "if these ever match, this test is measuring nothing"


def _recent_iso():
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")

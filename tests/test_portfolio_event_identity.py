"""#297 -- a bet logged from an L2-A row must be SETTLEABLE, not merely stored.

The pass condition is a non-empty key intersection with what the grader emits,
not an HTTP 200. The whole failure mode is that the POST succeeds either way and
the record dies silently at grading weeks later.

Measured on production L2-A rows, 2026-08-09, before this fix:
    GAME row -> record keys {event_id, market}
    PROP row -> record keys {event_id, market, 'sonia citron'}
`_graded_row_keys` emits only {selection, player, team, home, away, title}, so
the game row's intersection was empty against EVERY graded row that could exist,
and the prop row's join rested on one player-name string.
"""
from __future__ import annotations

from syndicate.features.shared.evaluation_settlement import (
    _evaluation_record_keys,
    _graded_row_keys,
    normalize_portfolio_event_identity,
)


def _l2a_game_row():
    """An L2-A game candidate, in the shape the board actually emits."""
    return {
        "sport": "soccer",
        "event_id": "a22463fa1e60fc06243141f286915661",
        "kind": "game",
        "market": "h2h",
        "side": "away",
        "home_team": "FC Twente Enschede",
        "away_team": "Ajax",
        "line": None,
    }


def _l2a_prop_row():
    return {
        "sport": "wnba",
        "event_id": "06f2966e428481e954611c5d5c21ef9f",
        "kind": "prop",
        "market": "player_double_double",
        "side": "Yes",
        "player_name": "Sonia Citron",
        "home_team": "Washington Mystics",
        "away_team": "Chicago Sky",
        "line": 0.5,
    }


def _keys(event):
    return _evaluation_record_keys({"recommendation": event, "sport": event.get("sport")})


def test_game_row_is_unsettleable_without_normalization():
    """Pins the defect, so the fix cannot be quietly reverted."""
    graded = {"selection": "Ajax", "team": "Ajax", "home": "FC Twente Enschede", "away": "Ajax"}
    assert _keys(_l2a_game_row()).isdisjoint(_graded_row_keys(graded)), (
        "a raw L2-A game row must be shown to have NO overlap -- if this ever "
        "fails the fixture has drifted and the rest of this file proves nothing"
    )


def test_normalized_game_row_shares_a_key_with_the_graded_row():
    graded = {"selection": "Ajax", "team": "Ajax", "home": "FC Twente Enschede", "away": "Ajax"}
    keys = _keys(normalize_portfolio_event_identity(_l2a_game_row()))

    overlap = keys & _graded_row_keys(graded)
    assert overlap, f"no shared key: record={sorted(keys)} graded={sorted(_graded_row_keys(graded))}"
    assert "ajax" in overlap, "the backed side's team name is what should carry the join"


def test_normalized_prop_row_keeps_the_player_join():
    graded = {"selection": "over", "player": "Sonia Citron", "team": "Washington Mystics"}
    keys = _keys(normalize_portfolio_event_identity(_l2a_prop_row()))
    assert "sonia citron" in (keys & _graded_row_keys(graded))


def test_market_token_is_not_added_as_a_key():
    """The dangerous widening. A category-shaped key lets a record overlap a
    graded row for a DIFFERENT game, pass _markets_compatible, and skip the line
    check -- a silently WRONG settlement, worse than no match."""
    other_game = {"selection": "Feyenoord", "team": "Feyenoord", "home": "Feyenoord", "away": "PSV"}
    keys = _keys(normalize_portfolio_event_identity(_l2a_game_row()))
    assert keys.isdisjoint(_graded_row_keys(other_game)), (
        "an unrelated game's graded row must NOT match on a shared market token"
    )


def test_normalization_does_not_overwrite_an_explicit_caller():
    """A caller already speaking the ledger's vocabulary must be left alone."""
    event = dict(_l2a_game_row(), home="Explicit Home", away="Explicit Away", team="Explicit Team")
    out = normalize_portfolio_event_identity(event)
    assert out["home"] == "Explicit Home"
    assert out["away"] == "Explicit Away"
    assert out["team"] == "Explicit Team"


def test_nested_recommendation_shape_is_normalized_in_place():
    """The endpoint receives {recommendation: {...}} as often as a flat event."""
    out = normalize_portfolio_event_identity({"recommendation": _l2a_game_row()})
    rec = out["recommendation"]
    assert rec.get("away") == "Ajax" and rec.get("home") == "FC Twente Enschede"
    assert rec.get("team") == "Ajax", "side=away must resolve `team` to the away side"

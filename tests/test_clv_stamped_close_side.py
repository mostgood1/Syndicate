"""The stamped close belongs to `entity`, so it is only valid for that side.

`odds_refresh_tracking.py:1602` writes `closing_price = previous_odds`, and
`previous_odds` is one team's price. Measured on mlb 2026-08-15 across every
market carrying a stamp: `entity == home_team` on 18 of 18.

`resolve_close` path 1 read that scalar with no side handling, so an away-side
opening was differenced against the HOME close. The production case pinned
below is event dbbb481a (Yankees @ Blue Jays): opened away -186, paired with
+168 -- which is Toronto's price -- for a clv of -27.72 that is not CLV at all.

The fix does not fabricate the missing side. It refuses the stamp for the wrong
side and falls through to `last_pregame_quote`, which reads the `line` block and
is side-aware. Every clean row in production already came from that path.
"""
from __future__ import annotations

from syndicate.features.shared.clv_join import resolve_close


HOME, AWAY = "Toronto Blue Jays", "New York Yankees"


def _opening(side, price=-186, **over):
    row = {
        "key": "k1", "sport": "mlb", "market": "h2h", "side": side, "line": None,
        "player_name": None, "bookmaker": "fanduel", "price": price,
        "event_id": "dbbb481a", "captured_at": "2026-08-15T05:07:53Z",
        "commence_time": "2026-08-15T19:08:00Z",
        "home_team": HOME, "away_team": AWAY,
        "book_prices": {"fanduel": price},
    }
    row.update(over)
    return row


def _state(*, entity=HOME, with_history=True):
    """A stamped market. `entity` is whose price `closing_price` is."""
    state = {
        "closing_price": 168.0,
        "closing_line": 168.0,
        "closing_captured_at": "2026-08-15T20:34:26+00:00",
    }
    if with_history:
        state["history"] = [{
            "entity": entity,
            "captured_at": "2026-08-15T18:00:00Z",
            "last_odds": 156.0,
            "line": {"away_odds": "-190", "home_odds": "+160"},
        }]
    return state


# --- the production defect --------------------------------------------------

def test_away_opening_does_not_take_the_home_stamped_close():
    """The exact row that produced -27.72."""
    out = resolve_close(_opening("away"), _state())
    assert out["close_source"] != "observed_transition"
    assert out["close_price"] != 168.0, "the home team's price is not the away close"
    assert out["stamped_close_skipped"] == "stamped_close_is_home_side"


def test_the_away_row_falls_through_to_the_side_aware_close():
    """Refused, not discarded -- it gets the correct away price instead."""
    out = resolve_close(_opening("away"), _state())
    assert out["close_source"] == "last_pregame_quote"
    assert out["close_price"] == -190.0, "away_odds from the line block"


def test_home_opening_still_uses_its_own_stamped_close():
    """The stamp IS this side's price, so nothing is lost for home rows."""
    out = resolve_close(_opening("home", price=156), _state())
    assert out["close_source"] == "observed_transition"
    assert out["close_price"] == 168.0
    assert out.get("stamped_close_skipped") is None


def test_an_away_entity_flips_which_side_may_use_the_stamp():
    """Nothing is hardcoded to home -- it follows the entity.

    18/18 stamped markets were home on 2026-08-15, but that is an observation
    about today's data, not an invariant, so the code reads the entity.
    """
    away_out = resolve_close(_opening("away"), _state(entity=AWAY))
    assert away_out["close_source"] == "observed_transition"
    home_out = resolve_close(_opening("home", price=156), _state(entity=AWAY))
    assert home_out["stamped_close_skipped"] == "stamped_close_is_away_side"


# --- unknown must not take the permissive branch ----------------------------

def test_an_unidentifiable_entity_refuses_the_stamp():
    out = resolve_close(_opening("home", price=156), _state(with_history=False))
    assert out["stamped_close_skipped"] == "stamped_close_entity_unknown"
    assert out["close_source"] != "observed_transition"


def test_an_entity_matching_neither_team_refuses_the_stamp():
    out = resolve_close(_opening("home", price=156), _state(entity="Some Other Club"))
    assert out["stamped_close_skipped"] == "stamped_close_entity_unknown"


def test_totals_can_never_claim_the_stamp():
    """over/under sides against a team entity: unattributable by construction."""
    out = resolve_close(_opening("over", price=-110, market="totals", line=7.5), _state())
    assert out["close_source"] != "observed_transition"
    assert str(out["stamped_close_skipped"]).startswith("stamped_close_is_")


def test_entity_match_is_case_insensitive():
    out = resolve_close(_opening("home", price=156), _state(entity=HOME.upper()))
    assert out["close_source"] == "observed_transition"

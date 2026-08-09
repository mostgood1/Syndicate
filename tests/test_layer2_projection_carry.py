"""#270 -- the sim's projection must reach the candidate.

`attach_projections` stamps `projection` onto the grid row and every sport's
join agrees on that key (wnba_projections:164, soccer_projections:291,
prop_projections:712). `build_layer2_rows` then rebuilt each candidate from
`_IDENTITY_FIELDS` plus an explicit list, and `projection` was in neither -- so
the board's "Projected" fact had no value to render even where the projection
existed. Measured on production 2026-08-09: soccer carried 216
`rows_with_projection` and wnba 83, and `projection` appeared on zero of 200
served rows.

The distinction these tests pin is between ABSENT and NULL. A market with no
projection must not acquire a null one: the props pipeline treats "no
projection" and "a projection of 0" as different facts, and a null would make a
market look modelled-and-worthless rather than unmodelled.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared.layer2_board import build_layer2_rows


def _grid_row(**overrides):
    """One two-sided market instance in the shape build_book_grid emits."""
    row = {
        "sport": "wnba",
        "event_id": "evt-1",
        "kind": "prop",
        "market": "player_points",
        "segment": "full",
        "line": 18.5,
        "player_name": "A. Player",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2099-01-01T00:00:00Z",
        "sides": ["over", "under"],
        "books_quoting": 2,
        "cells": {},
        "best": {
            "over": {"price": -110, "bookmaker": "draftkings", "books_quoting": 2, "age_seconds": 30.0},
            "under": {"price": -110, "bookmaker": "fanduel", "books_quoting": 2, "age_seconds": 30.0},
        },
    }
    row.update(overrides)
    return row


def _candidates(row):
    return list(build_layer2_rows([row]).get("opportunities") or [])


def test_projection_reaches_the_candidate():
    rows = _candidates(_grid_row(projection=21.4))
    assert rows, "fixture must produce at least one candidate"
    assert all(r.get("projection") == 21.4 for r in rows), (
        "the projection stamped on the grid row must be carried onto every "
        "candidate built from it -- this is the #270 join"
    )


def test_absent_projection_stays_absent_rather_than_null():
    rows = _candidates(_grid_row())
    assert rows, "fixture must produce at least one candidate"
    for r in rows:
        assert "projection" not in r, (
            "an unmodelled market must not acquire a null projection -- absent "
            "means unknown, whereas null reads as 'modelled, and it is nothing'"
        )


@pytest.mark.parametrize("value", [0, 0.0])
def test_zero_projection_is_carried_not_dropped(value):
    """The falsy-but-real case. A truthiness check here would silently drop a
    genuine projection of zero, which is a meaningful prediction for a prop."""
    rows = _candidates(_grid_row(projection=value))
    assert rows, "fixture must produce at least one candidate"
    assert all(r.get("projection") == value for r in rows)
    assert all("projection" in r for r in rows)

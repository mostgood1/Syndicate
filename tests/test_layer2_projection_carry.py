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

**AMENDED `#510`, 2026-08-22: `projection` IS A MAPPING, NOT A SCALAR.** These
fixtures passed `projection=21.4` and every one of them failed, because
`_model_edge_for` (`layer2_board.py:829`) returns None for anything that is not
a Mapping -- so the row scored None and the opportunities filter dropped it
before the carry could be observed at all. What the producers actually stamp is
a dict carrying `edge_vs_market_pct` / `edge_vs_line` /
`edge_unavailable_reason` (`prop_projections.py:1027`).

The `#270` carry mechanism itself was never broken; only these fixtures were.
One consequence is recorded in `test_absent_projection_stays_absent_rather_
than_null`: with a model view now REQUIRED to score, a projection-less row
cannot reach `opportunities` at all, so the null failure mode is structurally
unreachable there rather than merely untested.
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
    rows = _candidates(_grid_row(projection={"edge_vs_market_pct": 6.0, "mean": 21.4}))
    assert rows, "fixture must produce at least one candidate"
    assert all(r.get("projection") == {"edge_vs_market_pct": 6.0, "mean": 21.4} for r in rows), (
        "the projection stamped on the grid row must be carried onto every "
        "candidate built from it -- this is the #270 join"
    )


def test_absent_projection_stays_absent_rather_than_null():
    """`#510`. Re-aimed, and the reason matters more than the assertion.

    Originally this built a candidate with no projection and asserted the key
    was ABSENT rather than null. Under the current board that state cannot
    reach `opportunities` at all: `_model_edge_for` requires a `projection`
    MAPPING carrying a numeric `edge_vs_market_pct`, `blended_score` returns
    None without a model view, and the opportunities filter drops every
    candidate whose score is None. Measured: a row with no projection yields
    `candidates=2, scored=0, opportunities=0`.

    So the null failure mode is now structurally unreachable here rather than
    merely untested -- and asserting a bare `rows == []` would pass for a dozen
    unrelated reasons. What is still worth pinning, and is pinned below, is
    that the row is dropped by the SCORING gate specifically, with the
    candidate built and no fabricated projection anywhere in it.
    """
    result = build_layer2_rows([_grid_row()])
    assert result["candidates"] == 2, "the candidate must still be BUILT"
    assert result["scored"] == 0, "and dropped for having no model view, not for being malformed"
    assert list(result.get("opportunities") or []) == []


def test_a_projection_without_a_market_edge_does_not_become_an_opportunity():
    """The other half of absent-vs-null: a projection dict that carries a
    mean but no `edge_vs_market_pct` is a real projection in the wrong UNITS
    (`edge_vs_line` is in rebounds/goals, not probability points). It must not
    be scored as though it were a probability view."""
    result = build_layer2_rows([_grid_row(projection={"edge_vs_market_pct": None, "edge_vs_line": 2.0})])
    assert result["candidates"] == 2
    assert result["scored"] == 0
    assert list(result.get("opportunities") or []) == []


@pytest.mark.parametrize("value", [0, 0.0])
def test_zero_projection_is_carried_not_dropped(value):
    """The falsy-but-real case, and the sharpest surviving form of the original
    intent. A truthiness check anywhere on this path would silently drop a
    genuine model edge of zero -- "the market is exactly right" is a
    prediction, not a missing one."""
    projection = {"edge_vs_market_pct": value}
    rows = _candidates(_grid_row(projection=projection))
    assert rows, "fixture must produce at least one candidate"
    assert all(r.get("projection") == projection for r in rows)
    assert all("projection" in r for r in rows)

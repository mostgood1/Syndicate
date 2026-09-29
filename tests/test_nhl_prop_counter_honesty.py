"""NHL's projection join must COUNT its prop population, not skip it silently.

WHY `[lane nhl-prop-counter-honesty, 2026-09-29]`. `attach_nhl_game_projections`
used to `continue` past every player-prop row BEFORE incrementing `considered`, so
the returned coverage could not even say "0 of 459". On production that made a
HEALTHY game join -- 10 of 10 game rows projected -- read as 10 against 834 NHL
candidates, i.e. as a near-total collapse. Two separate diagnoses went to the join
and the artifact read before the counter was found, and neither was at fault.

The distinction these tests protect: an UNCOUNTED row and a REFUSED-AND-COUNTED
row look identical in a coverage rate, and only the second one is actionable.
"""
from __future__ import annotations

from syndicate.features.nhl.game_projections import (
    NhlGameProjectionIndex,
    attach_nhl_game_projections,
)


def _index(date="2026-09-29"):
    """An empty but VALID index: no game matches, so attachment is 0 while the
    counters still have to report what they saw."""
    return NhlGameProjectionIndex(date=date)


def _game_row(market="h2h", date="2026-09-29"):
    return {"kind": "game", "market": market, "commence_time": f"{date}T23:00:00Z",
            "home_team": "Boston Bruins", "away_team": "Tampa Bay Lightning",
            "segment": "full"}


def _prop_row(market="SOG", date="2026-09-29"):
    return {"kind": "prop", "market": market, "commence_time": f"{date}T23:00:00Z",
            "player_name": "David Pastrnak", "segment": "full"}


# --------------------------------------------------------------------------
# The counters
# --------------------------------------------------------------------------

def test_prop_rows_are_counted_instead_of_vanishing():
    grid = [_game_row(), _prop_row(), _prop_row("ASSISTS"), _prop_row("POINTS")]
    out = attach_nhl_game_projections(grid, _index(), selected_date="2026-09-29")
    assert out["prop_rows_considered"] == 3
    assert out["prop_rows_with_projection"] == 0


def test_the_prop_zero_carries_a_stated_reason():
    """A zero with no reason is unactionable: a code gap and an empty slate are
    the same number. NHL's is a MODEL gap and must say so."""
    out = attach_nhl_game_projections([_prop_row()], _index(), selected_date="2026-09-29")
    coverage = out["prop_coverage"]
    assert coverage["supported"] is False
    assert coverage["rows_considered"] == 1
    assert coverage["rows_with_projection"] == 0
    assert "no NHL player-prop projection source" in coverage["reason"]


def test_game_counters_are_unchanged_by_the_split():
    """Behaviour preservation: `rows_considered` still means GAME rows, so any
    existing reader is unaffected."""
    grid = [_game_row("h2h"), _game_row("totals"), _prop_row(), _prop_row()]
    out = attach_nhl_game_projections(grid, _index(), selected_date="2026-09-29")
    assert out["rows_considered"] == 2
    assert out["game_rows_considered"] == 2
    assert out["rows_considered"] == out["game_rows_considered"]
    assert out["game_rows_with_projection"] == out["rows_with_projection"]


def test_unsupported_game_markets_are_counted_apart_from_props():
    """A segment/exotic game market and a player prop are different gaps with
    different owners, so folding them together would mislabel both."""
    grid = [_game_row("h2h"), _game_row("alternate_spreads"),
            _game_row("team_totals"), _prop_row()]
    out = attach_nhl_game_projections(grid, _index(), selected_date="2026-09-29")
    assert out["rows_considered"] == 1
    assert out["rows_unsupported_game_market"] == 2
    assert out["prop_rows_considered"] == 1


# --------------------------------------------------------------------------
# Date scoping -- the two denominators must cover the same population
# --------------------------------------------------------------------------

def test_prop_rows_are_date_scoped_like_game_rows():
    """Otherwise `prop_rows_considered` spans the whole multi-date grid while
    `rows_considered` covers one date -- two populations in one payload, which is
    the defect class this lane exists to remove."""
    grid = [_game_row(date="2026-09-29"), _prop_row(date="2026-09-29"),
            _game_row(date="2026-09-30"), _prop_row(date="2026-09-30"),
            _prop_row(date="2026-09-30")]
    out = attach_nhl_game_projections(grid, _index(), selected_date="2026-09-29")
    assert out["rows_considered"] == 1
    assert out["prop_rows_considered"] == 1      # not 3


def test_without_a_selected_date_every_row_is_counted():
    grid = [_game_row(date="2026-09-29"), _prop_row(date="2026-09-30")]
    out = attach_nhl_game_projections(grid, _index(), selected_date=None)
    assert out["rows_considered"] == 1
    assert out["prop_rows_considered"] == 1


def test_a_row_with_no_commence_time_is_not_dropped_by_date_scoping():
    grid = [{"kind": "prop", "market": "SOG", "player_name": "X"}]
    out = attach_nhl_game_projections(grid, _index(), selected_date="2026-09-29")
    assert out["prop_rows_considered"] == 1


# --------------------------------------------------------------------------
# The integration that is the whole point: the gate can now see this cell
# --------------------------------------------------------------------------

def test_the_coverage_contract_now_resolves_nhl_props_as_an_attributed_zero():
    """Before this fix the cross-sport gate reported `nhl.pregame_props:
    not_reported` -- an instrument defect, because NHL emitted no prop metric at
    all. It must now resolve as a KNOWN gap instead, which is actionable and does
    not fail the gate."""
    from syndicate.features.shared import coverage_contract as cc

    grid = [_game_row()] + [_prop_row() for _ in range(459)]
    out = attach_nhl_game_projections(grid, _index(), selected_date="2026-09-29")
    cov = cc.read_sport("nhl", {"candidates": 840, "enrichment": {"projections": out}})

    props = cov.cell(cc.PREGAME_PROPS)
    assert props.status == cc.ATTRIBUTED_ZERO
    assert props.projected == 0
    assert props.considered == 459
    assert props.rate == 0.0
    assert "no NHL player-prop projection source" in props.reason
    assert not any("pregame_props" in d for d in cov.defects)

    games = cov.cell(cc.PREGAME_GAMES)
    assert games.source_key == "projections.game_rows_with_projection"
    assert games.considered == 1

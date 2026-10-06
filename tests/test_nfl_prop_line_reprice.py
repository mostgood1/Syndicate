"""An NFL prop whose LINE moved is priced at the board's line with the same model.

Lane `nfl-prop-line-reprice` (2026-10-06). The artifact holds the lines captured at build
time; a later line missed the exact-key join although the player and stat were projected.
The artifact's stored inputs reproduce its stored probabilities exactly through
`_nfl_prop_model_probability`, so the board's own line is priced with that function.
"""
from __future__ import annotations

import pytest

from syndicate.features.nfl.props import _nfl_prop_join_market_key, _nfl_prop_model_probability
from syndicate.features.shared.nfl_prop_projections import (
    NflPropProjectionIndex,
    attach_nfl_prop_projections,
)

_INPUTS = {"projected_value": 72.0, "projected_sd": 24.0, "sample_games": 5}


def _index():
    key = _nfl_prop_join_market_key("receiving_yards", "Chris Olave", 82.5)
    stored = _nfl_prop_model_probability(stat="receiving_yards", mean=72.0, stdev=24.0, n=5, line=82.5)
    index = NflPropProjectionIndex(season=2026, week=4)
    index.entries[key] = {"market": key, "sim_projection": stored, "sim_source": "artifact", **_INPUTS}
    index.row_count = 1
    return index, stored


def _row(line, player="Chris Olave"):
    return {"sport": "nfl", "kind": "prop", "market": "Receiving Yards", "player_name": player,
            "line": line, "side": "over", "home_team": "New Orleans Saints", "away_team": "Atlanta Falcons"}


def test_the_artifact_line_still_uses_the_stored_probability():
    index, stored = _index()
    rows = [_row(82.5)]
    cov = attach_nfl_prop_projections(rows, index)
    assert cov["rows_with_projection"] == 1 and cov["rows_repriced_at_line"] == 0
    assert rows[0]["projection"].get("line_repriced") is None


def test_a_moved_line_is_priced_at_the_board_line_with_the_same_model():
    index, _ = _index()
    rows = [_row(84.5)]
    cov = attach_nfl_prop_projections(rows, index)
    assert cov["rows_repriced_at_line"] == 1
    assert cov["unmatched_key_rows"] == 0
    expected = _nfl_prop_model_probability(stat="receiving_yards", mean=72.0, stdev=24.0, n=5, line=84.5)
    assert rows[0]["projection"]["model_prob_over"] == pytest.approx(expected, abs=1e-4)  # stored at 4 dp
    assert rows[0]["projection"]["line_repriced"] is True


def test_off_is_not_on_an_unprojected_player_still_misses():
    index, _ = _index()
    rows = [_row(84.5, player="Drake London")]
    cov = attach_nfl_prop_projections(rows, index)
    assert cov["rows_repriced_at_line"] == 0
    assert cov["unmatched_key_rows"] == 1
    assert rows[0].get("projection") is None

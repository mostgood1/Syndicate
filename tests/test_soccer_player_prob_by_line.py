"""Player props price off the sim's PER-LINE probabilities, not a mean.

`player_shots`/`player_shots_on_target` were priced from `expected_shots` -- a
mean, in SHOT units -- so `_model_edge_for` correctly refused to add it to an EV
percentage and those rows ranked on EV alone. `player_assists` is a LIVE market
(74 rows measured on the board 2026-08-21) and had NO projection at all. All
three probability dicts existed in the sim and were dropped by the artifact
builder's hand-written allowlist.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import soccer_projections as sp


def _index(player_entry):
    idx = sp.SoccerProjectionIndex()
    idx.by_teams[("marseille", "strasbourg")] = {"match_id": "m1", "league": "ligue_1"}
    idx.players_by_match["m1"] = {"amine gouiri": player_entry}
    idx.matches = 1
    return idx


def _row(market, line):
    return {
        "sport": "soccer", "kind": "prop", "market": market, "line": line,
        "side": "over", "player_name": "Amine Gouiri",
        "home_team": "Marseille", "away_team": "Strasbourg",
    }


FULL = {
    "expected_shots": 1.9,
    "expected_shots_on_target": 0.7,
    "expected_assists": 0.21,
    "shots_over_probabilities": {"0.5": 0.82, "1.5": 0.55, "2.5": 0.28},
    "shots_on_target_over_probabilities": {"0.5": 0.51, "1.5": 0.19},
    "assists_over_probabilities": {"0.5": 0.19, "1.5": 0.03},
}


@pytest.mark.parametrize("market,line,expected,basis", [
    ("player_shots", 2.5, 0.28, "shots_over_probabilities"),
    ("player_shots_on_target", 0.5, 0.51, "shots_on_target_over_probabilities"),
    ("player_assists", 0.5, 0.19, "assists_over_probabilities"),
])
def test_exact_line_prices_from_the_probability_dict(market, line, expected, basis):
    row = _row(market, line)
    sp.attach_soccer_projections([row], _index(FULL))
    proj = row["projection"]
    assert proj["model_prob_over"] == expected
    assert proj["basis"] == basis


def test_assists_had_no_projection_before_and_has_one_now():
    """The market was live on the board with nothing behind it."""
    row = _row("player_assists", 0.5)
    sp.attach_soccer_projections([row], _index(FULL))
    assert row.get("projection") is not None
    assert row["projection"]["model_prob_over"] == 0.19


def test_a_line_the_sim_did_not_price_falls_back_to_the_mean_not_a_neighbour():
    """0.5 and 1.5 assists are different questions. Answering one with the
    other's number is the substitution this module exists to refuse."""
    row = _row("player_shots", 3.5)          # not in the dict
    sp.attach_soccer_projections([row], _index(FULL))
    proj = row["projection"]
    assert proj["basis"] == "expected_shots"          # fell back to the mean
    assert proj["model_prob_over"] is None


def test_assists_at_an_unpriced_line_is_refused_not_guessed():
    """There is no assists MEAN mapping, so an unpriced line must yield nothing
    rather than borrow the 0.5 probability."""
    row = _row("player_assists", 2.5)
    sp.attach_soccer_projections([row], _index(FULL))
    assert row.get("projection") is None


def test_an_artifact_without_the_dicts_degrades_to_the_old_behaviour():
    """Rebuild lag is the norm here; an older artifact must not break."""
    old = {"expected_shots": 1.9, "expected_shots_on_target": 0.7}
    row = _row("player_shots", 2.5)
    sp.attach_soccer_projections([row], _index(old))
    assert row["projection"]["basis"] == "expected_shots"


def test_an_out_of_range_probability_is_rejected():
    bad = dict(FULL, shots_over_probabilities={"2.5": 1.4})
    row = _row("player_shots", 2.5)
    sp.attach_soccer_projections([row], _index(bad))
    assert row["projection"]["basis"] == "expected_shots"   # fell back

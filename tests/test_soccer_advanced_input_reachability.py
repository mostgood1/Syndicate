"""The soccer engine's advanced inputs must REACH the simulation.

`docs/ai_context/model_engine_standard.md` §1 and its "reachability test before
correctness tests" rule. The failure this guards is not a wrong number, it is a
silent one:

    xg_for = _first_float(attacking_metrics, ["xg_for_per_match", ...])
    score += ((xg_for or 1.35) - 1.35) * 0.22

If nothing populates the container, that term is exactly zero forever. The sim
runs, the tests pass, and the output is identical to a build where the feature
does not exist. `scripts/soccer_sim_input_checklist.py` measured **20 of 20**
read sites in that state on 2026-08-18.

These tests fail if the wiring is reverted, if a key is renamed on either side,
or if the per-side lookup regresses to a single shared value.
"""
from __future__ import annotations

import pytest

from syndicate.features.soccer.features.loaders import build_soccer_match_features
from syndicate.features.soccer.sim_engine.soccersim.contracts import (
    PossessionState,
    SoccerSimSimulationInput,
)
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import get_league_profile
from syndicate.features.soccer.sim_engine.soccersim.possession_priors import build_possession_priors

PROFILE = get_league_profile("eredivisie")

# Shaped exactly as `compute_team_ratings` emits (loaders.py), so a failure here
# means the wiring broke, not that the fixture drifted from production.
RATINGS = {
    "ajax": {"attack_rating": 0.31, "defense_rating": -0.12,
             "xg_for_per_match": 1.92, "xg_against_per_match": 0.94,
             "ppda": 9.6, "matches": 34.0},
    "psv": {"attack_rating": 0.28, "defense_rating": -0.09,
            "xg_for_per_match": 1.10, "xg_against_per_match": 1.55,
            "ppda": 14.8, "matches": 34.0},
}


def _state(owner: str) -> PossessionState:
    return PossessionState(possession_owner=owner, pitch_position=50,
                           phase="open_play", half=1, clock_remaining=2700)


def _priors(payload: dict, owner: str):
    return build_possession_priors(
        SoccerSimSimulationInput(
            home_team="Ajax", away_team="PSV", seed=7,
            home_attack_rating=0.31, home_defense_rating=-0.12,
            away_attack_rating=0.28, away_defense_rating=-0.09,
            feature_generation_payload=payload,
        ),
        possession_state=_state(owner), profile=PROFILE,
    )


def _payload() -> dict:
    """The REAL production payload, via the only constructor there is."""
    match = build_soccer_match_features(
        league="eredivisie", date="2026-08-19",
        home_team="Ajax", away_team="PSV", ratings=RATINGS,
    )
    return {
        "attacking_metrics": dict(match.team_metrics),
        "defensive_metrics": dict(match.defensive_metrics),
        "possession_metrics": dict(match.possession_metrics),
        "set_piece_metrics": dict(match.set_piece_metrics),
    }


def test_the_production_constructor_populates_xg_and_ppda():
    """The containers the engine reads must be non-empty coming out of
    `build_soccer_match_features` -- the ONLY production constructor. They were
    `{}` until 2026-08-18, while `compute_team_ratings` computed these very
    values and filed them into `adapter_metadata`, which the engine never opens.
    """
    match = build_soccer_match_features(
        league="eredivisie", date="2026-08-19",
        home_team="Ajax", away_team="PSV", ratings=RATINGS,
    )
    assert match.team_metrics.get("home_xg_for_per_match") == 1.92
    assert match.team_metrics.get("away_xg_for_per_match") == 1.10
    assert match.defensive_metrics.get("home_xg_against_per_match") == 0.94
    assert match.defensive_metrics.get("away_xg_against_per_match") == 1.55
    assert match.defensive_metrics.get("home_ppda") == 9.6


@pytest.mark.parametrize("owner", ["home", "away"])
def test_off_differs_from_on(owner: str):
    """REACHABILITY, and it is the test that must run before any correctness
    test: an empty payload and a fed one must not produce the same priors."""
    off = _priors({"attacking_metrics": {}, "defensive_metrics": {}}, owner)
    on = _priors(_payload(), owner)
    assert off.goal_conversion_probability != on.goal_conversion_probability, (
        f"feeding xG/PPDA changed nothing for owner={owner} -- the input is inert"
    )


def test_each_side_is_scored_with_its_own_numbers():
    """THE HAZARD THAT KEPT THIS UNWIRED, not a nice-to-have.

    `feature_generation_payload` is ONE dict per match while
    `build_possession_priors` runs per possession owner. Without the per-side
    lookup, both teams are scored with whichever value sits under the bare key --
    a wrong number where a neutral default used to be, which is worse than
    leaving it unfed.

    The fixture is deliberately lopsided (Ajax 1.92 xG for / 0.94 against, PSV
    1.10 / 1.55): if the sides were collapsed, these would be equal.
    """
    payload = _payload()
    home = _priors(payload, "home")
    away = _priors(payload, "away")
    assert home.goal_conversion_probability != away.goal_conversion_probability
    assert home.goal_conversion_probability > away.goal_conversion_probability, (
        "the stronger attack facing the weaker defence must convert more often"
    )


def test_a_missing_ppda_is_dropped_not_fed_as_zero():
    """`compute_team_ratings` emits `ppda: 0.0` when a league carries none, and
    `_pressing_index` maps LOW ppda to HIGH pressing -- so feeding the 0.0 would
    inject the most aggressive press possible exactly where the data is absent.
    """
    thin = {k: dict(v, ppda=0.0) for k, v in RATINGS.items()}
    match = build_soccer_match_features(
        league="eredivisie", date="2026-08-19",
        home_team="Ajax", away_team="PSV", ratings=thin,
    )
    assert "home_ppda" not in match.defensive_metrics
    assert "away_ppda" not in match.defensive_metrics
    # The real xG must survive the ppda filter.
    assert match.defensive_metrics.get("home_xg_against_per_match") == 0.94


def test_the_goals_as_xg_path_does_not_feed_goals_twice():
    """A DUPLICATED TERM PASSES EVERY REACHABILITY TEST THERE IS.

    `team_rows_from_match_history` uses goals as the xG stand-in
    (`xg_for = home_goals`). Emitting `goals_for` beside it puts the SAME number
    into `_attack_strength` twice -- `(xg_for - 1.35) * 0.22` and
    `(goals - 1.35) * 0.14` -- silently weighting goals at 0.36 instead of 0.22
    for every league on football-data, and the same on defence.

    Nothing else in this file catches it: the field IS consumed, IS populated,
    and DOES move output. It was caught by an A/B artifact build, where one
    eredivisie fixture's `total_mean` read 3.39 against 3.32 once corrected, and
    `win_probability.home` moved the WRONG WAY (0.49 vs 0.46) -- the duplicate
    was not merely inflating magnitude, it was flipping the converter's
    direction on that fixture.

    A real xG source whose xG differs from goals may legitimately emit both;
    this pins only the goals-as-xG path.
    """
    from syndicate.features.soccer.features.loaders import team_rows_from_match_history

    rows = team_rows_from_match_history([{
        "league": "eredivisie", "season": 2025, "date": "2025-09-01",
        "home_team": "Ajax", "away_team": "PSV",
        "home_goals": 3, "away_goals": 1,
        "home_shots": 15, "away_shots": 9,
        "home_corners": 7, "away_corners": 3,
    }])
    assert len(rows) == 2
    for row in rows:
        assert "goals_for" not in row, (
            "goals_for duplicates xg_for on the goals-as-xG path -- "
            "`_attack_strength` would weight goals at 0.36 instead of 0.22"
        )
        assert "goals_against" not in row, "goals_against duplicates xg_against"
    # The genuinely-new columns must still come through.
    home = rows[0]
    assert home["xg_for"] == 3 and home["xg_against"] == 1
    assert home["shots"] == 15 and home["shots_allowed"] == 9
    assert home["corners"] == 7
    assert home["clean_sheet"] == 0.0     # PSV scored
    assert home["points"] == 3.0          # Ajax won
    away = rows[1]
    assert away["clean_sheet"] == 0.0 and away["points"] == 0.0

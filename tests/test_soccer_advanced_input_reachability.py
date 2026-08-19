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
# xG IS DELIBERATELY NOT A REACHABILITY SUBJECT HERE ANY MORE.
# `_attack_strength` / `_defense_strength` no longer read `xg_for_per_match` /
# `xg_against_per_match`: those terms were dropped because the index is averaged
# with `fallback_attack = 0.5 + attack_rating`, and the ratings ARE xG
# (corr +0.984 attack, **-1.000 exactly** on defence). The keys are still
# populated by `build_soccer_match_features` and are currently UNREAD -- a "dead
# field" in the model-engine standard's terms, kept because a real xG source
# whose xG differs from goals would want them. Reachability is therefore
# asserted on the terms the engine ACTUALLY reads.
RATINGS = {
    "ajax": {"attack_rating": 0.31, "defense_rating": -0.12,
             "xg_for_per_match": 1.92, "xg_against_per_match": 0.94,
             "ppda": 9.6, "matches": 34.0,
             "shots_per_match": 16.4, "shots_allowed_per_match": 8.1,
             "clean_sheet_rate": 0.47, "corners_per_match": 7.2,
             "points_per_match": 2.31},
    "psv": {"attack_rating": 0.28, "defense_rating": -0.09,
            "xg_for_per_match": 1.10, "xg_against_per_match": 1.55,
            "ppda": 14.8, "matches": 34.0,
            "shots_per_match": 9.3, "shots_allowed_per_match": 15.7,
            "clean_sheet_rate": 0.12, "corners_per_match": 3.4,
            "points_per_match": 0.94},
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
    # The terms the engine READS today.
    assert match.team_metrics.get("home_shots_per_match") == 16.4
    assert match.team_metrics.get("away_shots_per_match") == 9.3
    assert match.team_metrics.get("home_points_per_match") == 2.31
    assert match.defensive_metrics.get("home_shots_allowed_per_match") == 8.1
    assert match.defensive_metrics.get("home_clean_sheet_rate") == 0.47
    assert match.defensive_metrics.get("home_ppda") == 9.6
    assert match.set_piece_metrics.get("home_corners_per_match") == 7.2
    # Populated but currently UNREAD -- kept, and pinned so a future re-wiring
    # of a real xG source finds them where it expects.
    assert match.team_metrics.get("home_xg_for_per_match") == 1.92
    assert match.defensive_metrics.get("home_xg_against_per_match") == 0.94


@pytest.mark.parametrize("owner", ["home", "away"])
def test_off_differs_from_on(owner: str):
    """REACHABILITY, and it is the test that must run before any correctness
    test: an empty payload and a fed one must not produce the same priors."""
    off = _priors({"attacking_metrics": {}, "defensive_metrics": {},
                   "possession_metrics": {}, "set_piece_metrics": {}}, owner)
    on = _priors(_payload(), owner)
    assert off.goal_conversion_probability != on.goal_conversion_probability, (
        f"feeding shots/corners/clean-sheets/form/PPDA changed nothing for "
        f"owner={owner} -- the input is inert"
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


def test_espn_match_stats_join_reaches_possession_and_set_piece():
    """`possession_share` and `set_piece_goal_share` were CONSUMED and
    UNPOPULATED since the checklist first ran -- `possession_metrics` was
    never even returned by `build_soccer_match_features` (an empty dict on
    every call, so `_possession_share`'s own 0.5 neutral default was the only
    value the engine had ever seen), and `set_piece_metrics` only ever carried
    `corners_per_match`.

    `espn_match_stats.aggregate_season_match_stats` sources both from a
    single ESPN endpoint already being called for shot events
    (`espn_shot_events.py`) -- `boxscore.teams[].statistics[].possessionPct`,
    a real per-match field, plus the same commentary feed's `from_corner`
    shot tagging aggregated to a goal share. Matched to football-data rows by
    FUZZY team-pair resolution (`match_team_name`, not exact canonical
    equality -- measured 99.8% row-level match rate on real eredivisie data,
    up from 44% under exact-canonical pair matching, which is why the fuzzy
    matcher exists here rather than a simpler equality check).
    """
    from syndicate.features.soccer.features.loaders import team_rows_from_match_history

    history_row = {
        "league": "eredivisie", "season": 2025, "date": "07/08/2026",
        "home_team": "Ajax", "away_team": "PSV",
        "home_goals": 2, "away_goals": 1,
        "home_shots": 12, "away_shots": 9,
        "home_corners": 5, "away_corners": 3,
    }
    espn_row = {
        "event_id": "1", "date": "2026-08-07T18:00Z",
        # Deliberately the FULLER ESPN-style names, not football-data's
        # short forms -- this is the exact mismatch shape that made the
        # exact-canonical join fail on 56% of real rows.
        "home_team": "Ajax Amsterdam", "away_team": "PSV Eindhoven",
        "home_possession_share": 0.612, "away_possession_share": 0.388,
        "home_goals": 2, "home_corner_goals": 1, "home_set_piece_goal_share": 0.5,
        "away_goals": 1, "away_corner_goals": 0, "away_set_piece_goal_share": 0.0,
    }

    without = team_rows_from_match_history([history_row])
    with_espn = team_rows_from_match_history([history_row], espn_stats=[espn_row])

    for row in without:
        assert "possession_share" not in row, "no espn_stats given -- must not fabricate a value"
        assert "set_piece_goal_share" not in row

    home, away = with_espn
    assert home["possession_share"] == 0.612
    assert away["possession_share"] == 0.388
    assert home["set_piece_goal_share"] == 0.5
    assert away["set_piece_goal_share"] == 0.0

    match = build_soccer_match_features(
        league="eredivisie", date="2026-08-19", home_team="Ajax", away_team="PSV",
        ratings={
            "ajax": {"attack_rating": 0.1, "defense_rating": -0.05, "possession_share": 0.60, "set_piece_goal_share": 0.4},
            "psv": {"attack_rating": 0.05, "defense_rating": 0.0, "possession_share": 0.40, "set_piece_goal_share": 0.1},
        },
    )
    assert match.possession_metrics.get("home_possession_share") == 0.60
    assert match.possession_metrics.get("away_possession_share") == 0.40
    assert match.set_piece_metrics.get("home_set_piece_goal_share") == 0.4
    assert match.set_piece_metrics.get("away_set_piece_goal_share") == 0.1

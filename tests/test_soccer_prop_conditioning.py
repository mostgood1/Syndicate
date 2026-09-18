"""`#673`: every soccer player-prop family is priced on ONE stated question.

A book voids a player prop when the player does not appear, so what it settles
is P(over | he appears). Until 2026-09-18 the sim priced shots and shots on
target on a start/sub mixture conditional on appearing and ASSISTS on a Poisson
over the unconditional mean, and the board priced both side by side with nothing
on the row saying which. H33 (pre-registered, held out, 9,810 appeared rows) put
assists on the mixture: log loss 0.2366 -> 0.2309, 9 of 10 leagues.

Every test here fails on the pre-change code.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from syndicate.features.shared import soccer_projections as sp
from syndicate.features.shared.prop_evidence import soccer as ask_soccer
from syndicate.features.soccer.sim_engine.soccersim import player_props as PP

DIST = SimpleNamespace(
    mean_home_goals=1.6, mean_away_goals=1.1,
    mean_home_shots=14.0, mean_away_shots=10.0,
    mean_home_shots_on_target=5.0, mean_away_shots_on_target=3.5,
)

# A regular starter and a bench player, as `build_usage_profiles` sees them.
ROWS = [
    {"player_id": "s", "player_name": "Starter Nine", "position": "Forward", "expected_minutes_share": 0.9,
     "shots_per90": 3.0, "xg_per90": 0.45, "xa_per90": 0.25, "appearances": 10, "starts": 10},
    {"player_id": "b", "player_name": "Bench Seven", "position": "Midfielder", "expected_minutes_share": 0.15,
     "shots_per90": 2.0, "xg_per90": 0.20, "xa_per90": 0.30, "appearances": 8, "starts": 1},
    {"player_id": "d", "player_name": "Back Four", "position": "Defender", "expected_minutes_share": 0.95,
     "shots_per90": 0.6, "xg_per90": 0.05, "xa_per90": 0.08, "appearances": 10, "starts": 10},
]


def _projections():
    profiles = PP.build_usage_profiles(ROWS, side="home", team="Home FC")
    return profiles, [PP.project_player_props(DIST, p) for p in profiles]


def _poisson_ge1(mean):
    return round(1.0 - math.exp(-mean), 4)


# --- the engine -------------------------------------------------------------


def test_the_assists_ladder_is_the_start_sub_mixture_not_poisson_on_the_unconditional_mean():
    profiles, projections = _projections()
    bench = projections[1]
    assert profiles[1].on_pitch_assist_share is not None and profiles[1].start_probability < 0.5
    # Pre-change: exactly Poisson over the unconditional mean.
    assert bench.assists_over_probabilities["0.5"] != _poisson_ge1(bench.expected_assists)
    # The mixture, recomputed from the profile's own role inputs.
    full = DIST.mean_home_goals * 0.72 * profiles[1].on_pitch_assist_share
    p_start = profiles[1].start_probability
    expected = p_start * (1 - math.exp(-full * 83.1 / 90)) + (1 - p_start) * (1 - math.exp(-1.8 * full * 15.6 / 90))
    assert bench.assists_over_probabilities["0.5"] == round(expected, 4)
    # And its mean is the mixture's mean, not the minutes-share division.
    assert bench.expected_assists_if_playing == round(
        p_start * full * 83.1 / 90 + (1 - p_start) * 1.8 * full * 15.6 / 90, 4)
    # Conditional on appearing reads HIGHER than unconditional for a bench player.
    assert bench.assists_over_probabilities["0.5"] > _poisson_ge1(bench.expected_assists)


def test_on_pitch_assist_shares_allocate_the_whole_side():
    profiles, _ = _projections()
    minutes = [0.9, 0.15, 0.95]   # no games/minutes columns -> the minutes share itself
    rates = [0.25, 0.30, 0.08]
    total = sum(r * m for r, m in zip(rates, minutes))
    for profile, rate in zip(profiles, rates):
        assert abs(profile.on_pitch_assist_share - rate / total) < 1e-12


def test_every_probability_field_is_stamped_with_the_question_it_answers():
    _, projections = _projections()
    stamp = projections[0].to_dict()["ladder_conditioning"]
    assert stamp == {
        "shots_over_probabilities": "appearing",
        "shots_on_target_over_probabilities": "appearing",
        "assists_over_probabilities": "appearing",
        "anytime_scorer_probability": "unconditional",
        "anytime_scorer_probability_if_playing": "appearing",
        "two_or_more_scorer_probability": "unconditional",
        "goal_or_assist_probability": "unconditional",
    }


def test_a_profile_without_role_inputs_keeps_the_unconditional_ladder_and_says_so():
    bare = PP.PlayerUsageProfile(player_id="x", player_name="No Roles", side="home",
                                 expected_minutes_share=0.5, shot_share=0.2, goal_share=0.2, assist_share=0.2)
    projection = PP.project_player_props(DIST, bare)
    assert projection.assists_over_probabilities["0.5"] == _poisson_ge1(projection.expected_assists)
    assert projection.ladder_conditioning["assists_over_probabilities"] == "unconditional"
    assert projection.ladder_conditioning["shots_over_probabilities"] == "unconditional"


# --- the board's reading of a ladder ----------------------------------------


def test_the_producer_stamp_is_read_first():
    entry = {"assists_over_probabilities": {"0.5": _poisson_ge1(0.2)}, "expected_assists": 0.2,
             "ladder_conditioning": {"assists_over_probabilities": "appearing"}}
    assert sp.ladder_conditioning(entry, "assists_over_probabilities") == "appearing"


def test_without_a_stamp_the_exact_poisson_test_decides():
    legacy = {"assists_over_probabilities": {"0.5": _poisson_ge1(0.2), "1.5": 0.0175}, "expected_assists": 0.2}
    assert sp.ladder_conditioning(legacy, "assists_over_probabilities") == "unconditional"
    _, projections = _projections()
    new = projections[1].to_dict()
    new.pop("ladder_conditioning")          # an allowlist that drops the stamp
    assert sp.ladder_conditioning(new, "assists_over_probabilities") == "appearing"
    zero = {"shots_over_probabilities": {"0.5": 0.0, "1.5": 0.0}, "expected_shots": 0.0}
    assert sp.ladder_conditioning(zero, "shots_over_probabilities") == "zero"


def test_a_mixture_that_lands_on_the_poisson_value_is_told_apart_by_its_mean():
    """255 of 16,377 new assists ladders sat within 2e-4 of the Poisson value (H33
    replay). The unconditional path ALSO published `_if_playing` as mean / max(m,
    0.25); a mixture's mean does not, and that second fingerprint decides."""
    legacy = {"assists_over_probabilities": {"0.5": _poisson_ge1(0.2)}, "expected_assists": 0.2,
              "expected_minutes_share": 0.8, "expected_assists_if_playing": 0.25}      # 0.2 / 0.8
    assert sp.ladder_conditioning(legacy, "assists_over_probabilities") == "unconditional"
    coincident = dict(legacy, expected_assists_if_playing=0.2105)                        # a mixture mean
    assert sp.ladder_conditioning(coincident, "assists_over_probabilities") == "appearing"
    floored = {"assists_over_probabilities": {"0.5": _poisson_ge1(0.02)}, "expected_assists": 0.02,
               "expected_minutes_share": 0.1, "expected_assists_if_playing": 0.08}      # 0.02 / 0.25
    assert sp.ladder_conditioning(floored, "assists_over_probabilities") == "unconditional"


# --- the board --------------------------------------------------------------


def _index(entry):
    idx = sp.SoccerProjectionIndex()
    idx.by_teams[("marseille", "strasbourg")] = {"match_id": "m1", "league": "ligue_1"}
    idx.players_by_match["m1"] = {"amine gouiri": entry}
    idx.matches = 1
    return idx


def _row(market, line):
    return {"sport": "soccer", "kind": "prop", "market": market, "line": line, "side": "over",
            "player_name": "Amine Gouiri", "home_team": "Marseille", "away_team": "Strasbourg"}


def test_an_unconditional_assists_ladder_is_not_priced_beside_conditional_shots():
    legacy = {"expected_assists": 0.2, "assists_over_probabilities": {"0.5": _poisson_ge1(0.2)}}
    row = _row("player_assists", 0.5)
    coverage = sp.attach_soccer_projections([row], _index(legacy))
    assert row.get("projection") is None
    assert coverage["conditioning_mismatch_by_market"] == {"player_assists": 1}
    assert coverage["unsupported_market_rows"] == 0, "the line WAS priced; the question was not"


def test_a_conditional_assists_ladder_is_priced_and_states_it():
    _, projections = _projections()
    entry = projections[1].to_dict()
    row = _row("player_assists", 0.5)
    coverage = sp.attach_soccer_projections([row], _index(entry))
    assert row["projection"]["model_prob_over"] == entry["assists_over_probabilities"]["0.5"]
    assert row["projection"]["conditioning"] == "appearing"
    assert coverage["conditioning_by_market"] == {"player_assists": {"appearing": 1}}
    assert coverage["conditioning_mismatch_by_market"] == {}


def test_an_unconditional_shots_ladder_falls_to_the_conditional_mean():
    legacy = {"expected_shots": 1.2, "expected_shots_if_playing": 1.6,
              "shots_over_probabilities": {"0.5": _poisson_ge1(1.2), "1.5": 0.3374}}
    row = _row("player_shots", 0.5)
    coverage = sp.attach_soccer_projections([row], _index(legacy))
    assert row["projection"]["basis"] == "expected_shots_if_playing"
    assert row["projection"]["model_prob_over"] is None
    assert row["projection"]["conditioning"] == "appearing"
    assert coverage["conditioning_mismatch_by_market"] == {"player_shots": 1}


def test_the_scorer_family_states_it_is_unconditional_by_user_decision():
    entry = {"anytime_scorer_probability": 0.31, "anytime_scorer_probability_if_playing": 0.36,
             "expected_goals": 0.37}
    row = _row("player_goal_scorer_anytime", None)
    coverage = sp.attach_soccer_projections([row], _index(entry))
    assert row["projection"]["model_prob_over"] == 0.31
    assert row["projection"]["conditioning"] == "unconditional"
    assert coverage["conditioning_by_market"] == {"player_goal_scorer_anytime": {"unconditional": 1}}


# --- Ask reads the ladder the way the board does ------------------------------


def test_ask_labels_a_new_assists_ladder_if_playing_and_flags_a_legacy_one():
    spec = ask_soccer.MARKETS["player_assists"]
    _, projections = _projections()
    assert ask_soccer.ladder_basis(projections[1].to_dict(), spec) == "if_playing"
    legacy = {"expected_assists": 0.2, "assists_over_probabilities": {"0.5": _poisson_ge1(0.2)}}
    assert ask_soccer.ladder_basis(legacy, spec) == "unconditional"
    assert ask_soccer.board_prices_ladder("player_assists", "if_playing") is True
    assert ask_soccer.board_prices_ladder("player_assists", "unconditional") is False

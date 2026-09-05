"""The NCAAF live re-sim: what it prices, and every way it refuses to.

The refusal tests are the important ones. `#414`'s defect was not a wrong
probability -- it was a RIGHT-LOOKING one, the pregame value, sitting on rows the
live model could not reach, on a board that sorts by edge.
"""
from __future__ import annotations

import pytest

from syndicate.features.ncaaf import live_resim as lr


# --------------------------------------------------------------------------
# clock and field position: the two transforms that can be silently backwards
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("13:20", 800),
    ("0:27", 27),
    ("15:00", 900),
    ("0:00", 0),          # a quarter's end is a REAL state, not an absence
])
def test_clock_parses(text, expected):
    assert lr.clock_to_seconds(text) == expected


@pytest.mark.parametrize("text", ["", None, "Halftime", "13:60", "abc", "1:2:3"])
def test_unparseable_clock_is_none_not_zero(text):
    """None and 0 are different answers and only one of them is safe to resume."""
    assert lr.clock_to_seconds(text) is None


def test_field_position_transform_matches_the_measured_espn_frame():
    """ESPN measures from the HOME goal line; smartsim2 from the possessor's own.

    The three cases are read off the real 2026-09-05 slate, including the one
    that makes the inversion visible: Boise State, the AWAY team, at its own 3
    with ESPN reporting `yardLine: 97`.
    """
    assert lr.field_position_for_possessor(39, possessor_is_home=True) == 39     # "TEX 39"
    assert lr.field_position_for_possessor(24, possessor_is_home=True) == 24     # "PSU 24"
    assert lr.field_position_for_possessor(75, possessor_is_home=False) == 25    # "BAY 25"
    assert lr.field_position_for_possessor(97, possessor_is_home=False) == 3     # "BOIS 3"


def test_field_position_rejects_nonsense():
    assert lr.field_position_for_possessor(None, possessor_is_home=True) is None
    assert lr.field_position_for_possessor("x", possessor_is_home=True) is None
    assert lr.field_position_for_possessor(140, possessor_is_home=True) is None


# --------------------------------------------------------------------------
# state resolution and its refusals
# --------------------------------------------------------------------------

def _row(**kw):
    base = {"in_progress": True, "final": False, "period": 2, "clock": "13:01",
            "home_score": 3, "away_score": 0}
    base.update(kw)
    return base


def test_a_live_row_resolves():
    state = lr.live_state_from_espn_event(_row(), away_team="Baylor", home_team="Auburn")
    assert isinstance(state, lr.NcaafLiveGameState)
    assert (state.period, state.clock_seconds) == (2, 781)
    assert state.home_margin == 3


@pytest.mark.parametrize("row,reason", [
    (_row(final=True), "game_final"),
    (_row(in_progress=False), "game_not_in_progress"),
    (_row(period=0), "no_period"),
    (_row(period=None), "no_period"),
    (_row(period=5), "overtime_not_modelled"),
    (_row(clock="Halftime"), "no_clock"),
    (_row(home_score=None), "no_score"),
])
def test_every_unresumable_state_refuses_by_name(row, reason):
    out = lr.live_state_from_espn_event(row, away_team="A", home_team="B")
    assert isinstance(out, lr.NcaafResimRefusal)
    assert out.reason == reason


def test_espn_sends_minus_one_for_down_and_distance_between_plays():
    """Two of fourteen live games did on 2026-09-05; -1 must not clamp to 1st-and-1."""
    state = lr.live_state_from_espn_event(
        _row(situation={"down": -1, "distance": -1, "yardLine": 65}),
        away_team="Towson", home_team="Navy",
    )
    assert (state.down, state.distance) == (1, 10)


def test_possession_is_left_unknown_rather_than_guessed():
    state = lr.live_state_from_espn_event(
        _row(situation={"down": 1, "distance": 10, "yardLine": 25}),
        away_team="A", home_team="B",
    )
    assert state.possession_owner is None
    assert state.field_position == 25


def test_possession_side_is_resolved_against_the_competitor_ids():
    competition = {"situation": {"possession": "68", "down": 4, "distance": 5, "yardLine": 97}}
    side, situation = lr.possession_side_from_espn(competition, home_id="2483", away_id="68")
    assert side == "away"
    assert situation["yardLine"] == 97
    side, _ = lr.possession_side_from_espn(competition, home_id="68", away_id="2483")
    assert side == "home"
    # An id belonging to neither side is unknown, not a coin flip.
    side, _ = lr.possession_side_from_espn(competition, home_id="1", away_id="2")
    assert side is None


# --------------------------------------------------------------------------
# the re-sim itself
# --------------------------------------------------------------------------

RATINGS = {"oregon": (1.2, 0.6), "boise state": (0.1, 0.1)}


def _resim(state, sims=40):
    return lr.resim_live_game(
        state, home_offense=1.2, home_defense=0.6,
        away_offense=0.1, away_defense=0.1, sims=sims,
    )


def test_a_decided_game_prices_at_the_boundary_not_near_it():
    """`#414`: an already-decided prop fell out as exactly 1.0, and so must this."""
    state = lr.NcaafLiveGameState(away_team="Boise State", home_team="Oregon",
                                  period=4, clock_seconds=15,
                                  home_score=42, away_score=7,
                                  possession_owner="home")
    assert _resim(state)["home_win_prob"] == 1.0
    flipped = lr.NcaafLiveGameState(away_team="Boise State", home_team="Oregon",
                                    period=4, clock_seconds=15,
                                    home_score=7, away_score=42,
                                    possession_owner="home")
    assert _resim(flipped)["home_win_prob"] == 0.0


def test_the_probability_moves_with_the_score_which_is_the_entire_point():
    kw = dict(away_team="Boise State", home_team="Oregon", period=2,
              clock_seconds=900, possession_owner="home")
    level = _resim(lr.NcaafLiveGameState(home_score=7, away_score=7, **kw))["home_win_prob"]
    behind = _resim(lr.NcaafLiveGameState(home_score=0, away_score=21, **kw))["home_win_prob"]
    ahead = _resim(lr.NcaafLiveGameState(home_score=21, away_score=0, **kw))["home_win_prob"]
    assert behind < level < ahead


def test_unknown_possession_is_marginalised_over_both_sides():
    state = lr.NcaafLiveGameState(away_team="Boise State", home_team="Oregon",
                                  period=3, clock_seconds=600,
                                  home_score=14, away_score=14)
    result = _resim(state)
    assert result["possession_unknown"] is True
    # Half the seeds each way, so the count is the requested total, not half.
    assert result["sims_run"] == 40


def test_sims_run_is_the_number_actually_run():
    """`prob_std_err` divides by it. A wrong `n` is a wrong error bar."""
    state = lr.NcaafLiveGameState(away_team="B", home_team="A", period=4,
                                  clock_seconds=30, home_score=10, away_score=3,
                                  possession_owner="home")
    assert _resim(state, sims=25)["sims_run"] == 25


# --------------------------------------------------------------------------
# the published lane: the interlock
# --------------------------------------------------------------------------

def test_a_refusal_publishes_a_lane_that_carries_no_probability_at_all():
    """The interlock. Not the pregame value, not zero, not a null.

    A downstream `prob or fallback` cannot resurrect a number that is not in the
    payload, which is why the key is ABSENT rather than None.
    """
    lanes = lr.build_game_lens(None, lr.NcaafResimRefusal("no_pregame_ratings", "d"))
    assert len(lanes) == 1
    lane = lanes[0]
    assert "modelHomeWinProb" not in lane
    assert "simsRun" not in lane
    assert lane["source"] == lr.PREGAME_LENS_SOURCE
    assert lane["liveResimRefusal"] == "no_pregame_ratings"


def test_the_refused_stamp_is_rejected_by_the_join_and_the_priced_one_is_accepted():
    """Read through the JOIN's own function, not a copy of its rule."""
    from syndicate.features.shared.live_gameline_join import (
        lens_sources_for_sport,
        live_gameline_from_lens,
    )

    sources = lens_sources_for_sport("ncaaf")
    refused = lr.build_game_lens(None, lr.NcaafResimRefusal("no_live_state", ""))
    assert live_gameline_from_lens(refused, sources=sources) is None

    state = lr.NcaafLiveGameState(away_team="B", home_team="A", period=4,
                                  clock_seconds=30, home_score=24, away_score=10,
                                  possession_owner="home")
    priced = lr.build_game_lens(state, _resim(state))
    projection = live_gameline_from_lens(priced, sources=sources)
    assert projection is not None
    assert projection["home_win_prob"] == 1.0
    assert projection["sims_run"] == 40


def test_the_lane_publishes_no_distribution_so_totals_stay_unpriceable():
    """Deliberate. NCAAF live totals have never been graded (`#499`'s bar)."""
    state = lr.NcaafLiveGameState(away_team="B", home_team="A", period=3,
                                  clock_seconds=400, home_score=17, away_score=14,
                                  possession_owner="home")
    lane = lr.build_game_lens(state, _resim(state))[0]
    assert "marginDist" not in lane["projection"]
    assert "totalRunsDist" not in lane["projection"]


# --------------------------------------------------------------------------
# the snapshot
# --------------------------------------------------------------------------

def _games():
    return [
        {"away_team": "Boise State", "home_team": "Oregon", "live_key": "68@2483"},
        {"away_team": "Marshall", "home_team": "Penn State", "live_key": "276@213"},
        {"away_team": "Nowhere State", "home_team": "Elsewhere", "live_key": "1@2"},
    ]


def _index():
    return {
        "68@2483": _row(period=2, clock="11:17", home_score=7, away_score=7,
                        situation={"down": 4, "distance": 5, "yardLine": 97}),
        "276@213": _row(period=2, clock="13:28", home_score=17, away_score=0,
                        situation={"down": 2, "distance": 5, "yardLine": 24}),
        "1@2": _row(period=2, clock="10:00", home_score=3, away_score=3),
    }


def test_snapshot_shape_and_coverage_counters():
    ratings = {"oregon": (1.2, 0.6), "boise state": (0.1, 0.1),
               "penn state": (1.5, 0.8), "marshall": (-0.4, -0.2)}
    snapshot = lr.build_live_lens_snapshot(
        "2026-09-05", games=_games(), live_index=_index(), ratings=ratings, sims=20,
    )
    ok, why = lr.validate_live_lens_snapshot(snapshot)
    assert ok, why
    coverage = snapshot["coverage"]
    assert coverage["games"] == 3
    assert coverage["live_resimmed"] == 2
    # The third game is rated by NEITHER side, and that is a named refusal, not
    # a neutral 0.0 rating dressed up as a projection.
    assert coverage["refusals_by_reason"] == {"no_pregame_ratings": 1}


def test_a_game_with_no_espn_row_refuses_by_name():
    snapshot = lr.build_live_lens_snapshot(
        "2026-09-05",
        games=[{"away_team": "Boise State", "home_team": "Oregon", "live_key": "missing"}],
        live_index={},
        ratings={"oregon": (1.2, 0.6), "boise state": (0.1, 0.1)},
        sims=10,
    )
    assert snapshot["coverage"]["refusals_by_reason"] == {"no_live_state": 1}


def test_the_budget_refuses_by_name_rather_than_overrunning_the_tick():
    ratings = {"oregon": (1.2, 0.6), "boise state": (0.1, 0.1),
               "penn state": (1.5, 0.8), "marshall": (-0.4, -0.2)}
    snapshot = lr.build_live_lens_snapshot(
        "2026-09-05", games=_games()[:2], live_index=_index(), ratings=ratings,
        sims=20, budget_seconds=0.0,
    )
    reasons = snapshot["coverage"]["refusals_by_reason"]
    assert reasons.get("tick_budget_exhausted") == 2
    assert snapshot["coverage"]["live_resimmed"] == 0


def test_the_snapshot_refuses_to_run_in_a_request_path(monkeypatch):
    """The load-bearing rule: simulation happens on a worker, never in a route.

    Driven through a REAL Flask request context and a real hosted marker, so it
    exercises `refuse_if_compute_in_request_path`'s own two predicates rather
    than a stand-in for them. Off the request path it is a no-op, which is why
    every other test here calls the builder directly.
    """
    from flask import Flask

    from syndicate.features.shared.request_path_guard import ComputeInRequestPathError

    monkeypatch.setenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", "true")
    app = Flask(__name__)
    with app.test_request_context("/ncaaf/cards"):
        with pytest.raises(ComputeInRequestPathError):
            lr.build_live_lens_snapshot("2026-09-05", games=[], live_index={}, ratings={})


def test_validate_rejects_an_empty_or_malformed_snapshot():
    assert lr.validate_live_lens_snapshot(None)[0] is False
    assert lr.validate_live_lens_snapshot({})[0] is False
    assert lr.validate_live_lens_snapshot({"games": [{"home_name": ""}]})[0] is False

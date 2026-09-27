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


def test_the_lane_publishes_BOTH_graded_distributions():
    """`#499`'s bar was met by TOTALS on 2026-09-26 and by MARGINS on 09-27.

    Each key rests on its own cutoff-replay grade of THIS function at
    production's 120 sims and production's SP+ ratings:

        totals   worst bucket 0.1463 -> 0.0492   (561 rows / 187 games)
        margins  worst bucket 0.0954 -> 0.0448   (570 rows / 190 games)

    Both histograms are the CALIBRATED ones, so the board prices what was
    graded. A real histogram, not an empty dict -- `{}` would satisfy a key
    check while `price_distribution_market` withheld every row exactly as
    before.
    """
    state = lr.NcaafLiveGameState(away_team="B", home_team="A", period=3,
                                  clock_seconds=400, home_score=17, away_score=14,
                                  possession_owner="home")
    lane = lr.build_game_lens(state, _resim(state))[0]
    for key in ("totalRunsDist", "marginDist"):
        dist = lane["projection"][key]
        assert dist, f"{key} is empty -- pricing stays shut"
        assert sum(dist.values()) == lane["simsRun"]


def test_the_margin_calibration_is_SIGNED_and_never_clamps_away_wins():
    """The totals calibrator clamps at zero. This one MUST NOT.

    A total cannot be negative, so clamping it is right. A home margin is
    signed, and clamping would delete every away-win draw -- turning a game the
    home side is losing into a guaranteed cover, at exactly the lines a live
    spread is quoted on. This is the one place the two calibrators deliberately
    differ, so it gets a test rather than a comment.
    """
    corrected_mean, corrected = lr.calibrate_margin_distribution([-21, -14, -7, 0, 7])
    assert corrected, "no histogram produced"
    values = [float(k) for k in corrected]
    assert min(values) < 0, "away-win draws were clamped away"
    assert sum(corrected.values()) == 5, "draws were lost"
    assert corrected_mean < 0, "a losing position became a winning one"


def test_the_margin_correction_is_IDENTITY_but_the_MECHANISM_still_works(monkeypatch):
    """Zeroed 2026-09-27, and the transform is deliberately kept anyway.

    The refit measured a Saturday bias of -0.387 with a bootstrap CI over games
    of [-1.644, +0.896] and a worst-bucket improvement of 0.0014. Fitting a
    constant to a quantity that cannot be shown non-zero is the same error as
    the stale-ratings one a commit earlier, so the default is identity.

    BOTH HALVES ARE ASSERTED, and the second is the one that matters. A default
    of 0.0 makes `calibrate_margin_distribution` a pass-through, which means a
    future bug that silently broke the transform would be invisible -- the
    identity test would still pass. So the mechanism is exercised through the
    env override the next refit will use, proving off != on rather than merely
    that off is off.
    """
    draws = [-7, -3, 0, 3, 7, 10, 14]
    raw_mean = sum(draws) / len(draws)

    # DEFAULT: identity, in the mean and in the histogram.
    mean_id, hist_id = lr.calibrate_margin_distribution(draws)
    assert mean_id == pytest.approx(raw_mean, abs=1e-9)
    counted = {}
    for d in draws:
        counted[str(d)] = counted.get(str(d), 0) + 1
    assert hist_id == counted

    # MECHANISM: supply a constant and it must actually move, toward home.
    monkeypatch.setenv("NCAAF_LIVE_MARGIN_BIAS_POINTS", "3.0")
    mean_on, hist_on = lr.calibrate_margin_distribution(draws)
    assert mean_on == pytest.approx(raw_mean + 3.0, abs=1e-9), "the transform is broken"
    assert hist_on != counted
    # And still signed -- no clamp reintroduced by the override path.
    assert min(float(k) for k in hist_on) < 0


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


def test_REACHABILITY_a_published_total_actually_prices_through_the_real_join():
    """off != on, through the shipped functions, with nothing stubbed.

    Presence is not reachability. The producer carrying `totalRunsDist` is
    worth nothing unless `live_gameline_from_lens` forwards it and
    `price_distribution_market` answers a line with it -- exactly the hop that
    left NHL's predictions publishing to nobody. So this drives the real chain
    and compares the SAME lane with the key removed:

        with the distribution      -> a model probability at the line
        without it (the old lens)  -> REASON_NO_LIVE_DISTRIBUTION

    A test that only asserted the ON side would pass just as happily if the
    join had always been able to price totals, which would mean this lane
    shipped nothing.
    """
    import copy

    from syndicate.features.shared.live_gameline_join import (
        REASON_NO_LIVE_DISTRIBUTION,
        lens_sources_for_sport,
        live_gameline_from_lens,
        price_distribution_market,
    )

    sources = lens_sources_for_sport("ncaaf")
    state = lr.NcaafLiveGameState(away_team="B", home_team="A", period=3,
                                  clock_seconds=400, home_score=17, away_score=14,
                                  possession_owner="home")
    lanes = lr.build_game_lens(state, _resim(state, sims=120))

    hit = live_gameline_from_lens(lanes, sources=sources)
    assert hit is not None
    assert hit["total_runs_dist"], "the join dropped the distribution the producer published"

    # The line is taken FROM the sim's own centre, so the test is about
    # reachability and not about whether this fixture happens to sit on a
    # priced part of the curve.
    line = float(lanes[0]["projection"]["total"])
    on = price_distribution_market(
        dist=hit["total_runs_dist"], line=line, side="over", market="totals",
        market_prob=0.5, sims=hit["sims_run"], sport="ncaaf",
    )
    assert on["model_prob"] is not None
    assert on["withheld_reason"] != REASON_NO_LIVE_DISTRIBUTION

    # THE OFF SIDE: the identical lane as it looked before this change.
    old = copy.deepcopy(lanes)
    old[0]["projection"].pop("totalRunsDist")
    old_hit = live_gameline_from_lens(old, sources=sources)
    off = price_distribution_market(
        dist=old_hit["total_runs_dist"], line=line, side="over", market="totals",
        market_prob=0.5, sims=old_hit["sims_run"], sport="ncaaf",
    )
    assert off["model_prob"] is None
    assert off["withheld_reason"] == REASON_NO_LIVE_DISTRIBUTION


def test_REACHABILITY_spreads_now_price_through_the_real_join():
    """off != on for SPREADS, through the shipped functions, nothing stubbed.

    This test previously asserted the opposite -- that a spreads row refused
    with `no_live_distribution` because the margin estimator had never been
    graded. It has been graded now (`--market margin`, 570 rows / 190 games,
    worst bucket 0.0448 corrected), so the assertion flips in the same commit
    as the evidence, which is the only honest way for a gate test to change.
    """
    import copy

    from syndicate.features.shared.live_gameline_join import (
        REASON_NO_LIVE_DISTRIBUTION,
        lens_sources_for_sport,
        live_gameline_from_lens,
        price_distribution_market,
    )

    sources = lens_sources_for_sport("ncaaf")
    state = lr.NcaafLiveGameState(away_team="B", home_team="A", period=3,
                                  clock_seconds=400, home_score=17, away_score=14,
                                  possession_owner="home")
    lanes = lr.build_game_lens(state, _resim(state, sims=120))
    hit = live_gameline_from_lens(lanes, sources=sources)
    assert hit["margin_dist"], "the join dropped the margin distribution"

    line = float(lanes[0]["projection"]["homeMargin"])
    on = price_distribution_market(
        dist=hit["margin_dist"], line=line, side="home", market="spreads",
        market_prob=0.5, sims=hit["sims_run"], sport="ncaaf",
    )
    assert on["model_prob"] is not None
    assert on["withheld_reason"] != REASON_NO_LIVE_DISTRIBUTION

    old = copy.deepcopy(lanes)
    old[0]["projection"].pop("marginDist")
    old_hit = live_gameline_from_lens(old, sources=sources)
    off = price_distribution_market(
        dist=old_hit["margin_dist"], line=line, side="home", market="spreads",
        market_prob=0.5, sims=old_hit["sims_run"], sport="ncaaf",
    )
    assert off["model_prob"] is None
    assert off["withheld_reason"] == REASON_NO_LIVE_DISTRIBUTION


def test_the_moneyline_and_the_spread_stay_COHERENT_after_calibration():
    """A known, bounded incoherence -- recorded rather than discovered later.

    `home_win_prob` is counted from the RAW margins; `marginDist` is corrected.
    So the moneyline and a spread priced at the pivot no longer imply exactly
    the same win probability. Measured on three live states the gap is
    0.12-1.87pp, far inside the ~9.13pp publish bar at 120 sims, so it cannot
    produce two published edges that contradict each other. This test is the
    tripwire: if a future change to either estimator widens the gap past the
    bar, the board would start doing that, and this fails first.
    """
    from syndicate.features.shared.prop_projections import _dist_prob_over

    for home_score, away_score, period in ((17, 14, 3), (7, 7, 2), (3, 10, 3)):
        state = lr.NcaafLiveGameState(away_team="B", home_team="A", period=period,
                                      clock_seconds=400, home_score=home_score,
                                      away_score=away_score, possession_owner="home")
        result = _resim(state, sims=400)
        pivot = _dist_prob_over(result["margin_dist"], 0.5)
        gap_pp = abs(result["home_win_prob"] - pivot) * 100.0
        assert gap_pp < 5.0, (
            f"moneyline vs spread disagree by {gap_pp:.2f}pp at {home_score}-{away_score} "
            f"Q{period} -- approaching the publish bar, so the board could print "
            f"contradictory edges on the same team"
        )

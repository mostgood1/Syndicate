"""The NFL live re-sim must be OFF by default and must refuse a broken rating.

Every test here is written so that DISABLING the thing it tests turns it red.
A suite that stays green with its subject removed is measuring nothing, which is
the failure `sim_output_checklist.py` was written to catch one layer up.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.live_resim import (  # noqa: E402
    RATING_SEPARATION_FLOOR,
    NflLiveGameState,
    NflResimRefusal,
    build_game_lens,
    nfl_live_resim_enabled,
    ratings_are_degenerate,
    resim_live_game,
    summarise,
)

# A mid-third-quarter state: decided enough to be interesting, not decided.
STATE = NflLiveGameState(
    away_team="Dallas Cowboys", home_team="Philadelphia Eagles",
    period=3, clock_seconds=600, home_score=17, away_score=13,
    down=2, distance=7, field_position=41, possession_owner="home",
)

# Ratings that separate the two sides comfortably.
SEPARATED = dict(home_offense=27.0, home_defense=19.0,
                 away_offense=20.0, away_defense=24.0)


def test_absent_flag_reads_as_OFF():
    """CLAUDE.md: absent is not automatically off, so it is asserted. This
    module publishes live money edges on an engine that loses to the close, so
    the default must be off explicitly rather than by convention."""
    assert nfl_live_resim_enabled({}) is False
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": ""}) is False
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": "0"}) is False
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": "false"}) is False


def test_the_flag_can_actually_be_turned_ON():
    """off != on. Without this the test above passes on a function that returns
    False unconditionally, which is a real way to ship a dead feature."""
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": "1"}) is True
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": "on"}) is True


def test_disabled_refuses_and_NAMES_the_reason():
    out = resim_live_game(STATE, **SEPARATED, env={})
    assert isinstance(out, NflResimRefusal)
    assert out.reason == "nfl_live_resim_disabled"
    # The refusal has to carry WHY, not just THAT -- a bare reason string sends
    # the next reader to the code to find out whether it is a bug.
    assert "skill gate" in out.detail or "t=+3.34" in out.detail


def test_identical_net_ratings_are_DEGENERATE():
    """The measured failure: `nfl-rating-units` found across-game margin stdev
    2.16 against NCAAF's 15.37, i.e. the engine reporting its prior. Equal net
    strength on both sides is that case in its purest form."""
    assert ratings_are_degenerate(home_offense=25.0, home_defense=22.0,
                                  away_offense=25.0, away_defense=22.0) is True


def test_separated_ratings_are_NOT_degenerate():
    """off != on for the guard itself. A check that fires on everything is the
    same as no check -- it just moves the failure to 'nothing ever publishes'."""
    assert ratings_are_degenerate(**SEPARATED) is False


def test_degeneracy_is_measured_on_the_SIDES_not_the_four_numbers():
    """Two teams can have different individual ratings and identical NET
    strength. The simulation acts on home-offense vs away-defense and vice
    versa, so that pair is indistinguishable and must refuse."""
    assert ratings_are_degenerate(home_offense=30.0, home_defense=10.0,
                                  away_offense=20.0, away_defense=20.0) is True


def test_the_floor_is_a_floor_not_a_quality_bar():
    """Just past the floor must PASS. This pins the intent: it is a guard
    against publishing noise, not a judgement about whether the rating is good
    -- that belongs to `nfl-rating-units`. If someone later raises this to a
    quality threshold, this test tells them they changed its meaning."""
    just_over = RATING_SEPARATION_FLOOR * 1.05
    assert ratings_are_degenerate(home_offense=20.0 + just_over, home_defense=20.0,
                                  away_offense=20.0, away_defense=20.0) is False


def test_enabled_but_degenerate_STILL_refuses():
    """The flag protects against being on by accident. It does nothing about
    being on while the model is broken, which is the live condition today."""
    out = resim_live_game(
        STATE, home_offense=25.0, home_defense=22.0,
        away_offense=25.0, away_defense=22.0,
        env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    assert isinstance(out, NflResimRefusal)
    assert out.reason == "degenerate_ratings"


def test_a_refusal_still_produces_a_LANE():
    """A lane that vanishes on refusal is indistinguishable from a game the
    producer never saw. That ambiguity is what made NCAAF's original zero
    unreadable for a day."""
    lanes = build_game_lens(STATE, NflResimRefusal("degenerate_ratings", "x"))
    assert len(lanes) == 1
    assert lanes[0]["ok"] is False
    assert lanes[0]["refusal"]["reason"] == "degenerate_ratings"
    assert lanes[0]["source"] == "live_resim"


def test_summarise_reports_the_BREAKDOWN_not_just_a_count():
    """A zero with no refusal breakdown is not a result -- it cannot tell
    'nothing was live' from 'everything refused'."""
    games = [{"gameLens": build_game_lens(STATE, NflResimRefusal("degenerate_ratings"))},
             {"gameLens": build_game_lens(STATE, NflResimRefusal("bad_clock"))}]
    out = summarise(games)
    assert out["live_resimmed"] == 0
    assert out["refused"] == 2
    assert out["refusals_by_reason"] == {"degenerate_ratings": 1, "bad_clock": 1}
    assert out["enabled"] is False


def test_overtime_is_refused_before_the_sim_runs():
    out = resim_live_game(
        NflLiveGameState(away_team="A", home_team="B", period=5, clock_seconds=300,
                         home_score=20, away_score=20),
        **SEPARATED, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    assert isinstance(out, NflResimRefusal)
    assert out.reason == "overtime_not_resumable"

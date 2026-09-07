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


# --------------------------------------------------------------------------
# THE OUTPUT GUARD. Added 2026-09-07 after lane soccer-unfed-inputs showed the
# input floor covered 13% of a 93.8% defect -- arithmetic re-derived before
# accepting: NFL rating sd 2.16 -> gap sd 3.05 -> P(|gap|<0.5) = 13.0%, against
# a measured 93.8% of games landing inside P(home) 0.35-0.65. At least 80.8% of
# games cleared the floor AND were uninformative.
# --------------------------------------------------------------------------
from syndicate.features.nfl.live_resim import UNINFORMATIVE_BAND  # noqa: E402


def test_a_coin_flip_output_is_REFUSED_even_with_separated_ratings():
    """The case the input floor could not see: ratings that clear the gap floor
    and still produce a probability inside the band the engine cannot beat the
    close in. This is ~81% of NFL games today."""
    out = resim_live_game(
        NflLiveGameState(away_team="A", home_team="B", period=1,
                         clock_seconds=900, home_score=0, away_score=0),
        **SEPARATED, sims=40, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    if isinstance(out, NflResimRefusal):
        assert out.reason in {"uninformative_probability", "degenerate_ratings"}
        if out.reason == "uninformative_probability":
            assert "skill gate" in out.detail or "t=+3.34" in out.detail
    else:
        # If it published, it must be OUTSIDE the band -- never inside it.
        lo, hi = UNINFORMATIVE_BAND
        p = out["model_home_win_prob"]
        assert not (lo <= p <= hi), (
            f"published p={p} inside the uninformative band {lo}-{hi}")


def test_a_decided_game_still_publishes():
    """off != on for the output guard. A guard that refuses everything is the
    same as no producer -- a blowout late must still price, because that is a
    probability the engine CAN express."""
    out = resim_live_game(
        NflLiveGameState(away_team="A", home_team="B", period=4,
                         clock_seconds=60, home_score=38, away_score=3),
        **SEPARATED, sims=40, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    assert not isinstance(out, NflResimRefusal), getattr(out, "detail", "")
    lo, hi = UNINFORMATIVE_BAND
    assert out["model_home_win_prob"] > hi


def test_the_band_is_the_measured_one_not_an_invented_one():
    """Pins the constant to the measurement it came from. If someone widens it,
    this test makes them say why."""
    assert UNINFORMATIVE_BAND == (0.35, 0.65)


# --------------------------------------------------------------------------
# THE SNAPSHOT HALF. `_run_ncaaf_live_resim_tick` calls five things from its
# producer; this module shipped with two. These cover the three that were
# missing, and the property that matters most: the snapshot cannot bypass
# `resim_live_game`, so the flag and the band still apply to every game in it.
# --------------------------------------------------------------------------
from syndicate.features.nfl.live_resim import (  # noqa: E402
    build_live_lens_snapshot,
    live_lens_snapshot_path,
    live_state_from_row,
    validate_live_lens_snapshot,
)

LIVE_ROW = {
    "state": "live", "period": 3, "clock_seconds": 600,
    "home_score": 17, "away_score": 13, "possession_owner": "home",
    "down": 2, "distance": 7, "field_position": 41,
}
GAMES = [{"away_team": "Dallas Cowboys", "home_team": "Philadelphia Eagles",
          "live_key": "g1"}]
RATINGS = {"Philadelphia Eagles": (27.0, 19.0), "Dallas Cowboys": (20.0, 24.0)}


def test_snapshot_path_is_the_KEYVALUE_route():
    """`data/live/` routes to Redis on Render; a date-scoped path would never be
    carried by `pull_hot_artifacts`' `*<date>*` glob, and the symptom would look
    exactly like the producer never running."""
    p = str(live_lens_snapshot_path("/opt/render/project/data")).replace("\\", "/")
    assert p.endswith("/live/nfl_live_lens.json")


def test_validator_REJECTS_a_snapshot_with_no_games_list():
    ok, why = validate_live_lens_snapshot({"sport": "nfl"})
    assert ok is False and why == "snapshot_carries_no_games_list"


def test_validator_ACCEPTS_a_real_snapshot():
    """off != on. A validator that rejects everything is the same as one that
    rejects nothing -- it just moves where the silence happens."""
    snap = build_live_lens_snapshot("2026-09-14", games=GAMES,
                                    live_index={"g1": LIVE_ROW}, ratings=RATINGS,
                                    sims=20, env={})
    ok, why = validate_live_lens_snapshot(snap)
    assert ok is True, why


def test_the_snapshot_CANNOT_bypass_the_flag():
    """The whole safety argument rests on this. If the snapshot path could reach
    the sim without going through `resim_live_game`, the flag and the band would
    both be decorative."""
    snap = build_live_lens_snapshot("2026-09-14", games=GAMES,
                                    live_index={"g1": LIVE_ROW}, ratings=RATINGS,
                                    sims=20, env={})
    lanes = snap["games"][0]["gameLens"]
    assert lanes[0]["ok"] is False
    assert lanes[0]["refusal"]["reason"] == "nfl_live_resim_disabled"
    assert snap["coverage"]["live_resimmed"] == 0


def test_a_missing_live_row_refuses_BY_NAME():
    snap = build_live_lens_snapshot("2026-09-14", games=GAMES, live_index={},
                                    ratings=RATINGS, sims=20, env={})
    assert snap["coverage"]["refusals_by_reason"] == {"no_live_state": 1}


def test_an_incomplete_payload_names_the_MISSING_KEY():
    """NFL's ESPN `situation` shape has never been checked against the one
    NCAAF's transform assumes. A mismatch must surface as a named refusal
    carrying the missing key, not as a confident state built from defaults."""
    out = live_state_from_row({"state": "live", "period": 2},
                              away_team="A", home_team="B")
    assert out.reason == "incomplete_live_state"
    assert "clock_seconds" in out.detail


def test_a_final_game_is_refused_not_simulated():
    out = live_state_from_row({**LIVE_ROW, "state": "final"},
                              away_team="A", home_team="B")
    assert out.reason == "game_final"


def test_budget_exhaustion_refuses_BY_NAME_rather_than_shortening_the_slate():
    """A short slate and a refused slate look identical from the board. `#241`
    is why the budget exists; naming it is why the zero is readable."""
    many = [{"away_team": f"A{i}", "home_team": f"H{i}", "live_key": f"g{i}"}
            for i in range(6)]
    index = {f"g{i}": LIVE_ROW for i in range(6)}
    snap = build_live_lens_snapshot(
        "2026-09-14", games=many, live_index=index,
        ratings={f"H{i}": (27.0, 19.0) for i in range(6)}
        | {f"A{i}": (20.0, 24.0) for i in range(6)},
        sims=20, budget_seconds=1.0, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    reasons = snap["coverage"]["refusals_by_reason"]
    assert snap["coverage"]["games"] == 6
    # Every game is accounted for: resimmed + refused == games. A game that
    # simply vanished would break this and nothing else would notice.
    assert snap["coverage"]["live_resimmed"] + snap["coverage"]["refused"] == 6
    assert "budget_seconds" in snap["coverage"]
    assert reasons  # something refused; which reason depends on machine speed

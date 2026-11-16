"""The NFL live re-sim feeds smartsim2 the real timeouts left (todo #808, lane `nfl-live-timeouts`).

Reachability BEFORE correctness, per `docs/ai_context/model_engine_standard.md`:
  * the row's `home_timeouts` / `away_timeouts` reach the engine's `initial_timeouts_*` (call-site capture);
  * with the profile's `end_of_half_clock` OFF the re-sim is byte-identical with and without them;
  * with it ON, (0, 0) and (3, 3) give different games (off != on), in the direction the clock implies.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.features.nfl.live_resim as live_resim  # noqa: E402
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (  # noqa: E402
    NFL_CALIBRATION_PROFILE,
)
from syndicate.features.nfl.live_resim import (  # noqa: E402
    NflLiveGameState,
    NflResimRefusal,
    _timeouts_left,
    build_game_lens,
    live_state_from_row,
    resim_live_game,
)

ON = {"SYNDICATE_NFL_LIVE_RESIM": "1"}
SEPARATED = dict(home_offense=27.0, home_defense=19.0, away_offense=20.0, away_defense=24.0)

# THE CLOCK OFF, explicitly, so this file does not depend on what today's NFL profile happens to be.
CLOCK_OFF = replace(NFL_CALIBRATION_PROFILE, end_of_half_clock=False)
# The seven #808 switches ON: the candidate profile of the held-out read (2026-11-15).
CLOCK_ON = replace(
    NFL_CALIBRATION_PROFILE,
    halftime_kickoff=True, q2_urgency_ignores_score=True, end_of_half_clock=True,
    end_of_half_kneel_out=True, end_of_half_clock_by_need=True, q4_kick_waits=True,
    kneel_out_q4_only=True,
)

# The leader has the ball at its own 30 with 1:50 left. Whether the trailer can stop the clock is the
# whole question, which is the state the timeouts exist for.
LATE = dict(away_team="A", home_team="B", period=4, clock_seconds=110, home_score=24, away_score=17,
            down=1, distance=10, field_position=30, possession_owner="home")

ROW = {"state": "in", "period": 4, "clock_seconds": 110, "home_score": 24, "away_score": 17,
       "possession_owner": "home"}


def _without_timing(out):
    return {k: v for k, v in out.items() if k not in ("elapsed_seconds", "timeouts_fed")}


# ---- the parse --------------------------------------------------------------------------------------

def test_timeouts_left_takes_0_to_3_and_nothing_else():
    assert [_timeouts_left(v) for v in (0, 1, 2, 3, "2", " 3 ", 1.0)] == [0, 1, 2, 3, 2, 3, 1]
    for bad in (None, 4, -1, 2.5, "x", "", "-1", "²", "4", True, False, [], {}):
        assert _timeouts_left(bad) is None, bad


def test_the_row_carries_the_timeouts_into_the_state():
    st = live_state_from_row(dict(ROW, home_timeouts=1, away_timeouts=0), away_team="A", home_team="B")
    assert isinstance(st, NflLiveGameState)
    assert (st.home_timeouts, st.away_timeouts) == (1, 0)


def test_an_absent_or_broken_value_is_None_never_a_guess():
    st = live_state_from_row(dict(ROW), away_team="A", home_team="B")
    assert (st.home_timeouts, st.away_timeouts) == (None, None)
    st = live_state_from_row(dict(ROW, home_timeouts=7, away_timeouts="two"), away_team="A", home_team="B")
    assert (st.home_timeouts, st.away_timeouts) == (None, None)


# ---- reachability at the call site ------------------------------------------------------------------

def _capture(monkeypatch):
    seen = []

    def fake(simulation_input, *, profile):
        seen.append(simulation_input)
        return SimpleNamespace(final_score={"home": 30, "away": 0})

    monkeypatch.setattr(live_resim, "simulate_game", fake)
    return seen


def test_the_row_reaches_the_engine_input(monkeypatch):
    seen = _capture(monkeypatch)
    st = live_state_from_row(dict(ROW, home_timeouts=1, away_timeouts=2), away_team="A", home_team="B")
    out = resim_live_game(st, **SEPARATED, sims=6, env=ON)
    assert not isinstance(out, NflResimRefusal), getattr(out, "detail", "")
    assert len(seen) == 6
    assert {(i.initial_timeouts_home, i.initial_timeouts_away) for i in seen} == {(1, 2)}
    assert out["timeouts_fed"] is True


def test_absent_timeouts_leave_the_engine_input_as_it_was(monkeypatch):
    seen = _capture(monkeypatch)
    out = resim_live_game(live_state_from_row(dict(ROW), away_team="A", home_team="B"),
                          **SEPARATED, sims=4, env=ON)
    assert {(i.initial_timeouts_home, i.initial_timeouts_away) for i in seen} == {(None, None)}
    assert out["timeouts_fed"] is False


def test_one_side_only_is_passed_but_not_called_fed(monkeypatch):
    seen = _capture(monkeypatch)
    out = resim_live_game(NflLiveGameState(**LATE, away_timeouts=0), **SEPARATED, sims=2, env=ON)
    assert {(i.initial_timeouts_home, i.initial_timeouts_away) for i in seen} == {(None, 0)}
    assert out["timeouts_fed"] is False


# ---- inert with the clock OFF, reachable with it ON -------------------------------------------------

def test_clock_off_is_byte_identical_with_and_without_timeouts():
    """The engine reads timeouts only under `end_of_half_clock`, so feeding them changes nothing until a
    profile load turns it on. Pinned on real sims, in the state where they would matter most."""
    fed = resim_live_game(NflLiveGameState(**LATE, home_timeouts=0, away_timeouts=0),
                          **SEPARATED, sims=60, env=ON, profile=CLOCK_OFF)
    unfed = resim_live_game(NflLiveGameState(**LATE), **SEPARATED, sims=60, env=ON, profile=CLOCK_OFF)
    assert not isinstance(fed, NflResimRefusal), getattr(fed, "detail", "")
    assert _without_timing(fed) == _without_timing(unfed)
    assert (fed["timeouts_fed"], unfed["timeouts_fed"]) == (True, False)


def test_clock_on_the_timeouts_change_the_game():
    """off != on. A defence with no timeouts cannot stop a leader who has the ball: the leader kneels it out,
    so fewer points are scored and the leader wins at least as often."""
    none_left = resim_live_game(NflLiveGameState(**LATE, home_timeouts=3, away_timeouts=0),
                                **SEPARATED, sims=120, env=ON, profile=CLOCK_ON)
    all_left = resim_live_game(NflLiveGameState(**LATE, home_timeouts=3, away_timeouts=3),
                               **SEPARATED, sims=120, env=ON, profile=CLOCK_ON)
    for out in (none_left, all_left):
        assert not isinstance(out, NflResimRefusal), getattr(out, "detail", "")
    assert none_left["margin_dist"] != all_left["margin_dist"]
    assert none_left["total_mean"] < all_left["total_mean"]
    assert none_left["model_home_win_prob_raw"] >= all_left["model_home_win_prob_raw"]


# ---- published ---------------------------------------------------------------------------------------

def test_the_lane_publishes_the_timeouts_only_when_the_feed_said(monkeypatch):
    _capture(monkeypatch)
    st = NflLiveGameState(**LATE, home_timeouts=2, away_timeouts=0)
    lane = build_game_lens(st, resim_live_game(st, **SEPARATED, sims=2, env=ON))[0]
    assert lane["live_state"]["home_timeouts"] == 2 and lane["live_state"]["away_timeouts"] == 0
    assert lane["timeouts_fed"] is True

    bare = NflLiveGameState(**LATE)
    lane = build_game_lens(bare, resim_live_game(bare, **SEPARATED, sims=2, env=ON))[0]
    assert "home_timeouts" not in lane["live_state"] and "away_timeouts" not in lane["live_state"]
    assert lane["timeouts_fed"] is False

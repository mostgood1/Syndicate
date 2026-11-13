"""The NHL live re-sim plays overtime as it is played (lane nhl-live-overtime, todo #773).

Regular-season OT is sudden death: a game that reaches OT ends EXACTLY one goal past the tie, by an OT goal
or by the shootout credit. The engine used to play OT as one whole 5:00 segment and sum its goals, and a
state resumed IN overtime got a fresh 5:00 whatever the clock showed -- so some sims ended 2-3 goals past
the tie. `engine.simulate_with_lineups(ot_sudden_death=True)` cuts the OT segment at its first goal and,
resumed in OT, plays only the clock shown. `live_resim` turns it on (off switch SYNDICATE_NHL_LIVE_OVERTIME).

REACHABILITY BEFORE CORRECTNESS (`model_engine_standard`): every on-test here has an off twin that shows the
defect on the SAME seeds, so a pass is not vacuous.
"""
from __future__ import annotations

import inspect

import pytest

from syndicate.features.nhl import live_resim as LR
from syndicate.features.nhl.sim_engine.hockeysim import engine as E
from syndicate.features.nhl.sim_engine.hockeysim.models import RateModels
from syndicate.features.nhl.sim_engine.hockeysim.runtime import (
    run_hockeysim_game,
    run_hockeysim_game_from_state,
)
from tests.test_nhl_live_resim import AWAY, HOME, LINEUP_A, LINEUP_H, PERIOD_SECONDS, ROSTER_A, ROSTER_H, _StubFeatures

OT_IDX = 3              # the engine's 0-based OT index (`cfg.periods`)
OT_SECONDS = 5 * 60
SEEDS = range(300)
DATE = "2026-10-08"
PK = "2026020123"


def _run(seed, *, period_idx, secs, hs, as_, sudden):
    return run_hockeysim_game_from_state(
        HOME, AWAY, ROSTER_H, ROSTER_A, RateModels.baseline(),
        period_idx=period_idx, seconds_remaining=secs, home_score=hs, away_score=as_,
        lineup_home=LINEUP_H, lineup_away=LINEUP_A, seed=seed, ot_sudden_death=sudden,
    )


def _ot_goals(events):
    return [e for e in events if e.kind == "goal" and int(e.period) > 3]


def _shootouts(events):
    return [e for e in events if e.kind == "shootout"]


@pytest.fixture(scope="module")
def in_ot():
    """A state resumed at the start of OT, tied 2-2: off and on, the same 300 seeds."""
    off = [_run(s, period_idx=OT_IDX, secs=OT_SECONDS, hs=2, as_=2, sudden=False) for s in SEEDS]
    on = [_run(s, period_idx=OT_IDX, secs=OT_SECONDS, hs=2, as_=2, sudden=True) for s in SEEDS]
    return off, on


# --- the engine --------------------------------------------------------------------------------------------


def test_off_reproduces_the_defect_some_ot_sims_end_two_or_more_past_the_tie(in_ot):
    off, _ = in_ot
    past = sum(1 for gs, _ in off if abs(gs.home.score - gs.away.score) > 1)
    assert past > 0, "the control must show the defect, or the on-test proves nothing"


def test_on_every_ot_sim_ends_exactly_one_past_the_tie(in_ot):
    _, on = in_ot
    assert all(abs(gs.home.score - gs.away.score) == 1 for gs, _ in on)
    assert all(gs.home.score + gs.away.score == 5 for gs, _ in on)
    for _, ev in on:
        assert len(_ot_goals(ev)) + len(_shootouts(ev)) == 1


def test_on_is_the_same_ot_cut_at_its_first_goal_not_a_new_draw(in_ot):
    """Where off scored in OT, on's winner is the team of off's EARLIEST OT goal, at the same time."""
    off, on = in_ot
    checked = 0
    for (gs_off, ev_off), (gs_on, ev_on) in zip(off, on):
        goals_off = _ot_goals(ev_off)
        if not goals_off:
            assert (gs_on.home.score, gs_on.away.score) == (gs_off.home.score, gs_off.away.score)
            continue
        first = min(goals_off, key=lambda e: float(e.t))
        (winner,) = _ot_goals(ev_on)
        assert (winner.team, float(winner.t)) == (first.team, float(first.t))
        home_won = gs_on.home.score > gs_on.away.score
        assert home_won == (first.team == HOME)
        checked += 1
    assert checked > 0


def test_resumed_in_ot_with_no_time_left_goes_straight_to_the_shootout():
    """A shootout in progress reads as OT with 0:00 left. Off played a fresh 5:00 of OT anyway."""
    off = [_run(s, period_idx=OT_IDX, secs=0, hs=3, as_=3, sudden=False) for s in range(120)]
    on = [_run(s, period_idx=OT_IDX, secs=0, hs=3, as_=3, sudden=True) for s in range(120)]
    assert sum(1 for _, ev in off if _ot_goals(ev)) > 0
    assert all(not _ot_goals(ev) and len(_shootouts(ev)) == 1 for _, ev in on)
    assert all(abs(gs.home.score - gs.away.score) == 1 for gs, _ in on)


def test_resumed_in_ot_plays_only_the_clock_shown():
    """Fewer OT goals with 1:00 left than with 5:00 left; off ignored the clock (both were 5:00)."""
    def decided_in_ot(secs, sudden):
        return sum(1 for s in SEEDS if _ot_goals(_run(s, period_idx=OT_IDX, secs=secs, hs=1, as_=1, sudden=sudden)[1]))
    assert decided_in_ot(60, False) == decided_in_ot(OT_SECONDS, False)
    assert decided_in_ot(60, True) < decided_in_ot(OT_SECONDS, True)


def test_a_regulation_state_reaching_ot_obeys_it_and_regulation_endings_are_untouched():
    """Tied with 0:30 left in P3: sims that end in regulation are identical seed for seed; the ones that
    reach OT end exactly one past the tie."""
    reached_ot = 0
    for s in SEEDS:
        gs_off, ev_off = _run(s, period_idx=2, secs=30, hs=2, as_=2, sudden=False)
        gs_on, ev_on = _run(s, period_idx=2, secs=30, hs=2, as_=2, sudden=True)
        reg_off = [e for e in ev_off if int(e.period) <= 3]
        reg_on = [e for e in ev_on if int(e.period) <= 3]
        assert [(e.kind, e.team, e.t) for e in reg_on] == [(e.kind, e.team, e.t) for e in reg_off]
        if not any(int(e.period) > 3 for e in ev_off if e.kind in ("goal", "shootout")):
            assert (gs_on.home.score, gs_on.away.score) == (gs_off.home.score, gs_off.away.score)
            continue
        reached_ot += 1
        assert abs(gs_on.home.score - gs_on.away.score) == 1
    assert reached_ot > 0


def test_pregame_never_turns_it_on():
    """The pregame entry point does not pass the flag, and the engine's default is off: every pregame
    number is the one it was (a resume at the opening faceoff with it off IS the pregame run)."""
    assert inspect.signature(E.GameSimulator.simulate_with_lineups).parameters["ot_sudden_death"].default is False
    assert "ot_sudden_death" not in inspect.signature(run_hockeysim_game).parameters
    for s in range(60):
        pre, _ = run_hockeysim_game(HOME, AWAY, ROSTER_H, ROSTER_A, RateModels.baseline(),
                                    lineup_home=LINEUP_H, lineup_away=LINEUP_A, seed=s)
        res, _ = _run(s, period_idx=0, secs=PERIOD_SECONDS, hs=0, as_=0, sudden=False)
        assert (res.home.score, res.away.score) == (pre.home.score, pre.away.score)


def test_the_cut_never_leaves_more_than_one_goal_even_without_goal_events():
    assert E._cut_at_first_goal(2, 1, [], HOME) == (1, 0, [])
    assert E._cut_at_first_goal(0, 3, [], HOME) == (0, 1, [])
    assert E._cut_at_first_goal(1, 1, [], HOME) == (0, 0, [])


# --- live_resim: the switch reaches the published lane ------------------------------------------------------


def _state(period, clock, home, away):
    return LR.NhlLiveGameState(game_pk=PK, home_name=HOME, away_name=AWAY, home_score=home, away_score=away,
                               period=period, clock_seconds=clock, as_of="test")


def _features():
    return _StubFeatures(PK, HOME, AWAY)


def test_reachability_the_resim_differs_off_vs_on_in_ot():
    off = LR.resim_live_game(_features(), _state(4, 300, 2, 2), sims=200, base_seed=11, overtime_sudden_death=False)
    on = LR.resim_live_game(_features(), _state(4, 300, 2, 2), sims=200, base_seed=11, overtime_sudden_death=True)
    assert any(abs(int(k)) > 1 for k in off["margin_dist"])
    assert set(on["margin_dist"]) <= {"-1", "1"}
    assert off["total_mean"] > 5.0
    assert on["total_mean"] == 5.0       # the tied total + 1, every sim (OT goals are never thinned)
    assert off["overtime"] == {"rule": "full_segment", "calibration": "off", "sims_past_regulation": 200,
                               "resumed_ot_clock_seconds": 300}
    assert on["overtime"] == {"rule": "sudden_death", "calibration": "on", "sims_past_regulation": 200,
                              "resumed_ot_clock_seconds": 300}


def test_regulation_endings_are_identical_off_vs_on_mid_game():
    off = LR.resim_live_game(_features(), _state(2, 600, 1, 1), sims=120, base_seed=3, overtime_sudden_death=False)
    on = LR.resim_live_game(_features(), _state(2, 600, 1, 1), sims=120, base_seed=3, overtime_sudden_death=True)
    assert off["regulation_margin_dist"] == on["regulation_margin_dist"]
    assert sum(off["overtime_margin_dist"].values()) == sum(on["overtime_margin_dist"].values())
    assert set(on["overtime_margin_dist"]) <= {"-1", "1"}
    assert on["overtime"]["resumed_ot_clock_seconds"] is None


def test_the_env_switch_is_the_old_ot_and_unset_is_on(monkeypatch):
    monkeypatch.delenv(LR.LIVE_OVERTIME_ENV, raising=False)
    assert LR.live_overtime_sudden_death() is True
    monkeypatch.setenv(LR.LIVE_OVERTIME_ENV, "off")
    assert LR.live_overtime_sudden_death() is False
    by_env = LR.resim_live_game(_features(), _state(4, 300, 2, 2), sims=60, base_seed=11)
    explicit = LR.resim_live_game(_features(), _state(4, 300, 2, 2), sims=60, base_seed=11, overtime_sudden_death=False)
    assert by_env["margin_dist"] == explicit["margin_dist"] and by_env["overtime"]["rule"] == "full_segment"


def _ot_score_row(remaining="03:10", secs=190, home=2, away=2):
    return {
        "id": int(PK), "gameState": "LIVE", "periodDescriptor": {"number": 4, "periodType": "OT"},
        "clock": {"timeRemaining": remaining, "secondsRemaining": secs, "inIntermission": False},
        "homeTeam": {"id": 10, "name": {"default": HOME}, "score": home},
        "awayTeam": {"id": 9, "name": {"default": AWAY}, "score": away},
    }


def test_the_published_lane_carries_live_overtime_and_a_one_goal_ot(monkeypatch):
    monkeypatch.delenv(LR.LIVE_OVERTIME_ENV, raising=False)
    snap = LR.build_live_lens_snapshot(DATE, sims=60, score_rows=[_ot_score_row()], slate_features=[_features()])
    (lane,) = snap["games"][0]["gameLens"]
    assert lane["source"] == LR.LIVE_RESIM_LENS_SOURCE
    assert lane["liveOvertime"]["rule"] == "sudden_death"
    assert lane["liveOvertime"]["resumed_ot_clock_seconds"] == 190
    assert set(lane["projection"]["displayMarginDist"]) <= {"-1", "1"}
    assert lane["projection"]["total"] == 5.0

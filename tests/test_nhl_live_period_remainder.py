"""The rest of the CURRENT period is played as regulation (lane nhl-live-period-remainder, todo #773).

`simulate_period_with_lines` used to infer overtime from a period's LENGTH (`T != seconds_per_period`). A live
resume's first period is always short, so the rest of a regulation period was simulated as overtime: 3-on-3
skaters, the score effects' urgency on that period's clock alone, the game's power-play seconds packed into the
remainder, shorter segments. `simulate_with_lineups(explicit_period_kind=True)` states the period's kind instead;
`live_resim` turns it on (off switch SYNDICATE_NHL_LIVE_PERIOD_REMAINDER).

REACHABILITY BEFORE CORRECTNESS: every on-test has an off twin that shows the defect on the same seeds.
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

GOALIES = {1200, 2200}           # the stub rosters' goalie ids (base + 200)
SEEDS = range(120)
PK = "2026020123"


def _run(seed, *, period_idx, secs, hs=0, as_=0, explicit):
    return run_hockeysim_game_from_state(
        HOME, AWAY, ROSTER_H, ROSTER_A, RateModels.baseline(),
        period_idx=period_idx, seconds_remaining=secs, home_score=hs, away_score=as_,
        lineup_home=LINEUP_H, lineup_away=LINEUP_A, seed=seed, ot_sudden_death=True, explicit_period_kind=explicit,
    )


def _ev_skaters_per_segment(events, period):
    """Skaters on ice per (team, segment start) in EV segments of `period` (1-based), goalies excluded."""
    out = {}
    for e in events:
        if e.kind == "shift" and int(e.period) == period and e.player_id not in GOALIES \
                and (e.meta or {}).get("strength") == "EV":
            key = (e.team, round(float(e.t), 6))
            out[key] = out.get(key, 0) + 1
    return out


def _pp_segment_share(events, period):
    """Share of `period`'s segments in which either side is on the power play (home's view of each segment)."""
    segs = {}
    for e in events:
        if e.kind == "shift" and int(e.period) == period and e.team == HOME and e.player_id in GOALIES:
            segs[round(float(e.t), 6)] = (e.meta or {}).get("strength")
    return sum(1 for s in segs.values() if s in ("PP", "PK")) / max(1, len(segs))


# --- the engine --------------------------------------------------------------------------------------------


def test_off_reproduces_the_defect_the_rest_of_p1_is_three_on_three():
    _, ev = _run(3, period_idx=0, secs=600, explicit=False)
    counts = set(_ev_skaters_per_segment(ev, 1).values())
    assert counts == {3}, counts                      # the control: the defect is there, so the on-test means something
    _, ev_p2 = _run(3, period_idx=0, secs=600, explicit=False)
    assert set(_ev_skaters_per_segment(ev_p2, 2).values()) == {5}      # whole periods were always 5-on-5


def test_on_the_rest_of_the_period_is_five_on_five():
    for s in range(20):
        _, ev = _run(s, period_idx=0, secs=600, explicit=True)
        assert set(_ev_skaters_per_segment(ev, 1).values()) == {5}
        _, ev3 = _run(s, period_idx=2, secs=300, hs=2, as_=2, explicit=True)
        assert set(_ev_skaters_per_segment(ev3, 3).values()) <= {5}


def test_on_the_power_play_share_of_the_remainder_is_the_games_not_packed():
    """Off, the game's PP seconds are divided by the period's remaining 600 s (capped at 0.45): far more PP than in a
    whole period. On, the remainder's PP share matches a whole period's."""
    off = sum(_pp_segment_share(_run(s, period_idx=0, secs=600, explicit=False)[1], 1) for s in SEEDS) / len(SEEDS)
    on = sum(_pp_segment_share(_run(s, period_idx=0, secs=600, explicit=True)[1], 1) for s in SEEDS) / len(SEEDS)
    whole = sum(_pp_segment_share(_run(s, period_idx=0, secs=PERIOD_SECONDS, explicit=True)[1], 1)
                for s in SEEDS) / len(SEEDS)
    assert off > on + 0.10, (off, on)
    assert abs(on - whole) < 0.05, (on, whole)


def test_the_score_effect_clock_counts_the_periods_still_to_come():
    clock = E._score_effect_clock
    assert clock(3, 1200, 0, 600.0, False) == 3000.0       # P1 10:00 left: 50 minutes of game
    assert clock(3, 1200, 1, 300.0, False) == 1500.0
    assert clock(3, 1200, 2, 120.0, False) == 120.0
    assert clock(3, 1200, 3, 200.0, True) == 200.0          # OT is its own clock
    assert clock(3, 1200, 0, 600.0, True) == 600.0          # what off did to a resumed P1


def test_a_resume_at_a_period_start_is_unchanged():
    """A whole period was never misread, so resuming at P2 20:00 is the same game on or off, seed for seed."""
    for s in range(40):
        a, ev_a = _run(s, period_idx=1, secs=PERIOD_SECONDS, hs=1, as_=0, explicit=False)
        b, ev_b = _run(s, period_idx=1, secs=PERIOD_SECONDS, hs=1, as_=0, explicit=True)
        assert (a.home.score, a.away.score) == (b.home.score, b.away.score)
        assert [(e.kind, e.team, e.t) for e in ev_a] == [(e.kind, e.team, e.t) for e in ev_b]


def test_pregame_never_turns_it_on_and_is_unchanged():
    assert inspect.signature(E.GameSimulator.simulate_with_lineups).parameters["explicit_period_kind"].default is False
    assert "explicit_period_kind" not in inspect.signature(run_hockeysim_game).parameters
    for s in range(40):
        pre, _ = run_hockeysim_game(HOME, AWAY, ROSTER_H, ROSTER_A, RateModels.baseline(),
                                    lineup_home=LINEUP_H, lineup_away=LINEUP_A, seed=s)
        on, _ = run_hockeysim_game_from_state(
            HOME, AWAY, ROSTER_H, ROSTER_A, RateModels.baseline(), period_idx=0, seconds_remaining=PERIOD_SECONDS,
            home_score=0, away_score=0, lineup_home=LINEUP_H, lineup_away=LINEUP_A, seed=s,
            explicit_period_kind=True)
        assert (on.home.score, on.away.score) == (pre.home.score, pre.away.score)


def test_overtime_is_still_three_on_three():
    _, ev = _run(5, period_idx=3, secs=300, hs=2, as_=2, explicit=True)
    counts = set(_ev_skaters_per_segment(ev, 4).values())
    assert counts <= {3} and counts


# --- live_resim: the switch reaches the published lane ------------------------------------------------------


def _state(period, clock, home, away):
    return LR.NhlLiveGameState(game_pk=PK, home_name=HOME, away_name=AWAY, home_score=home, away_score=away,
                               period=period, clock_seconds=clock, as_of="test")


def _features():
    return _StubFeatures(PK, HOME, AWAY)


def test_reachability_the_resim_differs_off_vs_on_mid_period():
    st = _state(1, 600, 0, 0)
    off = LR.resim_live_game(_features(), st, sims=120, base_seed=11, period_remainder_regulation=False)
    on = LR.resim_live_game(_features(), st, sims=120, base_seed=11, period_remainder_regulation=True)
    assert off["raw_total_dist"] != on["raw_total_dist"]
    assert off["period_remainder"] == {"play": "inferred_from_length", "calibration": "off",
                                       "resumed_period_seconds": 600}
    assert on["period_remainder"] == {"play": "regulation", "calibration": "on", "resumed_period_seconds": 600}


def test_at_a_period_start_the_resim_is_identical_off_vs_on():
    st = _state(2, PERIOD_SECONDS, 1, 0)
    off = LR.resim_live_game(_features(), st, sims=60, base_seed=5, period_remainder_regulation=False)
    on = LR.resim_live_game(_features(), st, sims=60, base_seed=5, period_remainder_regulation=True)
    for key in ("margin_dist", "raw_total_dist", "home_win_prob", "total_mean"):
        assert off[key] == on[key], key


def test_the_env_switch_is_the_old_play_and_unset_is_on(monkeypatch):
    monkeypatch.delenv(LR.LIVE_PERIOD_REMAINDER_ENV, raising=False)
    assert LR.live_period_remainder_regulation() is True
    monkeypatch.setenv(LR.LIVE_PERIOD_REMAINDER_ENV, "off")
    assert LR.live_period_remainder_regulation() is False
    st = _state(1, 600, 0, 0)
    by_env = LR.resim_live_game(_features(), st, sims=40, base_seed=11)
    explicit = LR.resim_live_game(_features(), st, sims=40, base_seed=11, period_remainder_regulation=False)
    assert by_env["raw_total_dist"] == explicit["raw_total_dist"]
    assert by_env["period_remainder"]["play"] == "inferred_from_length"


def _score_row(period=1, remaining="10:00", secs=600, home=0, away=0):
    return {
        "id": int(PK), "gameState": "LIVE", "periodDescriptor": {"number": period, "periodType": "REG"},
        "clock": {"timeRemaining": remaining, "secondsRemaining": secs, "inIntermission": False},
        "homeTeam": {"id": 10, "name": {"default": HOME}, "score": home},
        "awayTeam": {"id": 9, "name": {"default": AWAY}, "score": away},
    }


def test_the_published_lane_carries_live_period_remainder(monkeypatch):
    monkeypatch.delenv(LR.LIVE_PERIOD_REMAINDER_ENV, raising=False)
    snap = LR.build_live_lens_snapshot("2026-10-08", sims=30, score_rows=[_score_row()], slate_features=[_features()])
    (lane,) = snap["games"][0]["gameLens"]
    assert lane["source"] == LR.LIVE_RESIM_LENS_SOURCE
    assert lane["livePeriodRemainder"] == {"play": "regulation", "calibration": "on", "resumed_period_seconds": 600}

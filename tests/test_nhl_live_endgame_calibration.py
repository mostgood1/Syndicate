"""The NHL live re-sim's END-GAME (lane nhl-live-endgame-calibration, todo #773).

The 2026-11-11 replay failed the live histogram on one state: a one-goal lead late in the third, where the
leader went on to win by 2+ in 0.43 of games against the model's 0.18 -- the empty-net goal the event engine
under-produces. `resim_live_game` now gives a sim that finishes REGULATION with a one-goal lead one more goal
for the leader with probability p (ramped down inside the last minutes), fit on this engine by walk-forward
replay. These pin, reachability first (model_engine_standard 4.3):
  - REACHABILITY: through the REAL producer and `build_live_lens_snapshot`, on != off, and the lane says which;
  - OFF IS TODAY: the engine's draws are untouched, so the raw splits are identical on and off, and off's
    histogram is exactly their sum; the winner never changes (an empty-net goal only extends a lead);
  - SCOPE: only regulation-end +-1 sims move, and only to +-2; OT/SO sims never move;
  - the ramp, the OT zero and the env switch;
  - the harness applies the same p IN EXPECTATION, and its closed-form fit recovers a known p.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from syndicate.features.nhl import live_resim as LR
from tests.test_nhl_live_resim import _StubFeatures

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backtest_nhl_live_puckline.py"
_spec = importlib.util.spec_from_file_location("backtest_nhl_live_puckline_endgame", _PATH)
H = importlib.util.module_from_spec(_spec)
sys.modules["backtest_nhl_live_puckline_endgame"] = H
_spec.loader.exec_module(H)

DATE = "2026-10-08"
PK = "2026020123"
HOME, AWAY = "Toronto Maple Leafs", "Ottawa Senators"
ON = {"empty_net_p": 1.0, "ramp_seconds": 0.0}      # every eligible sim moves: the clearest on != off


def _state(period=3, clock=300, home=2, away=1):
    return LR.NhlLiveGameState(game_pk=PK, home_name=HOME, away_name=AWAY, home_score=home, away_score=away,
                               period=period, clock_seconds=clock, as_of="test")


def _features():
    return _StubFeatures(PK, HOME, AWAY)


@pytest.fixture(scope="module")
def pair():
    off = LR.resim_live_game(_features(), _state(), sims=80, base_seed=11, endgame=LR.LEGACY_LIVE_ENDGAME)
    on = LR.resim_live_game(_features(), _state(), sims=80, base_seed=11, endgame=ON)
    return off, on


def _score_row(period=3, remaining="05:00", secs=300, home=2, away=1):
    return {
        "id": int(PK), "gameState": "LIVE", "periodDescriptor": {"number": period, "periodType": "REG"},
        "clock": {"timeRemaining": remaining, "secondsRemaining": secs, "inIntermission": False},
        "homeTeam": {"id": 10, "name": {"default": HOME}, "score": home},
        "awayTeam": {"id": 9, "name": {"default": AWAY}, "score": away},
    }


def _lane(monkeypatch, calibration):
    monkeypatch.setattr(LR, "NHL_LIVE_ENDGAME_CALIBRATION", dict(calibration))
    monkeypatch.delenv(LR.LIVE_ENDGAME_ENV, raising=False)
    snap = LR.build_live_lens_snapshot(DATE, sims=60, score_rows=[_score_row()], slate_features=[_features()])
    (lane,) = snap["games"][0]["gameLens"]
    assert lane["source"] == LR.LIVE_RESIM_LENS_SOURCE
    return lane


def test_reachability_the_published_lane_differs_on_vs_off(monkeypatch):
    off = _lane(monkeypatch, LR.LEGACY_LIVE_ENDGAME)
    on = _lane(monkeypatch, ON)
    assert off["liveEndgame"]["calibration"] == "off" and off["liveEndgame"]["empty_net_goals"] == 0
    assert on["liveEndgame"]["calibration"] == "on" and on["liveEndgame"]["empty_net_p"] == 1.0
    assert on["liveEndgame"]["empty_net_goals"] > 0
    assert on["projection"]["displayMarginDist"] != off["projection"]["displayMarginDist"]
    assert on["projection"]["total"] == off["projection"]["total"]         # the MARGIN only, by design
    assert on["modelHomeWinProb"] == off["modelHomeWinProb"]               # and never changes the winner


def test_the_shipped_calibration_is_the_replay_fit():
    # findings_2026-11-11_nhl_live_endgame_calibration.md: full-sample fit on 284 games / 41 dates
    assert LR.NHL_LIVE_ENDGAME_CALIBRATION == {"empty_net_p": 0.38, "ramp_seconds": 90.0}


def test_the_env_switch_turns_the_shipped_calibration_off(monkeypatch):
    monkeypatch.setenv(LR.LIVE_ENDGAME_ENV, "off")
    assert LR.live_endgame_calibration() == LR.LEGACY_LIVE_ENDGAME
    monkeypatch.delenv(LR.LIVE_ENDGAME_ENV)
    assert LR.live_endgame_calibration() == LR.NHL_LIVE_ENDGAME_CALIBRATION


def test_off_is_todays_histogram_and_the_engine_draws_are_untouched(pair):
    off, on = pair
    assert off["regulation_margin_dist"] == on["regulation_margin_dist"]
    assert off["overtime_margin_dist"] == on["overtime_margin_dist"]
    summed = dict(off["regulation_margin_dist"])
    for k, v in off["overtime_margin_dist"].items():
        summed[k] = summed.get(k, 0) + v
    assert off["margin_dist"] == summed
    assert off["home_win_prob"] == on["home_win_prob"]
    assert off["endgame"] == {"empty_net_p": 0.0, "ramp_seconds": 0.0, "empty_net_goals": 0, "calibration": "off"}


def test_only_regulation_end_one_goal_sims_move_and_only_to_two(pair):
    _off, on = pair
    reg = {int(k): v for k, v in on["regulation_margin_dist"].items()}
    ot = {int(k): v for k, v in on["overtime_margin_dist"].items()}
    final = {int(k): v for k, v in on["margin_dist"].items()}
    assert reg.get(1, 0) + reg.get(-1, 0) > 0                              # the branch under test ran
    assert set(ot) <= {1, -1}                                              # OT/SO ends by exactly one
    assert final.get(1, 0) == ot.get(1, 0) and final.get(-1, 0) == ot.get(-1, 0)   # p = 1: every reg +-1 moved
    assert final.get(2, 0) == reg.get(2, 0) + reg.get(1, 0)
    assert final.get(-2, 0) == reg.get(-2, 0) + reg.get(-1, 0)
    for k in set(final) - {1, -1, 2, -2}:
        assert final[k] == reg.get(k, 0) + ot.get(k, 0)
    assert on["endgame"]["empty_net_goals"] == reg.get(1, 0) + reg.get(-1, 0)


def test_the_ramp_reads_the_time_the_one_goal_margin_had():
    cal = {"empty_net_p": 0.4, "ramp_seconds": 120.0}
    assert LR.endgame_empty_net_prob(cal, seconds_left=1800) == 0.4
    assert LR.endgame_empty_net_prob(cal, seconds_left=120) == 0.4
    assert LR.endgame_empty_net_prob(cal, seconds_left=60) == pytest.approx(0.2)
    assert LR.endgame_empty_net_prob(cal, seconds_left=0) == 0.0
    assert LR.endgame_empty_net_prob({"empty_net_p": 0.4, "ramp_seconds": 0}, seconds_left=5) == 0.4
    assert LR.endgame_empty_net_prob(LR.LEGACY_LIVE_ENDGAME, seconds_left=300) == 0.0
    assert LR.endgame_empty_net_prob({"empty_net_p": "x"}, seconds_left=300) == 0.0
    assert LR.regulation_seconds_left(3, 300) == 300 and LR.regulation_seconds_left(1, 1200) == 3600
    assert LR.regulation_seconds_left(4, 200) == 0


class _Ev:
    def __init__(self, kind, period, t):
        self.kind, self.period, self.t = kind, period, t


def test_seconds_left_at_last_goal_reads_a_resumed_period_on_its_own_clock():
    # resumed at P3 05:00 (period_idx 2, the period runs 300 s): a goal 240 s in is 60 s from the end
    assert LR.seconds_left_at_last_goal([_Ev("goal", 3, 2 * 300 + 240)], start_period_idx=2, start_seconds=300,
                                        default=300) == pytest.approx(60)
    # resumed at P2 10:00: a P2 goal 100 s in leaves 500 + 1200; a later P3 goal 1000 s in leaves 200 -- the LAST
    events = [_Ev("goal", 2, 1 * 600 + 100), _Ev("goal", 3, 2 * 1200 + 1000), _Ev("shot", 3, 2 * 1200 + 1100)]
    assert LR.seconds_left_at_last_goal(events, start_period_idx=1, start_seconds=600, default=1800) == pytest.approx(200)
    # no regulation goal after the cutoff (an OT goal does not count): the cutoff's own time
    assert LR.seconds_left_at_last_goal([_Ev("goal", 4, 3700)], start_period_idx=2, start_seconds=300,
                                        default=300) == 300


def test_the_producers_timing_bins_sit_inside_the_time_that_was_left(pair):
    off, _on = pair                                                      # resumed at P3 05:00, 2-1
    reg = {int(k): v for k, v in off["regulation_margin_dist"].items()}
    bins = off["regulation_one_goal_seconds"]
    for sign in (1, -1):
        assert sum(bins[str(sign)].values()) == reg.get(sign, 0)          # every regulation-end +-1 sim, once
        assert all(0 <= int(k) <= 300 for k in bins[str(sign)])           # never more time than was left
    assert sum(bins["1"].values()) > 0 and "300" in bins["1"]             # untouched 2-1 leads carry the cutoff


def test_a_long_ramp_moves_fewer_sims_than_a_full_one():
    full = LR.resim_live_game(_features(), _state(), sims=80, base_seed=11, endgame=ON)
    ramped = LR.resim_live_game(_features(), _state(), sims=80, base_seed=11,
                                endgame={"empty_net_p": 1.0, "ramp_seconds": 3600.0})
    assert 0 < ramped["endgame"]["empty_net_goals"] < full["endgame"]["empty_net_goals"]
    assert ramped["regulation_margin_dist"] == full["regulation_margin_dist"]


def test_went_past_regulation_reads_the_engine_period_stamps():
    class E:
        def __init__(self, kind, period):
            self.kind, self.period = kind, period
    assert LR._went_past_regulation([E("goal", 3), E("shot", 4)]) is False
    assert LR._went_past_regulation([E("goal", 1), E("goal", 4)]) is True        # OT goal (period_idx 3 + 1)
    assert LR._went_past_regulation([E("shootout", 4)]) is True
    assert LR._went_past_regulation([]) is False


# --------------------------------------------------------------------------- the harness


def _row(reg, ot, final, period=3, remaining=300, date="2026-10-20", pk="1"):
    hist = dict(reg)
    for k, v in ot.items():
        hist[k] = hist.get(k, 0) + v
    return {"pk": pk, "date": date, "cutoff": "P3 05:00", "period": period, "remaining": remaining,
            "home_score": 1, "away_score": 0, "final_margin": final, "total_mean": 4.0,
            "hist": {str(k): v for k, v in hist.items()},
            "reg_hist": {str(k): v for k, v in reg.items()}, "ot_hist": {str(k): v for k, v in ot.items()}}


def test_the_harness_applies_the_producers_p_in_expectation(pair):
    off, on = pair
    row = {"period": 3, "remaining": 300, "hist": off["margin_dist"],
           "reg_hist": off["regulation_margin_dist"], "ot_hist": off["overtime_margin_dist"]}
    assert H.endgame_hist(row, None) == {int(k): float(v) for k, v in off["margin_dist"].items()}
    # at p = 1, ramp 0 the expectation IS the producer's draw: every eligible sim moves
    expected = {k: v for k, v in H.endgame_hist(row, ON).items() if v}
    assert expected == {int(k): float(v) for k, v in on["margin_dist"].items() if v}
    # with the timing bins, a ramp moves the same share the producer's own rule gives each bin
    row["reg_one_goal_secs"] = off["regulation_one_goal_seconds"]
    cal = {"empty_net_p": 0.5, "ramp_seconds": 600.0}
    expect = sum(0.5 * min(1.0, (float(k) + 2.5) / 600.0) * v
                 for side in off["regulation_one_goal_seconds"].values() for k, v in side.items())
    assert sum(H.endgame_moved(row, cal)) == pytest.approx(expect)


def test_with_endgame_moves_mass_and_the_total_and_drops_rows_without_splits():
    r = _row({1: 100, 2: 50}, {1: 10, -1: 10}, 2)
    (new,) = H.with_endgame([r, {k: v for k, v in r.items() if k != "reg_hist"}], {"empty_net_p": 0.5,
                                                                                   "ramp_seconds": 0})
    assert new["hist"][1] == pytest.approx(10 + 50) and new["hist"][2] == pytest.approx(100)
    assert new["total_mean"] == 4.0                                       # the margin only
    assert new["endgame_moved"] == pytest.approx(0.5 * 100 / 170, abs=1e-6)


def test_the_closed_form_fit_recovers_a_known_p():
    # 100 sims all end regulation at home +1. Home -1.5 (line +1.5) covers at (p*100 + 2) / 104; outcomes
    # cover 40 of 100 rows, so the Brier minimiser is p = (0.40 * 104 - 2) / 100 = 0.396.
    rows = [_row({1: 100}, {}, 2 if i < 40 else 1, period=2, remaining=600, pk=str(i)) for i in range(100)]
    fit = H.fit_endgame(rows)
    assert fit["empty_net_p"] == pytest.approx(0.40, abs=0.0101)
    assert fit["brier"] < fit["brier_at_p0"]


def test_walk_forward_fits_only_on_earlier_dates():
    rows = []
    for d in range(20):
        date = f"2026-10-{d + 1:02d}"
        for i in range(10):
            rows.append(_row({1: 100}, {}, 2 if i < 4 else 1, period=2, remaining=600, date=date, pk=f"{d}-{i}"))
    wf = H.walk_forward(rows, min_dates=14)
    assert wf["oos_dates"] == [f"2026-10-{d + 1:02d}" for d in range(14, 20)]
    assert wf["fits"]["2026-10-15"]["train_dates"] == 14
    assert wf["p_range"][0] == pytest.approx(0.40, abs=0.0101)


def test_lead_states_orient_to_the_leader():
    away_leads = _row({-1: 60, -2: 40}, {}, -2)
    away_leads.update(home_score=0, away_score=1)
    (s,) = H.lead_states([away_leads])
    assert s["lead"] == 1 and s["model_leader_by_2plus"] == 0.4 and s["obs_leader_by_2plus"] == 1.0

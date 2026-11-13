"""The NHL live re-sim's TOTAL (lane nhl-live-total-calibration, todo #773).

The 2026-11-11 cutoff replay measured the live total running HIGH early (+0.81 goals at puck drop, +0.34 at P2
10:00) and about right to low inside the last minutes. Two corrections were measured on the same replayed
states: lowering the ENGINE's goal rate (`goal_scale`) fixed the total but moved the margin and the moneyline
(slightly worse); THINNING THE TOTAL ONLY (`total_keep`: each regular-play goal after the live state kept with
probability q, goals in the last `total_keep_late_seconds` spared) fixed it as well and leaves the margin and
the moneyline exactly as they were. Production runs the thinning, with the end-game's empty-net goals counted in
the total. These pin, reachability first (model_engine_standard 4.3):
  - REACHABILITY: through the REAL producer and `build_live_lens_snapshot`, the published total moves on vs off,
    the lane says which, and the margin and the moneyline DO NOT move;
  - OFF IS TODAY: legacy publishes the raw engine total, the end-game out of it, and env off is legacy;
  - the thinning: only regular-play goals, never the late window or OT/SO goals, no draw at all at keep 1;
  - the per-sim records account for every goal, and the harness applies (keep, window, end-game) EXACTLY as
    the producer does where the producer is deterministic;
  - the engine-level `goal_scale` (the replay's knob) does reach the engine, and nonsense values are refused;
  - the harness's CRPS is the textbook one, and every fit (scale, keep) trains only on earlier dates.
"""
from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

from syndicate.features.nhl import live_resim as LR
from tests.test_nhl_live_resim import _StubFeatures

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backtest_nhl_live_puckline.py"
_spec = importlib.util.spec_from_file_location("backtest_nhl_live_puckline_total", _PATH)
H = importlib.util.module_from_spec(_spec)
sys.modules["backtest_nhl_live_puckline_total"] = H
_spec.loader.exec_module(H)

DATE = "2026-10-08"
PK = "2026020123"
HOME, AWAY = "Toronto Maple Leafs", "Ottawa Senators"
EN_ALL = {"empty_net_p": 1.0, "ramp_seconds": 0.0}          # every eligible sim moves: the clearest check
ON = {"goal_scale": 1.0, "total_keep": 0.7, "total_keep_late_seconds": 300.0, "count_endgame_in_total": True}


def _state(period=1, clock=1200, home=0, away=0):
    return LR.NhlLiveGameState(game_pk=PK, home_name=HOME, away_name=AWAY, home_score=home, away_score=away,
                               period=period, clock_seconds=clock, as_of="test")


def _features():
    return _StubFeatures(PK, HOME, AWAY)


def _score_row(period=1, remaining="20:00", secs=1200, home=0, away=0):
    return {
        "id": int(PK), "gameState": "LIVE", "periodDescriptor": {"number": period, "periodType": "REG"},
        "clock": {"timeRemaining": remaining, "secondsRemaining": secs, "inIntermission": False},
        "homeTeam": {"id": 10, "name": {"default": HOME}, "score": home},
        "awayTeam": {"id": 9, "name": {"default": AWAY}, "score": away},
    }


def _lane(monkeypatch, scoring):
    monkeypatch.setattr(LR, "NHL_LIVE_SCORING_CALIBRATION", dict(scoring))
    monkeypatch.delenv(LR.LIVE_SCORING_ENV, raising=False)
    monkeypatch.delenv(LR.LIVE_ENDGAME_ENV, raising=False)
    snap = LR.build_live_lens_snapshot(DATE, sims=60, score_rows=[_score_row()], slate_features=[_features()])
    (lane,) = snap["games"][0]["gameLens"]
    assert lane["source"] == LR.LIVE_RESIM_LENS_SOURCE
    return lane


def _mean(hist):
    return sum(int(k) * v for k, v in hist.items()) / sum(hist.values())


# --- the producer --------------------------------------------------------------------------------------------

def test_reachability_the_total_moves_and_the_margin_and_moneyline_do_not(monkeypatch):
    off = _lane(monkeypatch, LR.LEGACY_LIVE_SCORING)
    on = _lane(monkeypatch, ON)
    assert off["liveScoring"] == {"goal_scale": 1.0, "total_keep": 1.0, "total_keep_late_seconds": 0.0,
                                  "endgame_in_total": False, "calibration": "off"}
    assert on["liveScoring"] == {"goal_scale": 1.0, "total_keep": 0.7, "total_keep_late_seconds": 300.0,
                                 "endgame_in_total": True, "calibration": "on"}
    assert on["projection"]["total"] < off["projection"]["total"] - 0.5      # puck drop: ~7 goals thinned 0.7
    assert on["projection"]["displayMarginDist"] == off["projection"]["displayMarginDist"]
    assert on["modelHomeWinProb"] == off["modelHomeWinProb"]
    assert on["projection"]["homeMargin"] == off["projection"]["homeMargin"]


def test_the_shipped_calibration_is_the_replay_fit():
    # findings_2026-11-13_nhl_live_total_calibration.md: full-sample fit on 301 games / 43 dates
    assert LR.NHL_LIVE_SCORING_CALIBRATION == {"goal_scale": 1.0, "total_keep": 0.85,
                                               "total_keep_late_seconds": 240.0, "count_endgame_in_total": True}


def test_off_is_todays_total_and_the_env_switch_is_legacy(monkeypatch):
    monkeypatch.setenv(LR.LIVE_SCORING_ENV, "off")
    assert LR.live_scoring_calibration() == LR.LEGACY_LIVE_SCORING
    via_env = LR.resim_live_game(_features(), _state(3, 300, 2, 1), sims=60, base_seed=9, endgame=EN_ALL)
    explicit = LR.resim_live_game(_features(), _state(3, 300, 2, 1), sims=60, base_seed=9, endgame=EN_ALL,
                                  scoring=LR.LEGACY_LIVE_SCORING)
    assert via_env == explicit
    assert via_env["endgame"]["empty_net_goals"] > 0                     # the branch under test ran
    assert via_env["total_dist"] == via_env["raw_total_dist"]            # today's: raw, end-game out
    assert via_env["total_mean"] == pytest.approx(_mean(via_env["raw_total_dist"]), abs=1e-12)
    monkeypatch.delenv(LR.LIVE_SCORING_ENV)
    assert LR.live_scoring_calibration() == LR.NHL_LIVE_SCORING_CALIBRATION


def test_thinning_never_touches_the_engine_the_margin_or_the_endgame():
    st = _state(2, 600, 1, 1)
    base = dict(goal_scale=1.0, total_keep_late_seconds=300.0, count_endgame_in_total=True)
    one = LR.resim_live_game(_features(), st, sims=80, base_seed=4, endgame=EN_ALL, scoring=dict(base, total_keep=1.0))
    low = LR.resim_live_game(_features(), st, sims=80, base_seed=4, endgame=EN_ALL, scoring=dict(base, total_keep=0.6))
    for key in ("raw_total_dist", "margin_dist", "regulation_margin_dist", "overtime_margin_dist",
                "home_win_prob", "home_margin_mean", "regulation_one_goal_seconds", "endgame"):
        assert one[key] == low[key], key
    assert low["total_mean"] < one["total_mean"] - 0.3


def test_the_endgame_goals_are_in_the_total_exactly_when_asked():
    st = _state(3, 300, 2, 1)
    out = LR.resim_live_game(_features(), st, sims=60, base_seed=9, endgame=EN_ALL,
                             scoring={"goal_scale": 1.0, "count_endgame_in_total": False})
    inn = LR.resim_live_game(_features(), st, sims=60, base_seed=9, endgame=EN_ALL,
                             scoring={"goal_scale": 1.0, "count_endgame_in_total": True})
    assert out["raw_total_dist"] == inn["raw_total_dist"] and out["margin_dist"] == inn["margin_dist"]
    goals = inn["endgame"]["empty_net_goals"]
    assert goals > 0
    s = lambda h: sum(int(k) * v for k, v in h.items())
    assert s(inn["total_dist"]) == s(inn["raw_total_dist"]) + goals     # +1 per empty-net goal, nothing else
    reg = {int(k): v for k, v in inn["regulation_margin_dist"].items()}
    binned = sum(v for bins in inn["regulation_one_goal_totals"].values() for v in bins.values())
    assert binned == reg.get(1, 0) + reg.get(-1, 0)


def test_thin_total_spares_the_late_window_and_draws_nothing_at_keep_one():
    rng = random.Random(1)
    state = rng.getstate()
    assert LR.thin_total(9, [3000.0, 1000.0, 200.0], 1.0, 300.0, rng) == 9
    assert rng.getstate() == state                                       # keep 1: the stream is untouched
    # keep ~0 drops every regular-play goal (left > 300 s), spares the late one and anything unrecorded (OT/SO)
    assert LR.thin_total(9, [3000.0, 1000.0, 200.0], 1e-12, 300.0, random.Random(2)) == 7
    assert LR.thin_total(9, [3000.0, 1000.0, 200.0], 1e-12, 0.0, random.Random(2)) == 6
    assert LR.thin_total(9, [], 1e-12, 0.0, random.Random(2)) == 9


def test_the_per_sim_records_account_for_every_goal():
    for period, clock, h, a in ((1, 1200, 0, 0), (2, 600, 1, 1), (3, 300, 2, 1)):
        res = LR.resim_live_game(_features(), _state(period, clock, h, a), sims=60, base_seed=5, endgame=EN_ALL,
                                 scoring=LR.LEGACY_LIVE_SCORING, record_sims=True)
        assert len(res["sim_records"]) == 60
        assert sorted(r[0] for r in res["sim_records"]) == sorted(
            int(k) for k, v in res["raw_total_dist"].items() for _ in range(v))
        for raw, en_secs, lefts in res["sim_records"]:
            assert raw - (h + a) - len(lefts) >= 0                       # the rest are OT / shootout goals
            assert all(0.0 <= s <= LR.regulation_seconds_left(period, clock) for s in lefts)
            if en_secs >= 0:                                             # ended IN regulation: no OT/SO goal,
                assert raw == (h + a) + len(lefts)                       # so every goal is a recorded one
                assert en_secs == (min(lefts) if lefts else float(LR.regulation_seconds_left(period, clock)))
        eligible = sum(1 for _r, en, _l in res["sim_records"] if en >= 0)
        reg = {int(k): v for k, v in res["regulation_margin_dist"].items()}
        assert eligible == reg.get(1, 0) + reg.get(-1, 0)
        assert sum(len(l) for _r, _e, l in res["sim_records"]) > 0       # goals were scored and recorded
    assert "sim_records" not in LR.resim_live_game(_features(), _state(), sims=5, base_seed=5)


def test_the_engine_scale_reaches_both_teams_rates(monkeypatch):
    """The engine receives BOTH teams' `goals_per_60` multiplied by the scale, and nothing else changed."""
    from syndicate.features.nhl.sim_engine.hockeysim import runtime

    seen = []
    real = runtime.run_hockeysim_game_from_state

    def spy(home, away, rh, ra, rates, **kw):
        seen.append(rates)
        return real(home, away, rh, ra, rates, **kw)

    monkeypatch.setattr(runtime, "run_hockeysim_game_from_state", spy)
    feats = _features()
    LR.resim_live_game(feats, _state(), sims=2, base_seed=5, scoring={"goal_scale": 0.6})
    LR.resim_live_game(feats, _state(), sims=2, base_seed=5, scoring={"goal_scale": 1.0})
    low, one = seen[0], seen[-1]
    assert low.home.goals_per_60 == pytest.approx(0.6 * one.home.goals_per_60, abs=1e-12)
    assert low.away.goals_per_60 == pytest.approx(0.6 * one.away.goals_per_60, abs=1e-12)
    assert (low.home.shots_per_60, low.away.shots_per_60) == (one.home.shots_per_60, one.away.shots_per_60)
    assert one.home.goals_per_60 == float(feats.home.goals_per_60)      # 1.0 is today's rate, untouched


def test_the_engine_scale_reaches_the_engine():
    """`goal_scale` is the REPLAY's knob (production keeps 1.0): it must move the engine's own totals."""
    one = LR.resim_live_game(_features(), _state(), sims=80, base_seed=5, endgame=LR.LEGACY_LIVE_ENDGAME,
                             scoring={"goal_scale": 1.0})
    low = LR.resim_live_game(_features(), _state(), sims=80, base_seed=5, endgame=LR.LEGACY_LIVE_ENDGAME,
                             scoring={"goal_scale": 0.6})
    assert _mean(low["raw_total_dist"]) < _mean(one["raw_total_dist"]) - 0.5
    assert low["margin_dist"] != one["margin_dist"]                      # unlike the thinning, it moves the margin


@pytest.mark.parametrize("bad", [3.0, 0.1, "abc", None, float("nan")])
def test_nonsense_values_are_refused_not_run(bad):
    assert LR.scoring_goal_scale({"goal_scale": bad}) == 1.0
    assert LR.scoring_total_keep({"total_keep": bad}) == 1.0
    assert LR.scoring_goal_scale({}) == 1.0 and LR.scoring_total_keep({}) == 1.0
    assert LR.scoring_goal_scale({"goal_scale": 0.9}) == 0.9 and LR.scoring_total_keep({"total_keep": 0.85}) == 0.85
    assert LR.scoring_late_seconds({"total_keep_late_seconds": 5000}) == 1200.0
    assert LR.scoring_late_seconds({"total_keep_late_seconds": -3}) == 0.0
    assert LR.scoring_late_seconds({"total_keep_late_seconds": "x"}) == 0.0


# --- the harness ---------------------------------------------------------------------------------------------

def _rec_row(period, clock, h, a, scoring=None, seed=9, sims=60):
    res = LR.resim_live_game(_features(), _state(period, clock, h, a), sims=sims, base_seed=seed, endgame=EN_ALL,
                             scoring=scoring or {"goal_scale": 1.0, "count_endgame_in_total": True}, record_sims=True)
    row = {"period": period, "home_score": h, "away_score": a, "sims": res["sim_records"],
           "total_hist": res["raw_total_dist"], "total_one_goal_secs": res["regulation_one_goal_totals"]}
    return row, res


def test_the_harness_applies_the_endgame_to_the_total_as_the_producer_does():
    """At keep 1 and p = 1 (ramp 0) the producer is deterministic given the engine: the apply must equal it,
    from the per-sim records and from the older binned rows alike."""
    for period, clock, h, a in ((3, 300, 2, 1), (2, 600, 1, 1), (4, 200, 2, 2)):
        row, res = _rec_row(period, clock, h, a)
        want = {int(k): float(v) for k, v in res["total_dist"].items()}
        assert H.total_hist(row, EN_ALL) == want
        assert H.total_hist({k: v for k, v in row.items() if k != "sims"}, EN_ALL) == want
        assert H.total_hist(row, None) == {int(k): float(v) for k, v in res["raw_total_dist"].items()}


def test_the_harness_thinning_is_the_binomial_on_regular_play_goals_only():
    row = {"period": 1, "home_score": 0, "away_score": 0, "total_hist": {"5": 1},
           "sims": [[5, -1.0, [3000.0, 2000.0, 1000.0, 100.0]]]}               # 3 regular-play, 1 late, 1 OT/SO
    h = H.total_hist(row, None, keep=0.5, late_seconds=300.0)
    assert h == pytest.approx({2: 0.125, 3: 0.375, 4: 0.375, 5: 0.125})
    assert H.total_hist(row, None, keep=0.5, late_seconds=0.0) == pytest.approx(
        {1: 1 / 16, 2: 4 / 16, 3: 6 / 16, 4: 4 / 16, 5: 1 / 16})
    with pytest.raises(ValueError):
        H.total_hist({k: v for k, v in row.items() if k != "sims"}, None, keep=0.9)


def test_crps_is_the_ranked_probability_score():
    assert H.crps_discrete({5: 1.0}, 5) == 0.0
    assert H.crps_discrete({0: 1.0, 1: 1.0}, 0) == pytest.approx(0.25)
    assert H.crps_discrete({0: 1.0, 1: 1.0}, 1) == pytest.approx(0.25)
    assert H.crps_discrete({3: 1.0}, 5) == pytest.approx(2.0)            # off by two: two unit steps wrong
    assert H.crps_discrete({4: 1.0, 5: 1.0, 6: 1.0}, 5) < H.crps_discrete({6: 1.0, 7: 1.0, 8: 1.0}, 5)


def _keep_rows(final_by_date):
    """Rows whose every sim scores 8 regular-play goals (and nothing else) from 0-0; each date's finals are
    `final_by_date[date]`, so keep ~ final / 8 fits that date."""
    rows = []
    for d_i, (date, final) in enumerate(sorted(final_by_date.items())):
        for g in range(3):
            rows.append({"pk": f"{d_i}{g}", "cutoff": "P1 20:00", "date": date, "period": 1, "remaining": 1200,
                         "home_score": 0, "away_score": 0, "hist": {"1": 1}, "final_total": final,
                         "total_hist": {"8": 20}, "sims": [[8, -1.0, [3000.0 - 300 * k for k in range(8)]]] * 20})
    return rows


def test_the_keep_fit_recovers_the_keep_the_outcomes_imply():
    f = H.fit_total_keep(_keep_rows({f"2026-10-{d:02d}": 6 for d in range(1, 5)}), None)
    assert f["rows"] == 12
    assert 0.72 <= f["keep"] <= 0.78                                     # 6 of 8 goals: keep ~0.75


def test_the_keep_walk_forward_trains_only_on_earlier_dates():
    finals = {f"2026-10-{d:02d}": 8 for d in range(1, 4)}
    finals.update({f"2026-10-{d:02d}": 5 for d in range(4, 7)})
    wf = H.walk_forward_total_keep(_keep_rows(finals), None, min_dates=3)
    assert wf["oos_dates"] == ["2026-10-04", "2026-10-05", "2026-10-06"]
    assert wf["fits"]["2026-10-04"]["keep"] == 1.0          # only the keep-everything days before it
    assert wf["fits"]["2026-10-06"]["keep"] < 1.0           # 10-04 and 10-05 have joined its training set


def _synthetic_runs(best_by_date, games_by_date=None):
    """Engine-scale runs at 1.0 / 0.9 / 0.8 whose histograms centre on the outcome at the named scale."""
    runs = {1.0: [], 0.9: [], 0.8: []}
    order = [1.0, 0.9, 0.8]
    for d_i, (date, best) in enumerate(sorted(best_by_date.items())):
        for g in range((games_by_date or {}).get(date, 4)):
            pk = f"{d_i}{g}"
            for s in order:
                off = abs(order.index(s) - order.index(best))
                final = 6
                runs[s].append({"pk": pk, "cutoff": "P1 20:00", "date": date, "period": 1, "remaining": 1200,
                                "hist": {"1": 1}, "final_total": final, "scoring": {"goal_scale": s},
                                "total_hist": {str(final + off - 1): 1, str(final + off): 2, str(final + off + 1): 1}})
    return runs


def test_the_scale_fit_picks_the_scale_that_matches_the_outcomes():
    f = H.fit_goal_scale(_synthetic_runs({f"2026-10-{d:02d}": 0.9 for d in range(1, 6)}), None)
    assert f["best_grid"] == 0.9 and f["rows"] == 20 and 0.8 <= f["s_star"] <= 1.0


def test_the_scale_walk_forward_trains_only_on_earlier_dates():
    # 10-02 has three times 10-01's games: were it in its own training set, it would win it
    runs = _synthetic_runs({"2026-10-01": 1.0, "2026-10-02": 0.8}, {"2026-10-01": 2, "2026-10-02": 6})
    wf = H.walk_forward_goal_scale(runs, None, min_dates=1)
    assert wf["oos_dates"] == ["2026-10-02"]
    assert wf["fits"]["2026-10-02"] == 1.0
    assert H.fit_goal_scale(runs, None)["best_grid"] == 0.8               # the full sample does pick 0.8


def test_a_run_labelled_with_the_wrong_scale_is_refused(tmp_path):
    runs = _synthetic_runs({"2026-10-01": 0.9})
    d = tmp_path / "run"
    d.mkdir()
    (d / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in runs[0.9]), encoding="utf-8")
    assert len(H.load_scale_runs(f"0.9={d}")[0.9]) == 4
    with pytest.raises(ValueError):
        H.load_scale_runs(f"0.85={d}")


def test_the_replayed_row_carries_what_the_total_grade_needs():
    game = {"pk": PK, "home": HOME, "away": AWAY, "final_home": 3, "final_away": 2, "last_period_type": "REG",
            "goals": [(1, 100, 1, 0, "REG"), (2, 200, 1, 1, "REG"), (2, 900, 2, 1, "REG"), (3, 1100, 2, 2, "REG"),
                      (3, 1190, 3, 2, "REG")]}
    rows = H.replay_game(_features(), game, sims=12, endgame=LR.LEGACY_LIVE_ENDGAME,
                         scoring={"goal_scale": 0.9, "count_endgame_in_total": False})
    for r in rows:
        assert "refused" not in r, r
        assert r["final_total"] == 5
        assert sum(r["total_hist"].values()) == 12 == len(r["sims"])
        assert r["scoring"]["goal_scale"] == 0.9

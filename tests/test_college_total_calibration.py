"""#816 (lane ncaab-total-overprojection; user 2026-11-16 "Spread + level", after FAMU @ UTEP went 125 against an over
136.5 the board flagged): every college full-game TOTAL line's P(over), pregame and live, is the line's market
probability plus a fitted LEVEL plus a fitted share of the model's disagreement with the market:

    logit p = logit p_mkt + a + c * (logit p_raw - logit p_mkt)

Reachability first (`off != on`): the same NCAAB totals row through the live join with a fit in force, then with the
switch off; the same through the ledger and the pregame `_served`. Then the fit, its file and the daily refit step.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.college_basketball import total_prob_calibration as tpc
from syndicate.features.shared import college_game_projections as cgp
from syndicate.features.shared import live_gameline_join as lgj
from syndicate.features.shared.live_gameline_join import (
    agresti_coull_point,
    attach_live_gamelines,
    build_live_gameline_index,
    college_live_total_calibration,
    price_distribution_market,
)
from syndicate.features.shared.live_gameline_ledger import build_records

LANE_AT = datetime(2026, 11, 16, 20, 38, 0, tzinfo=timezone.utc)
HOME, AWAY = "UTEP Miners", "Florida A&M Rattlers"
DIST = {"130": 30, "134": 30, "138": 80, "144": 60}       # P(over 136.5) = 140 / 200 = 0.70 raw
LINE = 136.5
MARKET = 0.497
CAL = tpc.TotalCalibration(league="ncaab", phase="live", as_of=dt.date(2026, 11, 15), a=-0.49, c=0.21,
                           var_a=0.01, var_c=0.004, cov_ac=0.0, games=130.0, source="total_prob_calibration_2027_asof_20261115.json")


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.delenv(tpc.ENV_SWITCH, raising=False)
    monkeypatch.delenv("SYNDICATE_LIVE_TOTALS_PROB_SCALE", raising=False)
    monkeypatch.delenv("SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAB", raising=False)
    tpc._LISTING.clear()
    tpc._PARSED.clear()


def _logit(p):
    return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def _snapshot():
    lane = {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.9, "simsRun": 200,
            "liveStateAsOf": LANE_AT.isoformat(),
            "projection": {"total": 137.2, "homeMargin": 33.0, "totalRunsDist": dict(DIST), "marginDist": {"30": 100, "35": 100}}}
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row(market="totals", segment="full", market_prob=MARKET):
    sides = ["over", "under"] if market == "totals" else ["home", "away"]
    return {"kind": "game", "market": market, "segment": segment, "line": LINE, "sides": sides,
            "away_team": AWAY, "home_team": HOME, "age_seconds": 20.0, "updated_at": LANE_AT.isoformat(),
            "game": {"state": "live"}, "projection": {"market_fair_prob_over": market_prob}}


def _attach(rows, sport="ncaab"):
    index = build_live_gameline_index(_snapshot(), sources=("live_resim",), sport=sport)
    return attach_live_gamelines(rows, index, sport=sport, now=LANE_AT + timedelta(seconds=10))


def _with_fit(monkeypatch, cal=CAL):
    seen = []

    def _lookup(league, phase, game_date, **kw):
        seen.append((league, phase, game_date))
        return cal if tpc.enabled() else None

    monkeypatch.setattr(tpc, "calibration_for", _lookup)
    return seen


# --------------------------------------------------------------------------------------------- reachability

def test_off_is_not_on_through_the_live_join(monkeypatch):
    """FAMU @ UTEP's 2nd-half row: the engine says 0.70 at 136.5 against a 0.497 market; the fit pulls it under."""
    seen = _with_fit(monkeypatch)
    on, off = [_row()], [_row()]
    _attach(on)
    monkeypatch.setenv(tpc.ENV_SWITCH, "off")
    _attach(off)
    lg_on, lg_off = on[0]["live_gameline"], off[0]["live_gameline"]
    engine = agresti_coull_point(0.70, 200)
    expected = _sig(_logit(MARKET) + CAL.a + CAL.c * (_logit(engine) - _logit(MARKET)))
    assert lg_off["model_prob"] == pytest.approx(engine, abs=1e-9) and lg_off["total_calibration"] is None
    assert lg_on["model_prob"] == pytest.approx(expected, abs=1e-9)
    assert lg_on["model_prob_uncalibrated"] == pytest.approx(engine, abs=1e-9)
    assert lg_on["total_calibration"]["a"] == CAL.a and lg_on["total_calibration"]["c"] == CAL.c
    assert lg_on["model_prob"] < MARKET < lg_off["model_prob"]                     # off != on, and across the market
    assert on[0]["projection"]["edge_vs_market_pct"] == pytest.approx((expected - MARKET) * 100, abs=0.06)
    assert seen and seen[0][:2] == ("ncaab", "live")


def test_the_ledger_carries_the_engine_number_and_the_stamp(monkeypatch):
    _with_fit(monkeypatch)
    rows = [_row()]
    _attach(rows)
    rec = next(r for r in build_records(rows, sport="ncaab", date_str="2026-11-16") if r.get("market") == "totals")
    assert rec["model_home_win_prob_uncalibrated"] == pytest.approx(agresti_coull_point(0.70, 200), abs=1e-9)
    assert rec["total_cal"]["phase"] == "live" and rec["total_cal"]["a"] == CAL.a
    assert rec["model_home_win_prob"] == pytest.approx(rows[0]["live_gameline"]["model_prob"], abs=1e-9)


@pytest.mark.parametrize("sport,market,segment", [("nba", "totals", "full"), ("ncaab", "spreads", "full"),
                                                  ("ncaab", "totals", "h1"), ("ncaaf", "totals", "full")])
def test_only_college_full_game_totals_are_calibrated(monkeypatch, sport, market, segment):
    seen = _with_fit(monkeypatch)
    assert college_live_total_calibration(market, segment, sport) is None
    assert seen == []


def test_college_full_game_totals_ask_for_the_live_fit_by_central_date(monkeypatch):
    seen = _with_fit(monkeypatch)
    assert college_live_total_calibration("totals", "full", "wncaab", "2026-11-17T01:00:00Z") is CAL
    assert seen == [("wncaab", "live", dt.date(2026, 11, 16))]               # 7 PM CST on the 16th


def test_a_broken_lookup_prices_raw(monkeypatch, capsys):
    def _boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(tpc, "calibration_for", _boom)
    assert college_live_total_calibration("totals", "full", "ncaab") is None
    assert "COLLEGE_TOTAL_CALIBRATION_ERROR RuntimeError" in capsys.readouterr().out


def test_the_precision_gate_reads_the_calibrated_error():
    """The calibrated error = the sim's carried through c, plus the fit's own; a fit with no uncertainty and c = 0 has
    none at all, and a level then clears the gate on its own -- which is why the fit's variance rides along."""
    tight = tpc.TotalCalibration(league="ncaab", phase="live", as_of=dt.date(2026, 11, 15), a=-0.49, c=0.0)
    loose = tpc.TotalCalibration(league="ncaab", phase="live", as_of=dt.date(2026, 11, 15), a=-0.49, c=0.0, var_a=0.25)
    kw = dict(dist=DIST, line=LINE, side="over", market="totals", market_prob=MARKET, sims=200, sport="ncaab")
    assert price_distribution_market(**kw, total_calibration=tight)["prob_std_err"] == pytest.approx(0.0, abs=1e-12)
    v = price_distribution_market(**kw, total_calibration=loose)
    p = v["model_prob"]
    assert v["prob_std_err"] == pytest.approx(p * (1 - p) * 0.5, rel=1e-6)
    assert v["priceable"] is False                                           # a 0.5-logit-sd level does not clear 2 sd


def test_without_a_calibration_the_pricer_is_unchanged():
    kw = dict(dist=DIST, line=LINE, side="over", market="totals", market_prob=MARKET, sims=200, sport="ncaab")
    a, b = price_distribution_market(**kw), price_distribution_market(**kw, total_calibration=None)
    assert a == b and a["total_calibration"] is None and a["model_prob_uncalibrated"] is None


# --------------------------------------------------------------------------------------------- pregame

PRE = tpc.TotalCalibration(league="ncaab", phase="pregame", as_of=dt.date(2026, 11, 15), a=-0.38, c=0.0, games=221.0)


def test_pregame_full_game_total_is_calibrated_and_off_is_raw(monkeypatch):
    monkeypatch.setattr(cgp, "_no_vig_over_probability", lambda row: 0.5)
    monkeypatch.setattr(tpc, "calibration_for", lambda league, phase, game_date, **kw: PRE if (phase == "pregame" and tpc.enabled()) else None)
    prob, meta = cgp._served(0.71, {}, "totals", league="ncaab", game_date="2026-11-16", segment="full")
    assert prob == pytest.approx(_sig(-0.38), abs=1e-9)                     # c = 0: the market plus the level
    assert meta["book_blend"] == "total_calibration" and meta["total_calibration"]["phase"] == "pregame"
    assert meta["p_model_raw"] == 0.71 and meta["p_book"] == 0.5
    monkeypatch.setenv(tpc.ENV_SWITCH, "off")
    prob_off, meta_off = cgp._served(0.71, {}, "totals", league="ncaab", game_date="2026-11-16", segment="full")
    assert prob_off == 0.71 and "no total calibration in force" in meta_off["book_blend"]


def test_pregame_segments_and_missing_prices_stay_raw(monkeypatch):
    monkeypatch.setattr(tpc, "calibration_for", lambda *a, **k: PRE)
    assert cgp._served(0.6, {}, "totals", league="ncaab", game_date="2026-11-16", segment="h1")[0] == 0.6
    monkeypatch.setattr(cgp, "_no_vig_over_probability", lambda row: None)
    prob, meta = cgp._served(0.6, {}, "totals", league="ncaab", game_date="2026-11-16", segment="full")
    assert prob == 0.6 and "no two-sided book price" in meta["book_blend"]
    assert cgp._served(0.6, {}, "totals")[1]["book_blend"] == "not applied: totals served raw"   # no league / date


# --------------------------------------------------------------------------------------------- the fit

def _synthetic(n, a, c, seed=7):
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        x, off = rng.uniform(-1.5, 1.5), rng.uniform(-0.6, 0.6)
        rows.append((x, off, 1.0 if rng.random() < _sig(off + a + c * x) else 0.0, 1.0))
    return rows


def test_the_fit_recovers_a_known_level_and_share():
    f = tpc.fit(_synthetic(20000, -0.40, 0.30))
    assert f["a"] == pytest.approx(-0.40, abs=0.05) and f["c"] == pytest.approx(0.30, abs=0.05)
    assert f["var_a"] > 0 and f["clamped"] == [] and f["games"] == 20000


def test_the_fit_clamps_an_extreme_level():
    f = tpc.fit([(0.0, 0.0, 0.0, 1.0)] * 400)
    assert f["a"] == tpc.A_RANGE[0] and f["clamped"] and f["clamped"][0].startswith("a ")


def test_walk_forward_scores_each_day_on_a_fit_of_the_days_before():
    by_date = {f"2026-11-{d:02d}": _synthetic(80, -0.4, 0.3, seed=d) for d in range(11, 16)}
    wf = tpc.walk_forward(by_date)
    assert [s["date"] for s in wf["steps"]] == ["2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"]
    assert wf["calibrated"] < wf["raw"]


def _write_fit(monkeypatch, tmp_path, *, live_games=300.0):
    monkeypatch.setattr(tpc, "calibration_path", lambda league, season, as_of: tmp_path / f"total_prob_calibration_{season}_asof_{as_of:%Y%m%d}.json")
    # Seeded by the day's NUMBER, never hash(day): str hashes are randomised per process, which made the walk-forward
    # gate (rightly) refuse on some seeds and the test order-dependent.
    monkeypatch.setattr(tpc, "pregame_fit_rows", lambda league, day: _synthetic(150, -0.6, 0.0, seed=int(day[-2:])))
    live = _synthetic(int(live_games / 5), -0.6, 0.3, seed=3)
    monkeypatch.setattr(tpc, "live_fit_rows", lambda league, day: live)
    return tpc.refresh("ncaab", today=dt.date(2026, 11, 17), floor=dt.date(2026, 11, 11), write=True)


def test_refresh_writes_the_file_the_lookup_reads(monkeypatch, tmp_path):
    payload = _write_fit(monkeypatch, tmp_path)
    assert payload["window"] == ["2026-11-11", "2026-11-16"] and payload["as_of"] == "2026-11-16"
    assert payload["phases"]["pregame"]["calibrated"] and payload["phases"]["live"]["calibrated"]
    got = tpc.calibration_for("ncaab", "live", dt.date(2026, 11, 17), directory=tmp_path)
    assert got is not None and got.as_of == dt.date(2026, 11, 16) and got.phase == "live"
    assert tpc.calibration_for("ncaab", "live", dt.date(2026, 11, 16), directory=tmp_path) is None   # strictly before
    monkeypatch.setenv(tpc.ENV_SWITCH, "off")
    assert tpc.calibration_for("ncaab", "live", dt.date(2026, 11, 17), directory=tmp_path) is None


def test_a_thin_phase_is_written_uncalibrated_and_served_raw(monkeypatch, tmp_path):
    payload = _write_fit(monkeypatch, tmp_path, live_games=5)
    assert payload["phases"]["live"]["calibrated"] is False and "graded games" in payload["phases"]["live"]["reason"]
    assert tpc.calibration_for("ncaab", "live", dt.date(2026, 11, 17), directory=tmp_path) is None
    assert tpc.calibration_for("ncaab", "pregame", dt.date(2026, 11, 17), directory=tmp_path) is not None


@pytest.mark.parametrize("wf,reason", [
    ({"games": 30.0, "market": 0.25, "raw": 0.27, "calibrated": 0.24}, "games < 40"),
    ({"games": 100.0, "market": 0.25, "raw": 0.24, "calibrated": 0.245}, "did not beat the raw"),
    ({"games": 100.0, "market": 0.25, "raw": 0.27, "calibrated": 0.26}, "worse than the market"),
    ({"games": 100.0, "market": 0.25, "raw": 0.27, "calibrated": 0.24}, None),
])
def test_the_walk_forward_verdict(wf, reason):
    got = tpc._walk_forward_verdict(wf)
    assert (got is None) if reason is None else (reason in got)


def test_a_phase_that_lost_its_walk_forward_is_written_uncalibrated(monkeypatch, tmp_path):
    """WNCAAB pregame on 11-17 (fleet): walk-forward 0.2608 against the market's 0.2500 -- fitted, recorded, not served."""
    monkeypatch.setattr(tpc, "walk_forward", lambda by_date, **kw: {"games": 100.0, "market": 0.25, "raw": 0.2658, "calibrated": 0.2608})
    payload = _write_fit(monkeypatch, tmp_path)
    entry = payload["phases"]["pregame"]
    assert entry["calibrated"] is False and "worse than the market" in entry["reason"] and "a" in entry
    assert tpc.calibration_for("ncaab", "pregame", dt.date(2026, 11, 17), directory=tmp_path) is None


def test_an_unreadable_file_serves_raw(tmp_path):
    (tmp_path / "total_prob_calibration_2027_asof_20261116.json").write_text("{not json", encoding="utf-8")
    assert tpc.calibration_for("ncaab", "live", dt.date(2026, 11, 17), directory=tmp_path) is None


def test_live_fit_rows_read_the_engine_number_never_their_own_output(monkeypatch):
    from syndicate.features.shared import live_gameline_ledger as led

    recs = [
        {"market": "totals", "segment": "full", "line": 136.5, "home_team": HOME, "away_team": AWAY,
         "model_home_win_prob": 0.40, "model_home_win_prob_uncalibrated": 0.70, "total_cal": {"a": -0.5},
         "market_fair_prob_over": 0.5},
        {"market": "totals", "segment": "full", "line": 136.5, "home_team": HOME, "away_team": AWAY,
         "model_home_win_prob": 0.40, "total_cal": {"a": -0.5}, "market_fair_prob_over": 0.5},          # skipped
        {"market": "totals", "segment": "full", "line": 130.5, "home_team": HOME, "away_team": AWAY,
         "model_home_win_prob": 0.60, "market_fair_prob_over": 0.5},
        {"market": "spreads", "segment": "full", "line": 20.5, "home_team": HOME, "away_team": AWAY,
         "model_home_win_prob": 0.60, "market_fair_prob_over": 0.5},                                      # not a total
    ]
    monkeypatch.setattr(led, "read_records", lambda path: recs)
    from syndicate.features.ncaab import live_resim as lr

    key = (lr._join_key("ncaab", HOME), lr._join_key("ncaab", AWAY))
    monkeypatch.setattr(tpc, "_finals", lambda league, day: ({key: 125.0}, {}))
    rows = tpc.live_fit_rows("ncaab", "2026-11-16")
    assert len(rows) == 2 and all(w == pytest.approx(0.5) for *_, w in rows)
    assert rows[0][0] == pytest.approx(_logit(0.70)) and rows[0][2] == 0.0      # 125 < 136.5: the under
    assert rows[1][0] == pytest.approx(_logit(0.60)) and rows[1][2] == 0.0      # 125 < 130.5


# --------------------------------------------------------------------------------------------- the daily refit

def test_the_refit_step_runs_once_a_day_after_11z(monkeypatch, tmp_path):
    import importlib.util
    import sys
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("build_college_pregame_sims_816",
                                                  Path(__file__).resolve().parents[1] / "scripts" / "build_college_pregame_sims.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(tpc, "calibration_path", lambda league, season, as_of: tmp_path / f"t_{league}_{as_of:%Y%m%d}.json")
    calls = []
    refit = lambda league, today: calls.append((league, today)) or (tmp_path / f"t_{league}_{today - dt.timedelta(days=1):%Y%m%d}.json").write_text("{}")
    early = datetime(2026, 11, 17, 10, 59, tzinfo=timezone.utc)
    later = datetime(2026, 11, 17, 11, 5, tzinfo=timezone.utc)
    assert mod.refresh_total_calibrations(["ncaab"], early, refit=refit) == {"ncaab": "before_11z"}
    assert mod.refresh_total_calibrations(["ncaab", "wncaab"], later, refit=refit) == {"ncaab": "refitted", "wncaab": "refitted"}
    assert mod.refresh_total_calibrations(["ncaab"], later, refit=refit) == {"ncaab": "already_today"}
    assert calls == [("ncaab", dt.date(2026, 11, 17)), ("wncaab", dt.date(2026, 11, 17))]


def test_a_failed_refit_never_stops_the_sims(monkeypatch, tmp_path, capsys):
    import importlib.util
    import sys
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("build_college_pregame_sims_816b",
                                                  Path(__file__).resolve().parents[1] / "scripts" / "build_college_pregame_sims.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(tpc, "calibration_path", lambda league, season, as_of: tmp_path / "never.json")

    def _boom(league, today):
        raise ValueError("no ledgers")

    out = mod.refresh_total_calibrations(["ncaab"], datetime(2026, 11, 17, 12, tzinfo=timezone.utc), refit=_boom)
    assert out == {"ncaab": "failed"} and "FIT_FAILED league=ncaab ValueError" in capsys.readouterr().out

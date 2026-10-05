"""Score-adjusted team xG, game lines only (lane `nhl-game-lines-model`, user override 2026-10-05).

Fixtures are REAL (shared with the in-season team-xG test): production's prior `team_xg_latest.csv` (fleet copy),
the 2026-10-01 score feed, and PHI @ NJD 2026020009's play-by-play.
"""
from __future__ import annotations

import csv
import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import scripts.build_nhl_artifacts as producer
from syndicate.features.nhl import inseason_team_xg as M
from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyGameFeatures, HockeyTeamFeatures
from syndicate.features.nhl.sim_engine.hockeysim.projection import apply_projection

FX = Path(__file__).parent / "fixtures" / "nhl_inseason_team_xg"
PBP = json.loads((FX / "playbyplay_2026020009.json").read_text(encoding="utf-8"))


def test_unadjusted_sums_unchanged_and_score_walk_aligns():
    h, a, hx, ax = M.game_xg(PBP)
    h2, a2, hx2, ax2, hxa, axa = M.game_xg_scoreadj(PBP)
    assert (h, a) == (h2, a2) == ("NJD", "PHI")
    assert (hx, ax) == (hx2, ax2)                           # the season file's numbers are untouched
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X
    assert len(M.home_lead_before_shots(PBP)) == len(X.parse_play_by_play_shots(PBP))
    assert (hxa, axa) != (hx, ax)                           # the weights reach the sums
    flat = {d: 1.0 for d in range(-3, 4)}
    assert M.game_xg_scoreadj(PBP, flat)[4:] == pytest.approx((hx, ax))


def test_refresh_writes_the_adjusted_twin(tmp_path):
    root = tmp_path / "nhl_source"
    proc = root / "data" / "processed"
    proc.mkdir(parents=True)
    shutil.copy(FX / "team_xg_latest_fleet_2026-10-03.csv", proc / "team_xg_latest.csv")
    score = json.loads((FX / "score_2026-10-01.json").read_text(encoding="utf-8"))

    def fetch(url):
        if url.endswith("/score/2026-10-01"):
            return score
        if "/score/" in url:
            return {"games": []}
        return PBP if url.endswith("/gamecenter/2026020009/play-by-play") else None

    st = M.refresh_inseason_team_xg(root, today=date(2026, 10, 4), fetch=fetch, season_start=date(2026, 9, 30))
    assert st["wrote"] and st.get("scoreadj_written")
    plain = {r["abbr"]: r for r in csv.DictReader((proc / "team_xg_2026-2027.csv").open(encoding="utf-8"))}
    adj = {r["abbr"]: r for r in csv.DictReader((proc / "team_xg_scoreadj_2026-2027.csv").open(encoding="utf-8"))}
    assert set(plain) == set(adj)
    prior = {r["abbr"]: r for r in csv.DictReader((proc / "team_xg_latest.csv").open(encoding="utf-8"))}
    rf, ra = M.PRIOR_SCOREADJ_RATIO["BOS"]                  # BOS did not play: adjusted = prior x ratio
    assert float(adj["BOS"]["xgf60"]) == pytest.approx(float(prior["BOS"]["xgf60"]) * rf, abs=1e-4)
    assert float(adj["BOS"]["xga60"]) == pytest.approx(float(prior["BOS"]["xga60"]) * ra, abs=1e-4)


def _game(xgf_h, xga_h, xgf_a, xga_a) -> HockeyGameFeatures:
    home, away, _ = apply_projection(HockeyTeamFeatures(name="New Jersey Devils", abbrev="NJD", xgf_per_60=xgf_h, xga_per_60=xga_h),
                                     HockeyTeamFeatures(name="Philadelphia Flyers", abbrev="PHI", xgf_per_60=xgf_a, xga_per_60=xga_a))
    return HockeyGameFeatures(game_pk="2026020009", date="2026-10-05", home=home, away=away)


def _write_adj(proc: Path, rows):
    proc.mkdir(parents=True, exist_ok=True)
    with (proc / "team_xg_scoreadj_2026-2027.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["abbr", "xgf60", "xga60", "games"])
        for r in rows:
            w.writerow(r)


def test_identity_when_adjusted_equals_unadjusted(tmp_path):
    g = _game(3.2, 2.9, 2.8, 3.1)
    _write_adj(tmp_path / "data" / "processed", [("NJD", 3.2, 2.9, 1), ("PHI", 2.8, 3.1, 1)])
    out = producer._apply_scoreadj_xg([g], "2026-10-05", tmp_path)
    assert out[0].home.period_goal_lambdas == g.home.period_goal_lambdas
    assert out[0].away.period_goal_lambdas == g.away.period_goal_lambdas


def test_reachability_on_differs_from_off(tmp_path, monkeypatch):
    g = _game(3.2, 2.9, 2.8, 3.1)
    _write_adj(tmp_path / "data" / "processed", [("NJD", 3.3, 2.8, 1), ("PHI", 2.8, 3.1, 1)])
    on = producer._apply_scoreadj_xg([g], "2026-10-05", tmp_path)[0]
    assert sum(on.home.period_goal_lambdas) > sum(g.home.period_goal_lambdas)    # higher attack -> more home goals
    assert sum(on.away.period_goal_lambdas) < sum(g.away.period_goal_lambdas)    # better home defence
    assert on.home.goals_per_60 == g.home.goals_per_60                           # props' rate untouched
    monkeypatch.setenv(M.SCOREADJ_ENV, "off")
    off = producer._apply_scoreadj_xg([g], "2026-10-05", tmp_path)[0]
    assert off is g


def test_missing_team_or_file_keeps_unadjusted(tmp_path):
    g = _game(3.2, 2.9, 2.8, 3.1)
    assert producer._apply_scoreadj_xg([g], "2026-10-05", tmp_path)[0] is g          # no file
    _write_adj(tmp_path / "data" / "processed", [("NJD", 3.3, 2.8, 1)])               # PHI absent
    assert producer._apply_scoreadj_xg([g], "2026-10-05", tmp_path)[0] is g

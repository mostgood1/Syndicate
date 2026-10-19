"""Coherent shooting-foul model in the native basketball engine (lane basketball-scenario-calibration, round 2 R2-c',
pre-registered 13db6520): EventSimConfig.shooting_foul_model.

"legacy" (default) is today's loop. "coherent" defines the make probability on ALL attempts (de-netted from the
recorded prior, since real FGA exclude fouled misses), draws an and-one on a make and a fouled miss on a miss at
league rates x a team/shooter factor, and never counts a fouled miss as an FGA -- so the RECORDED 2P%/3P% land on the
priors whatever the foul rates are."""
from __future__ import annotations

import dataclasses
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from syndicate.features.basketball_engine import engine as E
from syndicate.features.shared import basketball_props_smart_sim as bpss


@pytest.fixture(autouse=True)
def _team_inputs_off(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NBA_TEAM_INPUTS", "0")


P2, P3 = 0.55, 0.36


def _team(p: str) -> pd.DataFrame:
    mins = [36, 35, 34, 33, 32, 24, 18, 14, 9, 5]
    n = len(mins)
    a3, a = 0.17, 0.40
    return pd.DataFrame({"player_name": [f"{p}{i}" for i in range(n)], "min": mins, "_sim_min": [float(m) for m in mins],
                         "_prior_fga_pm": [a] * n, "_prior_threes_att_pm": [a3] * n, "_prior_threes_pm": [a3 * P3] * n,
                         "_prior_fgm_pm": [a3 * P3 + (a - a3) * P2] * n, "_prior_fta_pm": [0.11] * n, "_prior_ftm_pm": [0.086] * n})


def _quarters():
    return [{"home_pts_mu": 28.0, "away_pts_mu": 27.0, "home_pts_sigma": 6.5, "away_pts_sigma": 6.5, "corr": 0.25} for _ in range(4)]


def _run(eng, n, **cfg):
    return [eng.simulate_pbp_game_boxscore(np.random.default_rng(s), _team("H"), _team("A"), cfg=eng.EventSimConfig(**cfg),
                                           target_home_points=None, target_away_points=None, quarters=_quarters()) for s in range(n)]


def _digest(games) -> str:
    h = hashlib.sha256()
    for g in games:
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    return h.hexdigest()


def _pcts(games):
    f2m = f2a = f3m = f3a = 0
    for hb, ab, _hq, _aq in games:
        for box in (hb, ab):
            for p in box["players"]:
                fga, fgm, tpa, tpm = (int(p.get(k) or 0) for k in ("fga", "fgm", "fg3a", "threes"))
                f2m += fgm - tpm; f2a += fga - tpa; f3m += tpm; f3a += tpa
    return f2m / f2a, f3m / f3a


def test_denet_inverts_the_recording():
    for p, b in ((0.5465, 0.2417), (0.3589, 0.0161), (0.6, 0.4)):
        q = E._sf_denet(p, b)
        assert abs(q / (1.0 - (1.0 - q) * b) - p) < 1e-12


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_default_is_legacy_and_matches_explicit_legacy(league):
    eng = bpss._engine_for_league_local(league)
    assert eng.EventSimConfig().shooting_foul_model == "legacy"
    assert _digest(_run(eng, 3)) == _digest(_run(eng, 3, shooting_foul_model="legacy"))


def test_coherent_is_reachable_and_records_the_priors():
    eng = bpss._engine_for_league_local("nba")
    on = _run(eng, 80, shooting_foul_model="coherent", fg2_from_two_point_split=True)
    assert _digest(on) != _digest(_run(eng, 3))
    p2, p3 = _pcts(on)
    # No target, so no EXACT scaling: the recorded rates should sit on the priors (sampling noise ~0.01 at 80 games).
    assert abs(p2 - P2) < 0.02 and abs(p3 - P3) < 0.02


def test_coherent_three_point_foul_trips_are_rare():
    eng = bpss._engine_for_league_local("nba")
    games = _run(eng, 60, shooting_foul_model="coherent", fg2_from_two_point_split=True, record_events=True)
    trips3 = sum(1 for hb, _ab, _hq, _aq in games for e in hb.get("events") or [] if e.get("type") == "FTA" and e.get("fta") == 3)
    trips2 = sum(1 for hb, _ab, _hq, _aq in games for e in hb.get("events") or [] if e.get("type") == "FTA" and e.get("fta") == 2 and not e.get("bonus"))
    assert trips2 > 5 * trips3

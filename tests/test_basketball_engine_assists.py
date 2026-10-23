"""Assisted makes in the native basketball engine (lane basketball-scenario-calibration, #5b, pre-registered be8a644b):
EventSimConfig.assisted_make_rate / assist_team_prior / assist_team_ref.

0.58 (default) is the old hard-coded constant, byte-identical. Real NBA 2025-26 FIT AST/FGM is 0.6368. The team
variant scales the league rate by the side's prior AST/FGM relative to assist_team_ref."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as bpss


@pytest.fixture(autouse=True)
def _team_inputs_off(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NBA_TEAM_INPUTS", "0")


def _team(p: str, ast_pm: float = 0.10) -> pd.DataFrame:
    mins = [36, 35, 34, 33, 32, 24, 18, 14, 9, 5]
    n = len(mins)
    return pd.DataFrame({"player_name": [f"{p}{i}" for i in range(n)], "min": mins, "_sim_min": [float(m) for m in mins],
                         "_prior_fga_pm": [0.40] * n, "_prior_threes_att_pm": [0.17] * n, "_prior_threes_pm": [0.0612] * n,
                         "_prior_fgm_pm": [0.188] * n, "_prior_fta_pm": [0.11] * n, "_prior_ftm_pm": [0.086] * n,
                         "_prior_ast_pm": [ast_pm] * n})


def _quarters():
    return [{"home_pts_mu": 28.0, "away_pts_mu": 27.0, "home_pts_sigma": 6.5, "away_pts_sigma": 6.5, "corr": 0.25} for _ in range(4)]


def _run(eng, n, home=None, away=None, **cfg):
    return [eng.simulate_pbp_game_boxscore(np.random.default_rng(s), home if home is not None else _team("H"),
                                           away if away is not None else _team("A"), cfg=eng.EventSimConfig(**cfg),
                                           target_home_points=112.0, target_away_points=108.0, quarters=_quarters()) for s in range(n)]


def _digest(games) -> str:
    h = hashlib.sha256()
    for g in games:
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    return h.hexdigest()


def _ratio(games, side: int = -1) -> float:
    ast = fgm = 0
    for g in games:
        boxes = (g[0], g[1]) if side < 0 else (g[side],)
        for box in boxes:
            for p in box["players"]:
                ast += int(p.get("ast") or 0); fgm += int(p.get("fgm") or 0)
    return ast / fgm


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_default_is_the_old_constant_and_byte_identical(league):
    eng = bpss._engine_for_league_local(league)
    cfg = eng.EventSimConfig()
    assert cfg.assisted_make_rate == 0.58 and cfg.assist_team_prior is False and cfg.assist_team_ref == 0.0
    assert _digest(_run(eng, 3)) == _digest(_run(eng, 3, assisted_make_rate=0.58))
    # The team variant without a ref is off.
    assert _digest(_run(eng, 3)) == _digest(_run(eng, 3, assist_team_prior=True))


def test_league_rate_is_reachable_and_lands():
    eng = bpss._engine_for_league_local("nba")
    on = _run(eng, 60, assisted_make_rate=0.6368)
    assert _digest(on) != _digest(_run(eng, 3))
    assert abs(_ratio(on) - 0.6368) < 0.02
    assert abs(_ratio(_run(eng, 60)) - 0.58) < 0.02


def test_team_prior_scales_each_side_by_its_own_ratio():
    eng = bpss._engine_for_league_local("nba")
    # Home passes more than the ref, away less: league ratio = 0.10 / 0.188 = 0.532.
    games = _run(eng, 80, home=_team("H", ast_pm=0.12), away=_team("A", ast_pm=0.08),
                 assisted_make_rate=0.6, assist_team_prior=True, assist_team_ref=0.10 / 0.188)
    h, a = _ratio(games, 0), _ratio(games, 1)
    assert abs(h - 0.6 * 1.2) < 0.03 and abs(a - 0.6 * 0.8) < 0.03

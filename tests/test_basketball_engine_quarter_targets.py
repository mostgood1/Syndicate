"""Per-quarter targets in the native basketball engine (lane basketball-scenario-calibration, round 2 R2-a,
pre-registered d0d30f21): EventSimConfig.quarter_targets_mode.

Production passes QuarterResultLocal DATACLASSES. The engine's reads used `getattr(qr, k, (qr or {}).get(k))`, whose
eagerly evaluated default raises on a dataclass, so the quarter mean shift and random environment never ran. "off"
keeps that exactly; "mean" reads the targets and applies the mean shift only; "full" adds the random environment."""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as bpss


@pytest.fixture(autouse=True)
def _team_inputs_off(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NBA_TEAM_INPUTS", "0")


def _team(p: str) -> pd.DataFrame:
    mins = [36, 35, 34, 33, 32, 24, 18, 14, 9, 5]
    n = len(mins)
    return pd.DataFrame({"player_name": [f"{p}{i}" for i in range(n)], "min": mins, "_sim_min": [float(m) for m in mins],
                         "_prior_fga_pm": [0.40] * n, "_prior_threes_att_pm": [0.17] * n, "_prior_threes_pm": [0.0612] * n,
                         "_prior_fgm_pm": [0.188] * n, "_prior_fta_pm": [0.11] * n, "_prior_ftm_pm": [0.086] * n})


def _dc_quarters(split, tot=230.0):
    """Production's shape: QuarterResultLocal dataclasses."""
    return [bpss.QuarterResultLocal(q=i + 1, home_pts_mu=tot / 2 * s, home_pts_sigma=6.5, away_pts_mu=tot / 2 * s,
                                    away_pts_sigma=6.5, corr=0.25) for i, s in enumerate(split)]


def _run(eng, split, n, **cfg):
    out = []
    for seed in range(n):
        out.append(eng.simulate_pbp_game_boxscore(np.random.default_rng(seed), _team("H"), _team("A"), cfg=eng.EventSimConfig(**cfg),
                                                  target_home_points=115.0, target_away_points=115.0, quarters=_dc_quarters(split)))
    return out


def _digest(games) -> str:
    h = hashlib.sha256()
    for g in games:
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    return h.hexdigest()


def _q(games):
    return np.mean([np.array(hq[:4]) + np.array(aq[:4]) for _hb, _ab, hq, aq in games], axis=0)


SPLIT_A = [0.245, 0.245, 0.255, 0.255]
SPLIT_B = [0.270, 0.250, 0.250, 0.230]


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_default_is_off_and_matches_explicit_off(league):
    eng = bpss._engine_for_league_local(league)
    assert eng.EventSimConfig().quarter_targets_mode == "off"
    assert _digest(_run(eng, SPLIT_A, 3)) == _digest(_run(eng, SPLIT_A, 3, quarter_targets_mode="off"))


def test_off_ignores_dataclass_quarter_targets_as_production_does():
    # The documented defect, pinned: with production's dataclass quarters, "off" output does not depend on the split.
    eng = bpss._engine_for_league_local("nba")
    assert _digest(_run(eng, SPLIT_A, 3)) == _digest(_run(eng, SPLIT_B, 3))


def test_mean_mode_is_reachable_and_follows_the_split_without_extra_rng():
    eng = bpss._engine_for_league_local("nba")
    a = _run(eng, SPLIT_A, 60, quarter_targets_mode="mean")
    b = _run(eng, SPLIT_B, 60, quarter_targets_mode="mean")
    assert _digest(a) != _digest(_run(eng, SPLIT_A, 3))  # reachable vs off
    qa, qb = _q(a), _q(b)
    assert qb[0] > qa[0] + 1.0 and qb[3] < qa[3] - 1.0   # Q1 up, Q4 down, as the targets say


def test_full_mode_adds_the_random_environment():
    eng = bpss._engine_for_league_local("nba")
    assert _digest(_run(eng, SPLIT_A, 4, quarter_targets_mode="full")) != _digest(_run(eng, SPLIT_A, 4, quarter_targets_mode="mean"))


def test_unknown_mode_is_off():
    eng = bpss._engine_for_league_local("nba")
    assert _digest(_run(eng, SPLIT_A, 3, quarter_targets_mode="bogus")) == _digest(_run(eng, SPLIT_A, 3))

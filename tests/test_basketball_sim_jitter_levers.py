"""Phase 2 #1 levers (lane basketball-scenario-calibration): EventSimConfig.possession_alternation and env_sd_scale.
Defaults equal the values that were hardcoded (unset == explicit defaults, same seeded output); moving either lever
changes the output (off != on). Both engine copies (NBA, WNBA). The HEAD-vs-patched sha256 proof is recorded in
.syndicate/findings_2026-10-06_basketball_scenario_calibration.md."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
QUARTERS = [{"home_pts_mu": 28.5, "away_pts_mu": 27.5, "home_pts_sigma": 6.5, "away_pts_sigma": 6.3, "corr": 0.25},
            {"home_pts_mu": 28.0, "away_pts_mu": 27.8, "home_pts_sigma": 6.4, "away_pts_sigma": 6.4, "corr": 0.25},
            {"home_pts_mu": 28.6, "away_pts_mu": 28.0, "home_pts_sigma": 6.6, "away_pts_sigma": 6.5, "corr": 0.25},
            {"home_pts_mu": 27.0, "away_pts_mu": 26.5, "home_pts_sigma": 6.9, "away_pts_sigma": 6.8, "corr": 0.3}]


def _events(pkg: str):
    src = VENDOR / f"{pkg}_repo" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return __import__(f"{pkg}.sim.events", fromlist=["x"])


def _team(p):
    return pd.DataFrame({"player_name": [f"{p}{i}" for i in range(10)], "min": [34, 33, 32, 31, 30, 25, 20, 15, 10, 10]})


def _digest(ev, **kw) -> str:
    h = hashlib.sha256()
    for seed in range(6):
        out = ev.simulate_pbp_game_boxscore(np.random.default_rng(seed), _team("H"), _team("A"), cfg=ev.EventSimConfig(**kw),
                                            target_home_points=112.6, target_away_points=109.8, quarters=QUARTERS)
        h.update(json.dumps(out, sort_keys=True, default=str).encode())
    return h.hexdigest()


@pytest.mark.parametrize("pkg", ["nba_betting", "wnba_betting"])
def test_defaults_are_the_old_hardcoded_values_and_unset_equals_explicit(pkg):
    ev = _events(pkg)
    cfg = ev.EventSimConfig()
    assert cfg.possession_alternation == 0.85 and cfg.env_sd_scale == 0.65
    assert _digest(ev) == _digest(ev, possession_alternation=0.85, env_sd_scale=0.65)


@pytest.mark.parametrize("pkg", ["nba_betting", "wnba_betting"])
def test_each_lever_is_reachable(pkg):
    ev = _events(pkg)
    base = _digest(ev)
    assert _digest(ev, possession_alternation=1.0) != base
    assert _digest(ev, env_sd_scale=0.0) != base

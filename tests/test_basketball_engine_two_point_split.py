"""Two-point make rate from the 2PA split in the native basketball engine (lane basketball-scenario-calibration, Phase 2
#5a, pre-registered 8caf0fca): EventSimConfig.fg2_from_two_point_split.

False is the default and changes nothing: a 2PA is made at the player's overall FG% (threes included). True makes it at
(FGM - 3PM) / (FGA - 3PA), so with EXACT the shared efficiency multiplier no longer has to lift 3P% to compensate
(full FIT 2025-26: 3P% 0.401 vs real 0.359, 2P% 0.512 vs real 0.547)."""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared.basketball_props_smart_sim import _engine_for_league_local


def _engine(league: str):
    prev = os.environ.get("SYNDICATE_NBA_TEAM_INPUTS")
    os.environ["SYNDICATE_NBA_TEAM_INPUTS"] = "0"
    try:
        return _engine_for_league_local(league)
    finally:
        if prev is None:
            os.environ.pop("SYNDICATE_NBA_TEAM_INPUTS", None)
        else:
            os.environ["SYNDICATE_NBA_TEAM_INPUTS"] = prev


def _team(p: str) -> pd.DataFrame:
    # Per-minute priors with a real 2P/3P split: ~0.55 on twos, ~0.36 on threes, overall ~0.47.
    mins = [36, 35, 34, 33, 32, 24, 18, 14, 9, 5]
    n = len(mins)
    return pd.DataFrame({
        "player_name": [f"{p}{i}" for i in range(n)],
        "min": mins,
        "_sim_min": [float(m) for m in mins],
        "_prior_fga_pm": [0.40] * n,
        "_prior_threes_att_pm": [0.17] * n,
        "_prior_threes_pm": [0.0612] * n,
        "_prior_fgm_pm": [0.0612 + 0.23 * 0.55] * n,
        "_prior_fta_pm": [0.11] * n,
        "_prior_ftm_pm": [0.086] * n,
    })


def _quarters(home_mu: float, away_mu: float):
    return [{"home_pts_mu": home_mu, "away_pts_mu": away_mu, "home_pts_sigma": 6.5, "away_pts_sigma": 6.5, "corr": 0.25}
            for _ in range(4)]


def _games(eng, n: int, **cfg):
    q = _quarters(28.0, 27.0)
    return [eng.simulate_pbp_game_boxscore(np.random.default_rng(seed), _team("H"), _team("A"), cfg=eng.EventSimConfig(**cfg),
                                           target_home_points=112.0, target_away_points=108.0, quarters=q) for seed in range(n)]


def _digest(games) -> str:
    h = hashlib.sha256()
    for g in games:
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    return h.hexdigest()


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_default_is_off_and_unset_equals_explicit_false(league):
    eng = _engine(league)
    assert eng.EventSimConfig().fg2_from_two_point_split is False
    assert _digest(_games(eng, 4)) == _digest(_games(eng, 4, fg2_from_two_point_split=False))


def test_player_two_pct_uses_the_split_and_falls_back():
    from syndicate.features.basketball_engine import engine as E

    df = _team("H")
    two = E._player_two_pct(df)
    assert np.allclose(two, 0.55, atol=1e-6)
    bad = pd.DataFrame({"_prior_fga_pm": [0.2, np.nan], "_prior_fgm_pm": [0.1, np.nan],
                        "_prior_threes_att_pm": [0.2, np.nan], "_prior_threes_pm": [0.07, np.nan]})
    assert np.allclose(E._player_two_pct(bad), 0.53)  # 2PA <= 0 and unknown -> default


def test_switch_is_reachable_and_moves_makes_from_threes_to_twos():
    eng = _engine("nba")
    off = _games(eng, 40)
    on = _games(eng, 40, fg2_from_two_point_split=True)
    assert _digest(on) != _digest(off)

    def pcts(games):
        f3m = f3a = f2m = f2a = 0
        for hb, ab, _hq, _aq in games:
            for box in (hb, ab):
                for p in box["players"]:
                    fga, fgm = int(p.get("fga") or 0), int(p.get("fgm") or 0)
                    tpa, tpm = int(p.get("fg3a") or 0), int(p.get("threes") or 0)
                    f3m += tpm; f3a += tpa; f2m += fgm - tpm; f2a += fga - tpa
        return f2m / f2a, f3m / f3a

    two_off, three_off = pcts(off)
    two_on, three_on = pcts(on)
    assert two_on > two_off + 0.02
    assert three_on < three_off - 0.01

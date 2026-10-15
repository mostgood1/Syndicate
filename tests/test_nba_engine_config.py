"""`nba_engine_config.json` production wiring (lane basketball-scenario-calibration; user decision 2026-10-15: enable the
FINAL Phase 2 config on a passing VALID read).

Absent = byte-identical; any unknown field = rejected whole (never a partial apply); present = the cfg carries the
file's EventSimConfig fields and the engine is built with its LeagueParams overrides -- the same output as building
that engine and cfg by hand."""
from __future__ import annotations

import dataclasses
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
    return pd.DataFrame({
        "player_name": [f"{p}{i}" for i in range(n)], "min": mins, "_sim_min": [float(m) for m in mins],
        "_prior_fga_pm": [0.40] * n, "_prior_threes_att_pm": [0.17] * n, "_prior_threes_pm": [0.0612] * n,
        "_prior_fgm_pm": [0.0612 + 0.23 * 0.55] * n, "_prior_fta_pm": [0.11] * n, "_prior_ftm_pm": [0.086] * n,
        "_prior_pf_pm": [0.06] * n,
    })


CONF = {
    "enabled": True,
    "event_sim_config": {"score_effect_k": 0.002, "fg2_from_two_point_split": True, "foul_out_in_sim": True,
                         "foul_trouble_thresholds": [2, 3, 4, 5], "foul_trouble_bench_mult": 0.05,
                         "possession_alternation": 1.0, "possessions_jitter": 0.0},
    "league_params": {"exact_target_calibration": True, "shooter_ft_rate": True},
}


def _quarters():
    return [{"home_pts_mu": 28.0, "away_pts_mu": 27.0, "home_pts_sigma": 6.5, "away_pts_sigma": 6.5, "corr": 0.25}
            for _ in range(4)]


def _run(cfg_obj, n=4):
    out = []
    for seed in range(n):
        out.append(bpss._call_native_engine_local(
            entrypoint_name="simulate_pbp_game_boxscore", league_code="nba",
            kwargs=dict(rng=np.random.default_rng(seed), home_players=_team("H"), away_players=_team("A"), cfg=cfg_obj,
                        target_home_points=112.0, target_away_points=108.0, quarters=_quarters())))
    h = hashlib.sha256()
    for g in out:
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    return h.hexdigest()


def _base_cfg():
    return bpss._build_smart_sim_config_local(n_sims=4, seed=1, use_pbp=True, roster_mode="pregame")


def test_absent_file_is_identity(tmp_path):
    cfg = _base_cfg()
    assert bpss._nba_engine_config_local(processed_root=tmp_path) == {}
    assert bpss._apply_nba_engine_config_local(cfg, processed_root=tmp_path, league_code="nba") is cfg


def test_disabled_or_unknown_field_is_rejected_whole(tmp_path, capsys):
    (tmp_path / bpss.NBA_ENGINE_CONFIG_FILE_LOCAL).write_text(json.dumps({**CONF, "enabled": False}))
    assert bpss._nba_engine_config_local(processed_root=tmp_path) == {}
    bad = json.loads(json.dumps(CONF))
    bad["event_sim_config"]["no_such_field"] = 1
    (tmp_path / bpss.NBA_ENGINE_CONFIG_FILE_LOCAL).write_text(json.dumps(bad))
    assert bpss._nba_engine_config_local(processed_root=tmp_path) == {}
    assert "NBA_ENGINE_CONFIG_REJECTED" in capsys.readouterr().out
    cfg = _base_cfg()
    assert bpss._apply_nba_engine_config_local(cfg, processed_root=tmp_path, league_code="nba") is cfg


def test_wnba_is_never_touched(tmp_path):
    (tmp_path / bpss.NBA_ENGINE_CONFIG_FILE_LOCAL).write_text(json.dumps(CONF))
    cfg = _base_cfg()
    assert bpss._apply_nba_engine_config_local(cfg, processed_root=tmp_path, league_code="wnba") is cfg


def test_present_file_is_reachable_and_equals_the_hand_built_engine(tmp_path):
    (tmp_path / bpss.NBA_ENGINE_CONFIG_FILE_LOCAL).write_text(json.dumps(CONF))
    cfg = bpss._apply_nba_engine_config_local(_base_cfg(), processed_root=tmp_path, league_code="nba")
    ev = cfg.event_cfg
    assert ev.score_effect_k == 0.002 and ev.fg2_from_two_point_split is True
    assert ev.foul_trouble_thresholds == (2, 3, 4, 5)
    assert dict(ev.league_params_overrides) == {"exact_target_calibration": True, "shooter_ft_rate": True}
    assert ev.config_sha == hashlib.sha256((tmp_path / bpss.NBA_ENGINE_CONFIG_FILE_LOCAL).read_bytes()).hexdigest()

    configured = _run(ev)
    default = _run(_base_cfg().event_cfg)
    assert configured != default  # reachable

    # Hand-built: the same LeagueParams overrides on a fresh engine, the same cfg values without the override field.
    from syndicate.features.basketball_engine import league_params
    from syndicate.features.basketball_engine.league_engine import LeagueEngine

    eng = LeagueEngine(dataclasses.replace(league_params("nba"), exact_target_calibration=True, shooter_ft_rate=True),
                       sample_lineup=bpss._sample_lineup_local)
    h = hashlib.sha256()
    for seed in range(4):
        g = eng.simulate_pbp_game_boxscore(rng=np.random.default_rng(seed), home_players=_team("H"), away_players=_team("A"),
                                           cfg=ev, target_home_points=112.0, target_away_points=108.0, quarters=_quarters())
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    assert h.hexdigest() == configured


def test_without_overrides_the_call_uses_the_unchanged_engine_and_output():
    # No `league_params_overrides` on the cfg (file absent) -> the very same cached engine object and the same draws as
    # calling that engine directly: the wiring adds nothing to today's path.
    assert bpss._engine_for_league_local("nba") is bpss._engine_for_league_local("nba", None)
    assert bpss._engine_for_league_local("nba") is bpss._engine_for_league_local("nba", ())
    ev = _base_cfg().event_cfg
    eng = bpss._engine_for_league_local("nba")
    h = hashlib.sha256()
    for seed in range(4):
        g = eng.simulate_pbp_game_boxscore(rng=np.random.default_rng(seed), home_players=_team("H"), away_players=_team("A"),
                                           cfg=ev, target_home_points=112.0, target_away_points=108.0, quarters=_quarters())
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    assert h.hexdigest() == _run(ev)


def test_configured_cfg_pickles_and_deepcopies_by_value(tmp_path):
    # P3, 2026-10-15: the bare make_dataclass class failed to pickle ("attribute lookup ... on types failed"), and
    # _persist_engine_inputs_once_local swallows errors -- every NBA game would have silently lost its live inputs.
    import copy
    import pickle

    (tmp_path / bpss.NBA_ENGINE_CONFIG_FILE_LOCAL).write_text(json.dumps(CONF))
    ev = bpss._apply_nba_engine_config_local(_base_cfg(), processed_root=tmp_path, league_code="nba").event_cfg
    for back in (pickle.loads(pickle.dumps(ev, protocol=4)), copy.deepcopy(ev)):
        assert dataclasses.asdict(back) == dataclasses.asdict(ev)
        assert back.league_params_overrides == ev.league_params_overrides
        assert _run(back) == _run(ev)

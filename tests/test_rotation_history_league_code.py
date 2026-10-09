"""_rotation_sim_minutes_for_team_local: the non-empty-gid / empty-stints branch.

That branch falls back to `_rotation_sim_minutes_from_history_local`, whose
`league_code` is a required keyword-only parameter. It used to be called
without it, so any sim run with pregame_safe=False (the vendored smart_sim sets
gid="" only when pregame_safe) raised TypeError there. Production pregame sims
take the gid="" branch, which always passed league_code, so the defect was
latent. Found 2026-10-09 by lane basketball-native-live-state.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from syndicate.features.shared import basketball_props_smart_sim as bpss


def _unused(*_args, **_kwargs):
    raise AssertionError("not reached on this branch")


def _fake_smart_sim(tmp_path: Path):
    return SimpleNamespace(
        _read_rotation_stints=lambda gid, side: pd.DataFrame(),
        _build_player_minutes_from_stints=_unused,
        _roll_minutes_unscaled=_unused,
        _regularize_rotation_minutes=_unused,
        _minutes_caps_from_team_df=_unused,
        _cap_and_redistribute_minutes=_unused,
        _rotation_minutes_signal_guardrail=_unused,
        _clean_id_str=_unused,
        _read_hist_any=lambda *paths: None,
        paths=SimpleNamespace(data_processed=tmp_path),
    )


def _call(tmp_path: Path, league_code: str):
    team_df = pd.DataFrame({"player_name": ["A Player"], "team": ["LVA"]})
    return bpss._rotation_sim_minutes_for_team_local(
        smart_sim_module=_fake_smart_sim(tmp_path),
        league_code=league_code,
        team_df=team_df,
        date_str="2026-06-01",
        home_tri="LVA",
        away_tri="NYL",
        team_tri="LVA",
        side="home",
        game_id="401234567",
    )


def test_empty_stints_falls_back_to_history_without_type_error(tmp_path):
    sim_min, lineups, lw, diag = _call(tmp_path, "wnba")

    assert (sim_min, lineups, lw) == (None, None, None)
    # The history path ran and its diag came back merged into this one.
    assert diag["source"] == "history"
    assert diag["lookback_days"] == 28
    assert diag["reason"] == "no_rotation_stints_history"
    assert diag["game_id"] == "401234567"


def test_empty_stints_branch_forwards_league_code(tmp_path, monkeypatch):
    seen: dict = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return None, None, None, {"attempted": True, "applied": False, "source": "history", "reason": "spy"}

    monkeypatch.setattr(bpss, "_rotation_sim_minutes_from_history_local", spy)
    _, _, _, diag = _call(tmp_path, "wnba")

    assert seen["league_code"] == "wnba"
    assert seen["lookback_days"] == 28
    assert diag["reason"] == "spy"

"""Lane `nba-pregame-lineup-pools` (2026-10-12): the rotation-history path that builds the engine's lineup pools.

1. `_rotation_sim_minutes_for_team_local`, per-game-stints branch: when the stints' total minutes are implausible it
   falls back to the history path. That call named `rotation_sim_minutes_from_history`, which is not defined anywhere,
   so the branch raised NameError. Pregame sims never reach it (gid is "" when pregame_safe), which is why it was
   latent; any sim with a per-game stints file and bad totals crashed there.
2. `_espn_name_to_id_map_for_game_local` no longer reads the vendored `pbp_espn_history.csv`. Measured on the fleet,
   pregame (D-1) map per game over every game with native player checks: it added 0 keys for players who played --
   WNBA 0/7,399 (366 games, csv present), NBA 0/31,936 (1,434 games; NBA holds only the .parquet it never read).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from syndicate.features.shared import basketball_props_smart_sim as bpss


def _unused(*_args, **_kwargs):
    raise AssertionError("not reached on this branch")


def _stints_module(tmp_path: Path, minutes: float):
    stints = pd.DataFrame({"team": ["LVA"], "event_id": ["401"], "duration_sec": [minutes * 60.0],
                           "lineup_player_ids": ["1;2;3;4;5"]})
    return SimpleNamespace(
        _read_rotation_stints=lambda gid, side: stints,
        _build_player_minutes_from_stints=lambda st: pd.DataFrame({"team": ["LVA"], "player_id": ["1"], "minutes": [minutes]}),
        _roll_minutes_unscaled=_unused,
        _regularize_rotation_minutes=_unused,
        _minutes_caps_from_team_df=_unused,
        _cap_and_redistribute_minutes=_unused,
        _rotation_minutes_signal_guardrail=_unused,
        _clean_id_str=_unused,
        _read_hist_any=lambda *paths: None,
        paths=SimpleNamespace(data_processed=tmp_path),
    )


def test_bad_stints_total_falls_back_to_history_without_name_error(tmp_path, monkeypatch):
    seen: dict = {}

    def history_spy(**kwargs):
        seen.update(kwargs)
        return None, None, None, {"attempted": True, "applied": False, "source": "history", "reason": "spy"}

    monkeypatch.setattr(bpss, "_rotation_sim_minutes_from_history_local", history_spy)
    monkeypatch.setattr(bpss, "_espn_name_to_id_map_for_game_local", lambda **_k: {("LVA", "A PLAYER"): "1"})
    module = _stints_module(tmp_path, minutes=12.0)  # 12 of 200 regulation minutes: far below the 0.8x floor

    sim_min, lineups, lw, diag = bpss._rotation_sim_minutes_for_team_local(
        smart_sim_module=module, league_code="wnba", team_df=pd.DataFrame({"player_name": ["A Player"], "team": ["LVA"]}),
        date_str="2026-06-01", home_tri="LVA", away_tri="NYL", team_tri="LVA", side="home", game_id="401234567")

    assert (sim_min, lineups, lw) == (None, None, None)
    assert seen["smart_sim_module"] is module and seen["league_code"] == "wnba" and seen["lookback_days"] == 28
    assert diag["fallback_reason"] == "bad_rotation_total_minutes"
    assert diag["reason"] == "spy"
    assert diag["rotation_total_minutes_raw"] == 12.0


def test_pregame_name_map_ignores_vendored_pbp_history(tmp_path, monkeypatch):
    processed = tmp_path / "wnba_source" / "data" / "processed"
    checks = processed / "rotation_stints"
    checks.mkdir(parents=True)
    pd.DataFrame([("2026-06-01", "LVA", "111", "A Player")], columns=["date", "team", "player_id", "player_name"]).to_csv(
        checks / "player_checks_2026-06-01.csv", index=False)
    pd.DataFrame([{"date": "2026-06-01", "team": "LVA", "enter_player_id": "999", "exit_player_id": "998",
                   "enter_player_name": "Vendored Only", "exit_player_name": "A Player"}]).to_csv(
        processed / "pbp_espn_history.csv", index=False)
    monkeypatch.setattr(bpss, "_espn_event_id_for_matchup_local", lambda **_: "")
    module = SimpleNamespace(paths=SimpleNamespace(data_processed=processed, root=processed.parent.parent),
                             _clean_id_str=bpss._clean_id_str_local, _norm_player_key=bpss._norm_name_key)

    out = bpss._espn_name_to_id_map_for_game_local(smart_sim_module=module, date_str="2026-06-02", home_tri="LVA",
                                                   away_tri="NYL", event_id=None)

    key = lambda name: str(bpss._norm_name_key(name)).upper().strip()
    assert out == {("LVA", key("A Player")): "111"}

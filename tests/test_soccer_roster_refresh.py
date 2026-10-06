"""Soccer ESPN rosters get a producer (lane `soccer-roster-refresh`).

`rosters_<season>.csv` had none: on 2026-10-06 the fleet served the 2026-07-20 git
seed. `refresh_odds_sources._soccer_rosters_step` refreshes it when stale, and
`build_soccer_rosters` never lets a sparse ESPN fetch shrink a club.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def refresh():
    return _load("refresh_odds_sources_rosters_under_test", "scripts/refresh_odds_sources.py")


@pytest.fixture(scope="module")
def builder():
    return _load("build_soccer_rosters_under_test", "scripts/build_soccer_rosters.py")


def _roster_file(root: Path, league: str, season: int, *, age_days: float | None) -> Path:
    target = root / league / "api" / "rosters" / f"rosters_{season}.csv"
    if age_days is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("team_id,team,player_id,player_name\n", encoding="utf-8")
        stamp = time.time() - age_days * 86400.0
        os.utime(target, (stamp, stamp))
    return target


def _season(refresh, league="epl"):
    return int(refresh.soccer_default_season(league))


def test_absent_roster_produces_a_step_into_the_data_root(refresh, tmp_path, monkeypatch):
    monkeypatch.delenv(refresh._SOCCER_ROSTER_REFRESH_ENV, raising=False)
    step = refresh._soccer_rosters_step("epl", tmp_path, sys.executable)
    assert step is not None
    assert "scripts/build_soccer_rosters.py" in step.command
    assert step.command[step.command.index("--out-root") + 1] == str(tmp_path)
    assert step.command[step.command.index("--season") + 1] == str(_season(refresh))
    assert set(step.phases) == {"pregame", "live"}


def test_stale_refetches_fresh_is_a_noop(refresh, tmp_path, monkeypatch):
    monkeypatch.delenv(refresh._SOCCER_ROSTER_REFRESH_ENV, raising=False)
    _roster_file(tmp_path, "epl", _season(refresh), age_days=refresh._SOCCER_ROSTER_REFRESH_DAYS + 1)
    assert refresh._soccer_rosters_step("epl", tmp_path, sys.executable) is not None
    _roster_file(tmp_path, "epl", _season(refresh), age_days=0.5)
    assert refresh._soccer_rosters_step("epl", tmp_path, sys.executable) is None


def test_kill_switch_off_differs_from_on(refresh, tmp_path, monkeypatch):
    monkeypatch.setenv(refresh._SOCCER_ROSTER_REFRESH_ENV, "0")
    off = refresh._soccer_rosters_step("epl", tmp_path, sys.executable)
    monkeypatch.delenv(refresh._SOCCER_ROSTER_REFRESH_ENV)
    on = refresh._soccer_rosters_step("epl", tmp_path, sys.executable)
    assert off is None and on is not None


def test_step_is_wired_into_the_soccer_build(refresh):
    source = (_REPO / "scripts" / "refresh_odds_sources.py").read_text(encoding="utf-8")
    body = source[source.index("def _build_soccer_steps"):]
    assert "_soccer_rosters_step(league, soccer_root, python_exe)" in body


def _player(i):
    return {"player_id": str(i), "player_name": f"P{i}", "position": "Forward"}


def test_sparse_fetch_never_shrinks_a_club(builder, tmp_path, monkeypatch):
    teams = [{"team_id": "1", "name": "Full FC"}, {"team_id": "2", "name": "Sparse FC"}, {"team_id": "3", "name": "Grown FC"}]
    out = tmp_path / "epl" / "api" / "rosters" / "rosters_2026.csv"
    out.parent.mkdir(parents=True)
    previous = [{"team_id": "2", "team": "Sparse FC", **_player(100 + i)} for i in range(25)]
    previous += [{"team_id": "3", "team": "Grown FC", **_player(200 + i)} for i in range(5)]
    pd.DataFrame(previous).to_csv(out, index=False)
    fetched = {"1": [_player(i) for i in range(26)], "2": [_player(300)], "3": [_player(400 + i) for i in range(10)]}
    monkeypatch.setattr(builder, "all_teams", lambda league: teams)
    monkeypatch.setattr(builder, "_fetch_roster_with_retries", lambda league, team_id: fetched[team_id])
    monkeypatch.setattr(builder, "sparse_roster_teams", lambda league, season: [])
    frame = builder.build_rosters("epl", 2026, out_root=tmp_path, sleep_seconds=0)
    counts = frame.groupby(frame["team_id"].astype(str)).size().to_dict()
    assert counts == {"1": 26, "2": 25, "3": 10}  # sparse kept previous 25; a sparse but GROWN club takes the fetch
    written = pd.read_csv(out, dtype=str)
    assert len(written) == 61


def test_nothing_fetched_and_no_previous_writes_nothing(builder, tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "all_teams", lambda league: [{"team_id": "1", "name": "X"}])
    monkeypatch.setattr(builder, "_fetch_roster_with_retries", lambda league, team_id: [])
    monkeypatch.setattr(builder, "roster_rows", type("R", (), {"__call__": lambda self, *a: (), "cache_clear": lambda self: None})())
    frame = builder.build_rosters("epl", 2026, out_root=tmp_path, sleep_seconds=0)
    assert frame.empty
    assert not (tmp_path / "epl" / "api" / "rosters" / "rosters_2026.csv").exists()


def test_rosters_are_allowlisted():
    from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path

    assert is_hot_artifact_relative_path("soccer_source/epl/api/rosters/rosters_2026.csv")

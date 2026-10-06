"""`#357` -- the soccer pipeline must be able to create the input it requires.

`build_soccer_artifacts.py` exits 1 when a league's ratings history is missing,
and until now `fetch_soccer_history_local.py` appeared NOWHERE in
`refresh_odds_sources.py`: no step in the pipeline could produce the thing the
pipeline demanded, so a disk that ever lacked history could never recover.

The step is conditional, which is the property most worth pinning down. It is a
strict no-op when the files are present -- so shipping it CANNOT be validated by
watching production turn green, and these tests are the only thing that says it
works. They assert both directions deliberately.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_orchestrator():
    spec = importlib.util.spec_from_file_location("ros_under_test", REPO_ROOT / "scripts" / "refresh_odds_sources.py")
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: the module defines frozen dataclasses, and
    # `dataclasses._is_type` resolves the owning module out of `sys.modules`.
    sys.modules["ros_under_test"] = module
    spec.loader.exec_module(module)
    return module


ALL_LEAGUES = (
    "mls",
    "epl",
    "la_liga",
    "bundesliga",
    "serie_a",
    "ligue_1",
    "eredivisie",
    "primeira_liga",
    "championship",
    "belgian_pro_league",
)


def test_no_step_when_history_is_already_present():
    """The healthy case. The bootstrap sync seeds `data/soccer_source` from the
    repo on every service start, so on a working disk this must add nothing --
    otherwise every tick would make a network fetch it does not need."""
    module = _load_orchestrator()
    root = REPO_ROOT / "data" / "soccer_source"
    for league in ALL_LEAGUES:
        assert module._soccer_history_step(league, root, "py") is None, (
            f"{league} would refetch history that is already on disk"
        )


def test_every_league_is_covered_when_the_disk_is_bare(tmp_path):
    """`_load_team_ratings` has THREE branches and the fix must match all of them:
    mls fetches ratings live and needs nothing, four leagues need
    `history/matches_*.csv`, the Understat five need `team_history/teams_*.csv`.
    Getting this wrong strands a league with no way to ever build."""
    module = _load_orchestrator()
    root = tmp_path / "soccer_source"

    assert module._soccer_history_step("mls", root, "py") is None, (
        "mls ratings come from a live ASA fetch -- a disk step for it would always be wasted"
    )

    expected_kind = {
        "epl": "teams",
        "la_liga": "teams",
        "bundesliga": "teams",
        "serie_a": "teams",
        "ligue_1": "teams",
        "eredivisie": "matches",
        "primeira_liga": "matches",
        "championship": "matches",
        "belgian_pro_league": "matches",
    }
    for league, kind in expected_kind.items():
        step = module._soccer_history_step(league, root, "py")
        assert step is not None, f"{league} has no way to obtain history"
        command = list(step.command)
        assert "scripts/fetch_soccer_history_local.py" in command
        assert command[command.index("--kind") + 1] == kind, f"{league} asked for the wrong history kind"
        # --out-dir must be explicit: the fetcher's default points at the REPO
        # tree, which on Render is not the root the sim reads.
        out_dir = Path(command[command.index("--out-dir") + 1])
        assert out_dir.is_relative_to(root), f"{league} would write history where the sim will not look"


def test_step_runs_in_the_live_phase_and_before_the_sim(tmp_path):
    """The autorun launches with `--phase live`, under which only `_artifacts`
    and `_live_state` run. A pregame-only prerequisite would never execute on the
    one path that needs it -- and it must be ordered ahead of the sim that
    consumes it, since steps run sequentially."""
    module = _load_orchestrator()
    root = tmp_path / "soccer_source"
    step = module._soccer_history_step("la_liga", root, "py")
    assert "live" in step.phases and "pregame" in step.phases

    args = type("Args", (), {"date": "2026-08-11", "soccer_date": "2026-08-15", "soccer_leagues": "la_liga"})()
    original = module._local_source_bundle_root
    module._local_source_bundle_root = lambda slug: root
    try:
        names = [s.name for s in module._filter_steps(module._build_soccer_steps(args), "live")]
    finally:
        module._local_source_bundle_root = original
    assert "soccer_la_liga_history" in names, "the live phase would skip the prerequisite"
    assert names.index("soccer_la_liga_history") < names.index("soccer_la_liga_artifacts"), (
        "history must be fetched before the sim that reads it"
    )


def test_unreadable_history_dir_is_not_treated_as_missing(monkeypatch, tmp_path):
    """Unreadable is not empty. Refetching over a directory we merely failed to
    stat would turn a transient IO error into a network call on every tick."""
    module = _load_orchestrator()

    def _boom(self, pattern):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "glob", _boom)
    assert module._soccer_history_step("la_liga", tmp_path / "soccer_source", "py") is None


# --- current-season ratings history (lane `soccer-team-history-current-season`, 2026-10-06) ---------------------

GOALS_FOUR = ("eredivisie", "primeira_liga", "championship", "belgian_pro_league")


def _season_window(module, monkeypatch, days_in: int):
    """Pin `central_today` to `days_in` days after each league's season start, whatever today is."""
    import datetime as _dt

    starts = {}
    for league in ALL_LEAGUES:
        if league == "mls":
            continue
        season = int(module.soccer_default_season(league))
        starts[league] = module.soccer_season_date_range(league, season)[0]
    first = min(starts.values())
    monkeypatch.setattr(module, "central_today", lambda: max(starts.values()) + _dt.timedelta(days=days_in))
    return first


def test_current_history_is_off_by_default(monkeypatch, tmp_path):
    """Absent is OFF: shipping this module changes nothing until the switch is set."""
    module = _load_orchestrator()
    monkeypatch.delenv("SYNDICATE_SOCCER_CURRENT_HISTORY", raising=False)
    for league in ALL_LEAGUES:
        assert module._soccer_current_history_step(league, tmp_path / "soccer_source", "py") is None


def test_current_history_fetches_the_current_season_for_each_branch(monkeypatch, tmp_path):
    """REACHABILITY (on != off): with the switch on and no current-season file, every league whose ratings
    are disk-backed gets a fetch of THIS season, of the family `_load_team_ratings` reads for it."""
    module = _load_orchestrator()
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    _season_window(module, monkeypatch, 30)
    root = tmp_path / "soccer_source"
    assert module._soccer_current_history_step("mls", root, "py") is None
    for league in ALL_LEAGUES:
        if league == "mls":
            continue
        step = module._soccer_current_history_step(league, root, "py")
        assert step is not None, f"{league} never refreshes its current-season ratings history"
        command = list(step.command)
        kind = "matches" if league in GOALS_FOUR else "teams"
        assert command[command.index("--kind") + 1] == kind
        assert command[command.index("--seasons") + 1] == str(int(module.soccer_default_season(league)))
        out_dir = Path(command[command.index("--out-dir") + 1])
        assert out_dir == root / league / ("history" if kind == "matches" else "team_history")


def test_current_history_refetches_daily_not_every_tick(monkeypatch, tmp_path):
    import os as _os
    import time as _time

    module = _load_orchestrator()
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    _season_window(module, monkeypatch, 30)
    root = tmp_path / "soccer_source"
    season = int(module.soccer_default_season("epl"))
    target = root / "epl" / "team_history" / f"teams_{season}.csv"
    target.parent.mkdir(parents=True)
    target.write_text("league,season,team\n", encoding="utf-8")
    assert module._soccer_current_history_step("epl", root, "py") is None, "a fresh file must not refetch"
    old = _time.time() - 2 * 86400
    _os.utime(target, (old, old))
    assert module._soccer_current_history_step("epl", root, "py") is not None, "a day-old file must refetch"


def test_current_history_waits_for_the_season_to_start(monkeypatch, tmp_path):
    """The fetcher refuses to write an empty file, so fetching before round one would fail every tick."""
    module = _load_orchestrator()
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    import datetime as _dt

    season = int(module.soccer_default_season("epl"))
    start = module.soccer_season_date_range("epl", season)[0]
    monkeypatch.setattr(module, "central_today", lambda: start + _dt.timedelta(days=2))
    assert module._soccer_current_history_step("epl", tmp_path / "soccer_source", "py") is None


def test_current_history_runs_in_the_live_phase_before_the_sim(monkeypatch, tmp_path):
    module = _load_orchestrator()
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    _season_window(module, monkeypatch, 30)
    root = tmp_path / "soccer_source"
    args = type("Args", (), {"date": "2026-10-06", "soccer_date": "2026-10-10", "soccer_leagues": "la_liga"})()
    monkeypatch.setattr(module, "_local_source_bundle_root", lambda slug: root)
    names = [s.name for s in module._filter_steps(module._build_soccer_steps(args), "live")]
    assert "soccer_la_liga_history_current" in names
    assert names.index("soccer_la_liga_history_current") < names.index("soccer_la_liga_artifacts")

"""The game-day NBA props pull runs with the live-odds-worker ROLE env (lane gameday-pull-role-env, user 2026-10-21).

The Windows tasks start it from a bare login shell; with that env its props runs lacked NBA_BETTING_DATA_ROOT (todo #718),
the local memory limit and the log stamps. It now copies the running role's env and refuses without one.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("nba_gameday_props_pull_role_env", ROOT / "scripts" / "nba_gameday_props_pull.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def _proc(root: Path, pid: int, argv: list[str], env: dict[str, str]) -> None:
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in env.items()) + b"\0")


def test_role_env_is_the_live_odds_worker_process_env(tmp_path):
    proc = tmp_path / "proc"
    _proc(proc, 10, ["bash", "-lc", "python scripts/run_live_odds_refresh_worker.py"], {"WHO": "bash"})
    _proc(proc, 11, ["/v/bin/python", "scripts/run_refresh_worker.py"], {"WHO": "refresh-worker"})
    _proc(proc, 12, ["/v/bin/python", "scripts/run_live_odds_refresh_worker.py"], {"WHO": "live-odds", "A": "x=y"})
    (proc / "self").mkdir()
    assert g.role_env(proc) == {"WHO": "live-odds", "A": "x=y"}


def test_no_role_process_is_none(tmp_path):
    proc = tmp_path / "proc"
    _proc(proc, 11, ["/v/bin/python", "scripts/run_refresh_worker.py"], {"WHO": "refresh-worker"})
    assert g.role_env(proc) is None
    assert g.role_env(tmp_path / "missing") is None


def _pull_day(tmp_path):
    p = tmp_path / "nba_source" / "data" / "processed"
    p.mkdir(parents=True)
    (p / "game_odds_2026-10-20.csv").write_text("date,commence_time\n2026-10-20,2030-01-01T00:00:00Z\n", encoding="utf-8")
    return ["--data-root", str(tmp_path), "--date", "2026-10-20"]


@pytest.fixture
def pulled(monkeypatch):
    seen = []
    monkeypatch.setattr(g, "props_job_running", lambda: False)

    class R:
        returncode, stderr = 0, ""

    monkeypatch.setattr(g.subprocess, "run", lambda cmd, **kw: seen.append(kw["env"]) or R())
    return seen


def test_the_pull_runs_with_the_role_env_not_this_shells(tmp_path, monkeypatch, pulled):
    monkeypatch.setenv("SHELL_ONLY", "1")
    role = {"SYNDICATE_DATA_ROOT": str(tmp_path), "NBA_BETTING_DATA_ROOT": "r", "ODDS_API_KEY": "rolekey"}
    monkeypatch.setattr(g, "role_env", lambda: dict(role))
    g.main(_pull_day(tmp_path))
    assert pulled == [role]                                   # exactly the role's env: nothing from this shell


def test_no_role_refuses_and_never_pulls(tmp_path, monkeypatch, pulled, capsys):
    monkeypatch.setattr(g, "role_env", lambda: None)
    assert g.main(_pull_day(tmp_path)) == 2
    assert pulled == [] and "REFUSING: no running live-odds-worker" in capsys.readouterr().out


def test_a_role_on_another_data_root_refuses(tmp_path, monkeypatch, pulled):
    monkeypatch.setattr(g, "role_env", lambda: {"SYNDICATE_DATA_ROOT": str(tmp_path / "other"), "ODDS_API_KEY": "k"})
    assert g.main(_pull_day(tmp_path)) == 2 and pulled == []


def test_env_file_key_only_fills_a_role_without_one(tmp_path, monkeypatch, pulled):
    env_file = tmp_path / ".env"
    env_file.write_text("ODDS_API_KEY=filekey\n", encoding="utf-8")
    args = _pull_day(tmp_path) + ["--env-file", str(env_file)]
    monkeypatch.setattr(g, "role_env", lambda: {"SYNDICATE_DATA_ROOT": str(tmp_path), "ODDS_API_KEY": "rolekey"})
    g.main(args)
    monkeypatch.setattr(g, "role_env", lambda: {"SYNDICATE_DATA_ROOT": str(tmp_path)})
    g.main(args)
    assert [e["ODDS_API_KEY"] for e in pulled] == ["rolekey", "filekey"]

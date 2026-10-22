"""The nightly ci-suite sweeps test-fixture keys out of the fleet Redis afterwards (lane fleet-redis-test-pollution).

Reachability first: the janitor must be invoked through `cmd_ci_run` -- the function the
`ci-suite` ScheduledJob actually calls -- on success, on a failing suite, and on a suite
that never starts. Then the helper's own contract.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import local_production as lp


def _args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(home=str(tmp_path), port=5000, host="127.0.0.1", state="x",
                              redis_url="redis://user:pw@10.1.1.1:6379/0")


def test_janitor_runs_after_a_passing_suite_and_keeps_its_code(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(lp, "_ci_run_suite", lambda a: 0)
    monkeypatch.setattr(lp, "run_state_janitor", lambda s, **k: calls.append(s) or 0)
    assert lp.cmd_ci_run(_args(tmp_path)) == 0
    assert len(calls) == 2   # once before the suite, once after


def test_janitor_runs_after_a_failing_suite_and_does_not_change_its_code(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(lp, "_ci_run_suite", lambda a: 1)
    monkeypatch.setattr(lp, "run_state_janitor", lambda s, **k: calls.append(s) or 4)
    assert lp.cmd_ci_run(_args(tmp_path)) == 1   # the janitor's 4 must not replace the suite's 1
    assert len(calls) == 2


def test_the_pre_sweep_happens_before_the_suite_starts(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(lp, "_ci_run_suite", lambda a: order.append("suite") or 0)
    monkeypatch.setattr(lp, "run_state_janitor", lambda s, **k: order.append("janitor"))
    lp.cmd_ci_run(_args(tmp_path))
    assert order == ["janitor", "suite", "janitor"]


def test_janitor_runs_when_the_suite_raises(monkeypatch, tmp_path):
    calls = []

    def boom(a):
        raise RuntimeError("clone exploded")

    monkeypatch.setattr(lp, "_ci_run_suite", boom)
    monkeypatch.setattr(lp, "run_state_janitor", lambda s, **k: calls.append(s))
    with pytest.raises(RuntimeError, match="clone exploded"):
        lp.cmd_ci_run(_args(tmp_path))
    assert len(calls) == 2


def test_a_broken_janitor_never_masks_the_suite_result(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "_ci_run_suite", lambda a: 7)

    def broken(s, **k):
        raise OSError("disk")

    monkeypatch.setattr(lp, "run_state_janitor", broken)
    assert lp.cmd_ci_run(_args(tmp_path)) == 7


def test_ci_run_subcommand_dispatches_to_the_wrapper():
    parser_src = Path(lp.__file__).read_text(encoding="utf-8")
    assert "p.set_defaults(func=cmd_ci_run)" in parser_src and "def _ci_run_suite" in parser_src


def test_helper_builds_a_safe_command_and_passes_the_url_by_env(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kw):
        seen["command"], seen["env"], seen["cwd"] = command, kw["env"], kw["cwd"]
        return SimpleNamespace(returncode=0)

    settings = lp.settings_from_args(_args(tmp_path))
    assert lp.run_state_janitor(settings, run=fake_run) == 0
    joined = " ".join(seen["command"])
    assert "keyvalue_janitor.py" in joined and "--apply" in joined and "--backup-dir" in joined
    assert "--min-idle-seconds 300" in joined
    assert "pw" not in joined and "10.1.1.1" not in joined          # URL is never on argv
    assert seen["env"]["SYNDICATE_JANITOR_REDIS_URL"] == settings.redis_url
    assert Path(seen["cwd"]) == lp.REPO_ROOT


def test_helper_swallows_a_launch_failure(monkeypatch, tmp_path, capsys):
    def fake_run(command, **kw):
        raise FileNotFoundError("python gone")

    assert lp.run_state_janitor(lp.settings_from_args(_args(tmp_path)), run=fake_run) is None
    assert "could not run" in capsys.readouterr().out


def test_helper_skips_when_the_script_is_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(lp, "REPO_ROOT", tmp_path / "nowhere")
    called = []
    assert lp.run_state_janitor(lp.settings_from_args(_args(tmp_path)), run=lambda *a, **k: called.append(1)) is None
    assert not called and "skipped" in capsys.readouterr().out


def test_janitor_script_exists_in_the_repo():
    assert (lp.REPO_ROOT / lp.JANITOR_SCRIPT).is_file()

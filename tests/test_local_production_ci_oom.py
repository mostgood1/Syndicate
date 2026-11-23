"""The nightly ci-suite runs at oom_score_adj 1000 (lane board-split-memory-guard, todo #850, findings section 15).

On 2026-11-20 at 08:49Z a pytest chunk ran away to 8.4 GB and the host's global OOM killed it, the largest process.
Every fleet role runs at oom_score_adj 0, and so did the suite, so a smaller runaway would have killed the board
child instead. Switch SYNDICATE_CI_SUITE_OOM_SCORE_ADJ: absent = ON (1000), `0` / `off` = the old behaviour.

Reachability first: off != on, read back from a real child AND its child. The suite's command is `nice ... python
run_ci_suite.py`, and the pytest chunks it forks are the processes that run away. Then the default is shown to reach
`_ci_run_suite`, then the switch's rules.
"""

from __future__ import annotations

import argparse
import builtins
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import local_production as lp

LINUX = sys.platform.startswith("linux")
READ_OWN = "print(open('/proc/self/oom_score_adj').read().strip())"
READ_GRANDCHILD = (
    "import subprocess, sys; "
    f"print('GRANDCHILD=' + subprocess.check_output([sys.executable, '-c', {READ_OWN!r}], text=True).strip())"
)


def _own() -> int:
    return int(Path("/proc/self/oom_score_adj").read_text().strip())


def _spawn_and_read(tmp_path: Path, environ: dict[str, str], capfd) -> tuple[str, str]:
    """(the CI_SUITE_OOM_SCORE_ADJ line's read=, the grandchild's own value)."""
    command = [sys.executable, "-c", READ_GRANDCHILD]
    if shutil.which("nice"):
        command = ["nice", "-n", "19"] + command
    rc = lp.spawn_ci_suite(command, cwd=str(tmp_path), env=dict(os.environ), environ=environ)
    out = capfd.readouterr().out.splitlines()
    assert rc == 0, out
    line = next(ln for ln in out if ln.startswith("CI_SUITE_OOM_SCORE_ADJ "))
    grandchild = next(ln for ln in out if ln.startswith("GRANDCHILD="))
    return line.rsplit("read=", 1)[1].strip(), grandchild.split("=", 1)[1]


@pytest.mark.skipif(not LINUX, reason="oom_score_adj is a Linux /proc file")
def test_suite_oom_score_adj_off_is_not_on_through_a_real_grandchild(tmp_path, capfd):
    own = _own()
    want = 1000 if own != 1000 else 999  # inside tonight's suite this process already runs at 1000
    off = _spawn_and_read(tmp_path, {lp.CI_SUITE_OOM_SCORE_ADJ_ENV: "0"}, capfd)
    on = _spawn_and_read(tmp_path, {lp.CI_SUITE_OOM_SCORE_ADJ_ENV: str(want)}, capfd)
    assert off == (str(own), str(own))  # off: the inherited value, exactly the old behaviour
    assert on == (str(want), str(want))  # on: the child AND the process it forks
    assert off != on


def test_the_default_reaches_the_suite_through_ci_run_suite(monkeypatch, tmp_path):
    """`_ci_run_suite` is what the `ci-suite` ScheduledJob runs (through cmd_ci_run). Absent switch -> 1000."""
    monkeypatch.delenv(lp.CI_SUITE_OOM_SCORE_ADJ_ENV, raising=False)
    monkeypatch.setattr(lp, "git_commit", lambda *a, **k: "f" * 40)
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    seen = {}

    class _Proc:
        pid = 4242

        def __init__(self, command, **kwargs):
            seen["command"], seen["kwargs"] = command, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def wait(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(lp.subprocess, "Popen", _Proc)
    monkeypatch.setattr(lp, "read_oom_score_adj", lambda pid: "1000")
    monkeypatch.setattr(lp, "IS_WINDOWS", False)
    args = argparse.Namespace(home=str(tmp_path), port=5000, host="127.0.0.1", state="x", redis_url="redis://x:1/0")
    assert lp._ci_run_suite(args) == 0
    assert "scripts/run_ci_suite.py" in seen["command"]
    assert seen["kwargs"]["cwd"] == str(tmp_path / "ci-checkout")
    preexec = seen["kwargs"]["preexec_fn"]
    assert preexec is not None
    assert preexec.__qualname__.startswith("_set_own_oom_score_adj")
    assert preexec.__closure__[0].cell_contents == 1000


def test_off_passes_no_preexec_and_windows_never_does(monkeypatch, tmp_path, capsys):
    kwargs_seen = []

    class _Proc:
        pid = 7

        def __init__(self, command, **kwargs):
            kwargs_seen.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def wait(self):
            return 3

        def kill(self):
            pass

    monkeypatch.setattr(lp.subprocess, "Popen", _Proc)
    monkeypatch.setattr(lp, "read_oom_score_adj", lambda pid: "0")
    monkeypatch.setattr(lp, "IS_WINDOWS", False)
    assert lp.spawn_ci_suite(["x"], cwd=str(tmp_path), env={}, environ={lp.CI_SUITE_OOM_SCORE_ADJ_ENV: "off"}) == 3
    monkeypatch.setattr(lp, "IS_WINDOWS", True)  # Windows Popen refuses any preexec_fn
    assert lp.spawn_ci_suite(["x"], cwd=str(tmp_path), env={}, environ={}) == 3
    assert [k["preexec_fn"] for k in kwargs_seen] == [None, None]
    out = capsys.readouterr().out
    assert "CI_SUITE_OOM_SCORE_ADJ switch=off pid=7 read=0" in out
    assert "CI_SUITE_OOM_SCORE_ADJ switch=1000 pid=7 read=n/a" in out


@pytest.mark.parametrize(
    "raw, want",
    [
        (None, 1000),  # absent = ON
        ("", 1000),
        ("  ", 1000),
        ("garbage", 1000),  # unparseable -> the default, never silently off
        ("0", None),
        ("off", None),
        ("OFF", None),
        ("false", None),
        ("no", None),
        ("-5", None),  # lowering needs privilege; treated as off
        ("500", 500),
        ("5000", 1000),  # the kernel's ceiling
    ],
)
def test_switch_rules(raw, want):
    environ = {} if raw is None else {lp.CI_SUITE_OOM_SCORE_ADJ_ENV: raw}
    assert lp.ci_suite_oom_score_adj(environ) == want


def test_a_failed_write_never_stops_the_suite(monkeypatch):
    def _deny(*a, **k):
        raise PermissionError("read-only /proc")

    monkeypatch.setattr(builtins, "open", _deny)
    assert lp._set_own_oom_score_adj(1000)() is None


def test_read_oom_score_adj_of_a_missing_pid_is_unreadable():
    assert lp.read_oom_score_adj(2**31 - 1) == "unreadable"

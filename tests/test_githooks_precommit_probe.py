"""The pre-commit ledger guard must RUN when python3 is a broken alias (lane precommit-python-probe, 2026-10-14).

Commit 857ec54b went in with "python3: Permission denied" from the hook: on Windows `python3` was the WindowsApps
App Execution Alias, which could not start from a backgrounded shell, and the hook read its exit 126 as fail-open.
These run the REAL hook under `sh` with a controlled PATH.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "pre-commit"
SH = shutil.which("sh")
DIRNAME = shutil.which("dirname")

pytestmark = pytest.mark.skipif(not SH or not DIRNAME, reason="needs sh and dirname")


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _posix(p: str) -> str:
    """An absolute path as `sh` on this platform spells it (Git Bash wants /c/..., not C:\\...)."""
    if os.name != "nt":
        return p
    drive, rest = os.path.splitdrive(os.path.abspath(p))
    return "/" + drive[0].lower() + rest.replace("\\", "/")


def _setup(tmp_path: Path, *, broken_python3: bool, working_python: bool) -> tuple[Path, Path]:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    shutil.copy(HOOK, hooks / "pre-commit")
    # A stand-in checker that always reports a VIOLATION: if it runs, the hook must exit 1.
    (hooks / "ledger_precommit.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    _script(bin_ / "dirname", f'exec "{_posix(DIRNAME)}" "$@"')
    if broken_python3:
        _script(bin_ / "python3", 'echo "python3: Permission denied" >&2; exit 126')
    if working_python:
        _script(bin_ / "python", f'exec "{_posix(sys.executable)}" "$@"')
    return hooks, bin_


def _run(hooks: Path, bin_: Path) -> subprocess.CompletedProcess:
    env = {"PATH": _posix(str(bin_)), "HOME": str(bin_.parent)}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return subprocess.run([SH, _posix(str(hooks / "pre-commit"))], capture_output=True, text=True, env=env)


def test_a_python3_that_cannot_start_falls_through_and_the_check_runs(tmp_path):
    hooks, bin_ = _setup(tmp_path, broken_python3=True, working_python=True)
    out = _run(hooks, bin_)
    assert out.returncode == 1, (out.returncode, out.stderr)


def test_no_interpreter_fails_open_but_says_so(tmp_path):
    hooks, bin_ = _setup(tmp_path, broken_python3=True, working_python=False)
    out = _run(hooks, bin_)
    assert out.returncode == 0
    assert "did NOT run" in out.stderr


def test_the_bypass_still_bypasses(tmp_path):
    hooks, bin_ = _setup(tmp_path, broken_python3=False, working_python=True)
    env = {"PATH": _posix(str(bin_)), "HOME": str(tmp_path), "SYNDICATE_ALLOW_LEDGER_COMMIT": "1"}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    out = subprocess.run([SH, _posix(str(hooks / "pre-commit"))], capture_output=True, text=True, env=env)
    assert out.returncode == 0

"""`local_production.py status` prints the memory cap a role RUNS with.

Lane `status-effective-memory-cap` (2026-10-08). It printed `PLAN_MEMORY_MB`
("Render plan 2048 MB") whatever the role ran with: live-odds-worker read 2048
there while it ran under 3072. The running cap comes from the role's own env
(built once at `up`); the env file's value is what the NEXT `up` will give.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import pytest

psutil = pytest.importorskip("psutil")

from scripts import local_production as lp


@pytest.mark.parametrize(
    "running,next_up,plan,expected",
    [
        (3072, 3072, 2048, "cap 3072 MB"),
        (3072, None, 2048, "cap 3072 MB"),
        (2048, 3072, 2048, "cap 2048 MB; env file gives 3072 MB at next up"),
        (None, 3072, 2048, "cap ? MB (role env unreadable; env file gives 3072 MB)"),
        (None, None, 2048, "cap ? MB (plan default 2048 MB)"),
        (None, None, None, ""),
    ],
)
def test_label(running, next_up, plan, expected):
    assert lp.memory_cap_label(running, next_up, plan) == expected


def _child(env_extra: dict[str, str]) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if k != lp.MEMORY_LIMIT_KEY}
    env.update(env_extra)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], env=env)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if lp.MEMORY_LIMIT_KEY in psutil.Process(proc.pid).environ() or not env_extra:
                break
        except Exception:
            pass
        time.sleep(0.1)
    return proc


def test_running_cap_is_read_from_the_role_process():
    with_key = _child({lp.MEMORY_LIMIT_KEY: "3072"})
    without = _child({})
    try:
        assert lp.role_running_memory_cap_mb(with_key.pid) == 3072
        assert lp.role_running_memory_cap_mb(without.pid) is None
        assert lp.role_running_memory_cap_mb(None) is None
    finally:
        with_key.kill()
        without.kill()


def test_status_prints_the_running_cap_and_flags_a_pending_env_change(tmp_path, capsys):
    """Off != on at the call site: the old code printed the plan default (2048) here."""
    home = tmp_path / "home"
    settings = lp.Settings(home=home, port=1)  # nothing listens on port 1: /healthz fails fast
    settings.run_dir.mkdir(parents=True)
    settings.logs_dir.mkdir(parents=True)
    settings.env_file.write_text("LIVE_ODDS_WORKER__SYNDICATE_LOCAL_MEMORY_LIMIT_MB=4096\n", encoding="utf-8")
    role = _child({lp.MEMORY_LIMIT_KEY: "3072"})
    try:
        (settings.run_dir / lp.PIDFILE_NAME).write_text(json.dumps({
            "supervisor_pid": os.getpid(), "started_at": "t", "state": "redis", "port": 1,
            "roles": {"live-odds-worker": role.pid},
        }), encoding="utf-8")
        args = argparse.Namespace(home=str(home), port=1, host="127.0.0.1", state="redis",
                                  redis_url=settings.redis_url, lines=0)
        assert lp.cmd_status(args) == 0
        out = capsys.readouterr().out
        assert "cap 3072 MB; env file gives 4096 MB at next up" in out
        assert "Render plan" not in out
    finally:
        role.kill()

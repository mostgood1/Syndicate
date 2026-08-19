"""The roster-rebuild gate on `run_mlb_daily_sim_job.py`. `#440`.

**These tests drive the REAL command construction**, not a reimplementation of
its logic. A hand-rolled copy of the `if` would pass while the wrapper shipped
the opposite, which is the failure mode this lane hit repeatedly: a check that
agrees with your belief instead of with the code.

The gate exists because `daily_update.py --use-roster-artifacts` defaults to
"on" and the wrapper never passed it, so production could not rebuild rosters at
all -- and the engine standard requires a rebuild to land any new input field.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import scripts.run_mlb_daily_sim_job as job  # noqa: E402


class _FakeProc:
    """Popen stand-in. Needs the context-manager protocol because
    `subprocess.run()` wraps Popen in a `with` block, and the checklist hook
    added in `#440` calls `subprocess.run`."""
    returncode = 0
    stdout = ""
    stderr = ""

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def communicate(self, *a, **k):
        return ("", "")

    def kill(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(monkeypatch, tmp_path, gate: str | None, date: str = "2026-08-19"):
    """Invoke the real main() and capture the argv it builds."""
    captured: dict = {}

    def fake_popen(cmd, **kwargs):
        # FIRST daily_update invocation only. The checklist hook also reaches
        # Popen (via subprocess.run), and taking the last call silently replaced
        # the sim command with the checklist's -- which made two passing tests
        # fail for a reason that had nothing to do with the gate.
        if "cmd" not in captured and any("daily_update" in str(t) for t in cmd):
            captured["cmd"] = list(cmd)
        return _FakeProc()

    monkeypatch.setattr(job.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(job, "_hydrate_vendor_oddsapi_mirror", lambda *a, **k: None)
    if gate is None:
        monkeypatch.delenv("SYNDICATE_MLB_ROSTER_REBUILD_DATE", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_MLB_ROSTER_REBUILD_DATE", gate)
    monkeypatch.setattr(sys, "argv", [
        "run_mlb_daily_sim_job.py", "--date", date, "--season", "2026",
        "--sims", "1", "--workers", "1",
    ])
    try:
        job.main()
    except SystemExit:
        pass
    except Exception:
        # main() does plenty after launching; we only care about the argv it
        # built, and Popen is already captured by then.
        pass
    return captured.get("cmd") or []


def _has_rebuild(cmd: list[str]) -> bool:
    """True when the command asks daily_update.py to REBUILD rather than reuse."""
    for i, tok in enumerate(cmd):
        if tok == "--use-roster-artifacts" and i + 1 < len(cmd):
            return cmd[i + 1] == "off"
    return False


def test_absent_gate_does_not_pass_the_flag_at_all(monkeypatch, tmp_path):
    """Absent must mean TODAY'S BEHAVIOUR, not an explicit 'off'.

    The distinction matters: passing `--use-roster-artifacts on` would look
    equivalent but pins a default this wrapper has no business pinning.
    """
    cmd = _run(monkeypatch, tmp_path, None)
    assert cmd, "main() never reached Popen -- the test proves nothing"
    assert "--use-roster-artifacts" not in cmd
    assert not _has_rebuild(cmd)


def test_matching_date_rebuilds(monkeypatch, tmp_path):
    cmd = _run(monkeypatch, tmp_path, "2026-08-19", date="2026-08-19")
    assert cmd, "main() never reached Popen -- the test proves nothing"
    assert _has_rebuild(cmd)


def test_non_matching_date_is_inert(monkeypatch, tmp_path):
    """A gate left set for yesterday must NOT rebuild today.

    This is the whole reason the gate is date-scoped: a rebuild is the expensive
    path, and a forgotten flag would otherwise pay that cost on every run.
    """
    cmd = _run(monkeypatch, tmp_path, "2026-08-18", date="2026-08-19")
    assert cmd, "main() never reached Popen -- the test proves nothing"
    assert not _has_rebuild(cmd)


def test_always_rebuilds(monkeypatch, tmp_path):
    cmd = _run(monkeypatch, tmp_path, "always", date="2026-08-19")
    assert cmd, "main() never reached Popen -- the test proves nothing"
    assert _has_rebuild(cmd)


def test_off_is_not_a_magic_word(monkeypatch, tmp_path):
    """`off` is not a date and not `always`, so it must be INERT.

    Guarding against a plausible mis-set: someone writing `off` expecting it to
    mean "do not rebuild" gets exactly that, by the ordinary date-mismatch path.
    """
    cmd = _run(monkeypatch, tmp_path, "off", date="2026-08-19")
    assert not _has_rebuild(cmd)


# ---------------------------------------------------------------- checklist hook

def _run_capturing_checklist(monkeypatch, gate: str | None, sim_rc: int = 0):
    """Drive the REAL main() and capture whether the checklist subprocess ran."""
    calls: list = []

    class _P:
        returncode = sim_rc

        def poll(self):
            return sim_rc

        def wait(self, timeout=None):
            return sim_rc

    monkeypatch.setattr(job.subprocess, "Popen", lambda cmd, **kw: _P())
    monkeypatch.setattr(job.subprocess, "run",
                        lambda cmd, **kw: calls.append(list(cmd)) or _P())
    monkeypatch.setattr(job, "_hydrate_vendor_oddsapi_mirror", lambda *a, **k: None)
    monkeypatch.setattr(job, "publish_changed_hot_artifacts", lambda *a, **k: 0)
    monkeypatch.setattr(job, "bootstrap_mlb_player_game_log", lambda *a, **k: {})
    monkeypatch.setattr(job, "pull_season_artifacts", lambda *a, **k: 0)
    if gate is None:
        monkeypatch.delenv("SYNDICATE_MLB_INPUT_CHECKLIST", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_MLB_INPUT_CHECKLIST", gate)
    monkeypatch.setattr(sys, "argv", [
        "run_mlb_daily_sim_job.py", "--date", "2026-08-19", "--season", "2026",
        "--sims", "1", "--workers", "1",
    ])
    try:
        job.main()
    except SystemExit:
        pass
    except Exception:
        pass
    return [c for c in calls if any("sim_input_checklist" in str(t) for t in c)]


def test_checklist_runs_by_default(monkeypatch):
    """Default ON is the point: nothing ran this on the worker before."""
    got = _run_capturing_checklist(monkeypatch, None)
    assert got, "checklist did not run with the gate unset"
    assert "--publish" in got[0], "ran without --publish -- the report never leaves the worker"


def test_checklist_gate_off_is_honoured(monkeypatch):
    assert not _run_capturing_checklist(monkeypatch, "off")


def test_checklist_skipped_when_the_sim_failed(monkeypatch):
    """A failed sim leaves rosters half-written; auditing them reports noise."""
    assert not _run_capturing_checklist(monkeypatch, None, sim_rc=1)

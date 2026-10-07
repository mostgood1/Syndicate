"""check_lane_invariants: disjoint DECLARED sections are not reported as a contest.

The guard permits them already; this pins the REPORT agreeing, and -- more importantly --
pins the three cases where it must still fail. The filtering lives in `main()` because
`contested_files`' signature is pinned by `tests/test_lane_guard_prohibition_marker.py`,
which calls it with a claim set; the section declaration lives in the ledger TEXT.

Run end to end through a scratch project dir, which is how this checker is exercised
elsewhere in the repo: it resolves `.syndicate/lanes.md` and `.claude/hooks` relative to
`CLAUDE_PROJECT_DIR`, so a copy run from anywhere else silently finds no ledger at all.
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CHECKER = _ROOT / "scripts/check_lane_invariants.py"

_spec = importlib.util.spec_from_file_location("checker_under_test", _CHECKER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

DOC = "docs/ai_context/local_production_runbook.md"


def _lane(slug, files, status="OPEN"):
    return (f"### {slug} \u2014 {status} \u2014 opened 2026-10-07 \u2014 session s-{slug}\n"
            f"- Goal: whatever\n"
            f"- Files: {files}\n"
            f"- Blocked by: none")


def _project(tmp_path, *blocks):
    """A scratch project dir the checker can actually read."""
    (tmp_path / ".syndicate").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".syndicate" / "lanes.md").write_text(
        "## OPEN\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    shutil.copytree(_ROOT / ".claude" / "hooks", tmp_path / ".claude" / "hooks",
                    dirs_exist_ok=True)
    shutil.copy2(_CHECKER, tmp_path / "scripts" / "check_lane_invariants.py")
    return tmp_path


def _run(project):
    env = {"CLAUDE_PROJECT_DIR": str(project), "PYTHONIOENCODING": "utf-8",
           "SYSTEMROOT": "C:\\Windows", "PATH": "C:\\Windows\\System32"}
    proc = subprocess.run([sys.executable, str(project / "scripts" / "check_lane_invariants.py")],
                          capture_output=True, text=True, cwd=str(project), env=env, timeout=300)
    return proc.stdout + proc.stderr


def test_contested_files_still_takes_a_CLAIM_SET(tmp_path):
    """The signature another test depends on. Changing it broke that file once already."""
    out = mod.contested_files([("a-lane", "x/y.py"), ("b-lane", "x/y.py")])
    assert list(out.values())[0] == ["a-lane", "b-lane"] or set(list(out.values())[0]) == {"a-lane", "b-lane"}


def test_two_different_declared_sections_are_NOT_a_contest(tmp_path):
    out = _run(_project(tmp_path,
                        _lane("watchdog-lane", f"{DOC} (watchdog section only)"),
                        _lane("webreload-lane", f"{DOC} (web reload section only)")))
    assert "DIFFERENT declared" in out, out[-1500:]
    assert "watchdog-lane: watchdog section only" in out
    assert "webreload-lane: web reload section only" in out
    assert "contested file" not in out, "must not also be counted as a failure"


def test_two_lanes_naming_the_SAME_section_ARE_still_a_contest(tmp_path):
    out = _run(_project(tmp_path,
                        _lane("one-lane", f"{DOC} (watchdog section only)"),
                        _lane("two-lane", f"{DOC} (watchdog section only)")))
    assert "contested file" in out, out[-1500:]
    assert "DIFFERENT declared" not in out


def test_one_UNDECLARED_holder_keeps_the_group_contested(tmp_path):
    """The case that would hide a real conflict: a whole-file holder could be editing
    anywhere in the file, so the section holder gets no pass either."""
    out = _run(_project(tmp_path,
                        _lane("section-lane", f"{DOC} (watchdog section only)"),
                        _lane("whole-file-lane", DOC)))
    assert "contested file" in out, out[-1500:]
    assert "DIFFERENT declared" not in out


def test_an_ordinary_contest_is_untouched(tmp_path):
    out = _run(_project(tmp_path,
                        _lane("p-lane", "syndicate/features/shared/thing.py"),
                        _lane("q-lane", "syndicate/features/shared/thing.py")))
    assert "contested file" in out
    assert "DIFFERENT declared" not in out

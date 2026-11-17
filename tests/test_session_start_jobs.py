"""scripts/session_start_jobs.py, and the session-start hook that reads it.

Lane session-start-hook-runtime (2026-11-16). The hook now starts every python check at once
through this runner instead of one after another. The runner tests pin the contract the hook
decodes. The hook tests run the REAL hook against a fixture tree of stub scripts. They prove each
result reaches its line (off != on), and that the hook still exits 0 with no traceback when
python, the runner, or any one script is missing.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import session_start_jobs as ssj  # noqa: E402

HOOK = REPO / ".claude" / "hooks" / "session-start.sh"
RUNNER = REPO / "scripts" / "session_start_jobs.py"


# ---------------------------------------------------------------- runner: pure functions

@pytest.mark.parametrize("raw,cap,expected", [
    # measured in Git Bash 5.2.37: $(...) strips trailing \n and \r\n, keeps a lone trailing \r
    (b"line\r\n", 0, b"line"),
    (b"a\r\nb\r\nc\rd\r\n\r\n", 0, b"a\r\nb\r\nc\rd"),
    (b"a\r\r\n\n", 0, b"a\r"),
    (b"a\r", 0, b"a\r"),
    (b"a\n\r", 0, b"a\n\r"),
    (b"", 0, b""),
    (b"a\0b\n", 0, b"ab"),
    # head -c CAP happens BEFORE the strip
    (b"abcdef\n", 3, b"abc"),
    (b"ab\ncd", 3, b"ab"),
    (b"\xe2\x80\x94\xe2\x80\x94", 4, b"\xe2\x80\x94\xe2"),
])
def test_as_command_substitution(raw, cap, expected):
    assert ssj.as_command_substitution(raw, cap) == expected


def test_parse_job():
    assert ssj.parse_job("todo_id_reconcile.py --no-history|-1|scripts/todo_id_reconcile.py --no-history") == (
        "todo_id_reconcile.py --no-history", -1, ["scripts/todo_id_reconcile.py", "--no-history"])
    assert ssj.parse_job("census|600|scripts/lane_census.py --digest") == (
        "census", 600, ["scripts/lane_census.py", "--digest"])
    for bad in ("nocap", "k|x|scripts/a.py", "|0|scripts/a.py", "k|0|"):
        with pytest.raises(ValueError):
            ssj.parse_job(bad)


def test_escape_is_one_line_and_doubles_every_backslash():
    raw = b"a\\b\nc\rd\te \\n"
    esc = ssj.escape(raw)
    assert b"\n" not in esc and b"\r" not in esc and b"\t" not in esc
    assert esc == b"a\\\\b\\nc\\rd\\te \\\\n"


# ---------------------------------------------------------------- runner: end to end

def _script(tmp, name, body):
    p = tmp / "scripts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _run_runner(tmp, *specs, deadline=None):
    args = [sys.executable, str(RUNNER)]
    if deadline is not None:
        args += ["--deadline", str(deadline)]
    p = subprocess.run(args + list(specs), cwd=str(tmp), capture_output=True, timeout=60)
    lines = p.stdout.split(b"\n")
    return p, lines


def test_runner_reports_rc_output_missing_and_end(tmp_path):
    _script(tmp_path, "ok.py", "print('hello world')\n")
    _script(tmp_path, "fail.py", "import sys; print('noise'); sys.exit(3)\n")
    _script(tmp_path, "args.py", "import sys; print(' '.join(sys.argv[1:]))\n")
    p, lines = _run_runner(tmp_path, "ok|0|scripts/ok.py", "fail|-1|scripts/fail.py",
                           "gone|0|scripts/gone.py", "args|5|scripts/args.py --digest x")
    assert p.returncode == 0
    assert p.stderr == b""
    assert lines[0] == b"ok\t0\thello world"
    assert lines[1] == b"fail\t3\t"            # CAP -1: stdout discarded, exit code kept
    assert lines[2] == b"gone\tmissing\t"
    assert lines[3] == b"args\t0\t--dig"        # cut to 5 bytes like head -c 5
    assert lines[4] == b"@@END\t4"


def test_runner_runs_jobs_side_by_side(tmp_path):
    for i in range(4):
        _script(tmp_path, "s%d.py" % i, "import time; time.sleep(1.5)\n")
    t0 = time.monotonic()
    p, lines = _run_runner(tmp_path, *["s%d|-1|scripts/s%d.py" % (i, i) for i in range(4)])
    took = time.monotonic() - t0
    assert [l.split(b"\t")[1] for l in lines[:4]] == [b"0"] * 4
    # serial would be >= 6 s; concurrent is one sleep plus interpreter starts
    assert took < 5.0, took


def test_runner_kills_a_check_at_the_deadline(tmp_path):
    _script(tmp_path, "hang.py", "import time; time.sleep(30)\n")
    _script(tmp_path, "ok.py", "print('fine')\n")
    t0 = time.monotonic()
    p, lines = _run_runner(tmp_path, "hang|-1|scripts/hang.py", "ok|0|scripts/ok.py", deadline=2)
    assert time.monotonic() - t0 < 15
    assert lines[0] == b"hang\ttimeout\t"
    assert lines[1] == b"ok\t0\tfine"
    assert lines[2] == b"@@END\t2"


def test_runner_malformed_spec_exits_1_without_end_or_traceback(tmp_path):
    p, _ = _run_runner(tmp_path, "no-separators-here")
    assert p.returncode == 1
    assert b"@@END" not in p.stdout
    assert b"Traceback" not in p.stderr


# ---------------------------------------------------------------- the hook, on a fixture tree

def _bash():
    if os.name == "nt":
        for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if os.path.isfile(c):
                return c
        return None
    return shutil.which("bash")


BASH = _bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="needs Git Bash / bash")

STUBS = {
    "lane_census.py": """
        import sys
        if "--budget-digest" in sys.argv:
            print("OPEN 9KB/3 lanes, archivable 1KB")
        else:
            print("3 OPEN / 0 UNOWNED (stub census)")
    """,
    "lane_identity_check.py": "pass\n",
    "check_lane_invariants.py": "import sys; print('VIOLATED'); sys.exit(1)\n",
    "check_lane_claims.py": "pass\n",
    "state_key_check.py": "pass\n",
    "todo_id_reconcile.py": "pass\n",
    "primary_tree_ff.py": """
        import sys
        if "--digest" in sys.argv:
            print("PRIMARY TREE NOT AUTO-UPDATED (stub)")
    """,
    "betting_change.py": "print('BETTING CHANGES: 1 load unclassified (stub)')\n",
}


def _fixture(tmp, lanes_bytes=0):
    tree = tmp / "tree"
    syn = tree / ".syndicate"
    syn.mkdir(parents=True)
    lanes = "# lanes\n\n## OPEN\n\n### a-lane — OPEN — opened 2026-11-16 — session x\n- Goal: g\n"
    if lanes_bytes:
        lanes += "x" * lanes_bytes + "\n"
    (syn / "lanes.md").write_text(lanes, encoding="utf-8")
    (syn / "learnings.md").write_text("## 2026-11-16 — FORBIDDEN: a stub rule\n", encoding="utf-8")
    (syn / "deploys.md").write_text("<pending>\n- RECONCILED: x\n", encoding="utf-8")
    (syn / "state.md").write_text("# state\n", encoding="utf-8")
    (tree / "scripts").mkdir()
    for name, body in STUBS.items():
        (tree / "scripts" / name).write_text(textwrap.dedent(body), encoding="utf-8")
    shutil.copy(RUNNER, tree / "scripts" / "session_start_jobs.py")
    return tree


def _env(tree, with_python=True):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env["CLAUDE_PROJECT_DIR"] = str(tree)
    env["SYNDICATE_PRIMARY_FF"] = "off"
    if os.name == "nt":
        usr_bin = str(Path(BASH).parents[1] / "usr" / "bin")
        dirs = [usr_bin]
        if with_python:
            dirs.insert(0, os.path.dirname(sys.executable))
        env["PATH"] = os.pathsep.join(dirs)
    else:
        bindir = tree.parent / "bin"
        bindir.mkdir(exist_ok=True)
        shim = bindir / "python"
        if with_python and not shim.exists():
            shim.symlink_to(sys.executable)
        env["PATH"] = os.pathsep.join([str(bindir), "/usr/bin", "/bin"])
    return env


def _hook(tree, with_python=True):
    p = subprocess.run([BASH, str(HOOK)], cwd=str(tree), env=_env(tree, with_python),
                       capture_output=True, timeout=120)
    return p, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


@needs_bash
def test_hook_reads_every_result_into_its_line(tmp_path):
    tree = _fixture(tmp_path, lanes_bytes=560000)   # lanes.md over its 550000 cap
    p, out, err = _hook(tree)
    assert p.returncode == 0, err
    assert "Traceback" not in err
    assert "3 OPEN / 0 UNOWNED (stub census)" in out
    assert "(census unavailable)" not in out
    assert "(OPEN 9KB/3 lanes, archivable 1KB)" in out          # the budget job, via WHERE
    assert "LEDGER INCOHERENT: lanes.md (scripts/check_lane_invariants.py)" in out
    assert "lane_identity_check" not in out                    # rc 0 checks are not flagged
    assert "PRIMARY TREE NOT AUTO-UPDATED (stub)" in out
    assert "BETTING CHANGES: 1 load unclassified (stub)" in out
    assert "NOT RUN" not in out and "no result" not in out and "NOT FINISHED" not in out


@needs_bash
def test_hook_off_vs_on_every_check_passing(tmp_path):
    tree = _fixture(tmp_path)
    (tree / "scripts" / "check_lane_invariants.py").write_text("pass\n", encoding="utf-8")
    p, out, err = _hook(tree)
    assert p.returncode == 0, err
    assert "LEDGER INCOHERENT" not in out
    assert "LEDGER OVER BUDGET" not in out                     # lanes.md under cap: no WHERE text
    assert "archivable" not in out


@needs_bash
def test_hook_fails_open_without_python(tmp_path):
    tree = _fixture(tmp_path)
    p, out, err = _hook(tree, with_python=False)
    assert p.returncode == 0, err
    assert "Traceback" not in err
    assert "(census unavailable)" in out
    assert "LEDGER INCOHERENT" not in out
    assert "=== end digest" in out


@needs_bash
def test_hook_says_so_when_the_runner_is_missing(tmp_path):
    tree = _fixture(tmp_path)
    (tree / "scripts" / "session_start_jobs.py").unlink()
    p, out, err = _hook(tree)
    assert p.returncode == 0, err
    assert "Traceback" not in err
    assert "[python checks NOT RUN: scripts/session_start_jobs.py is missing]" in out
    assert "(census unavailable)" in out
    assert "=== end digest" in out


@needs_bash
def test_hook_says_so_when_the_runner_dies(tmp_path):
    tree = _fixture(tmp_path)
    (tree / "scripts" / "session_start_jobs.py").write_text("import sys; sys.exit(1)\n", encoding="utf-8")
    p, out, err = _hook(tree)
    assert p.returncode == 0, err
    assert "[python checks: runner ended with no result" in out
    assert "LEDGER INCOHERENT" not in out
    assert "=== end digest" in out


@needs_bash
@pytest.mark.parametrize("missing", sorted(STUBS))
def test_hook_fails_open_with_any_one_script_missing(tmp_path, missing):
    tree = _fixture(tmp_path)
    (tree / "scripts" / missing).unlink()
    p, out, err = _hook(tree)
    assert p.returncode == 0, err
    assert "Traceback" not in err and "Traceback" not in out
    assert "=== end digest" in out
    assert "NOT RUN" not in out and "no result" not in out
    if missing == "lane_census.py":
        assert "(census unavailable)" in out
    if missing == "check_lane_invariants.py":
        assert "LEDGER INCOHERENT" not in out       # skipped, as the old `[ -f ]` guard did
    else:
        assert "LEDGER INCOHERENT: lanes.md (scripts/check_lane_invariants.py)" in out

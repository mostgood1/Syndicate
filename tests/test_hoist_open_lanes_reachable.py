"""`hoist_open_lanes.py` must survive the path where it has work to do.

MEASURED 2026-10-09: the tool crashed with `NameError: name '__file__' is not
defined` whenever a lane block actually sat below `## Archived lanes` -- the one
condition it exists to repair, and the one the `ledger-postwrite` guard tells
every session to fix with `py -3 scripts/hoist_open_lanes.py --apply`.

WHY IT WENT UNNOTICED. `guard_claims()` is only called once the tool has found
something to move, so on a clean `lanes.md` the tool printed "nothing to move"
and exited 0 -- a dry run against a healthy ledger could never see it. This is
the reachability-before-correctness rule in CLAUDE.md: prove the branch RUNS
before testing what it returns.

The cause was `exec`ing `.claude/hooks/lane-guard.py` into a bare module dict,
which defines no `__file__`; that hook does
`sys.path.insert(0, dirname(abspath(__file__)))` at import to reach `lane_claims`.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TOOL = _ROOT / "scripts/hoist_open_lanes.py"
EM = chr(8212)
NL = chr(10)


def _project(tmp_path, stranded: bool):
    """A scratch project the tool can read.

    It resolves `.syndicate/lanes.md` and `.claude/hooks/lane-guard.py` RELATIVE TO
    CWD, not to CLAUDE_PROJECT_DIR, so this must run it with cwd set here. Setting
    the env var alone silently reads the REAL repo ledger instead -- which is how a
    first attempt at this test "passed" against a clean file and proved nothing.
    """
    (tmp_path / ".syndicate").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copytree(_ROOT / ".claude" / "hooks", tmp_path / ".claude" / "hooks",
                    dirs_exist_ok=True)
    shutil.copy2(_TOOL, tmp_path / "scripts" / "hoist_open_lanes.py")
    # the tool imports scripts/ledger_io.py (byte-safe ledger read/write), and it
    # resolves that by sys.path[0] = the script's own directory
    shutil.copy2(_ROOT / "scripts/ledger_io.py", tmp_path / "scripts" / "ledger_io.py")
    blocks = [
        "### a-normal-open-lane " + EM + " OPEN " + EM + " opened 2026-10-09 " + EM + " session s-aaaa",
        "- Goal: a lane that is already in the right place",
        "- Files: scripts/nothing_real_aaaa.py",
        "- Blocked by: none",
        "",
        "## Archived lanes (full bodies in `lanes_closed.md`)",
        "",
    ]
    if stranded:
        blocks += [
            "### stranded-open-lane " + EM + " OPEN " + EM + " opened 2026-10-09 " + EM + " session s-bbbb",
            "- Goal: this block sits BELOW the archive marker, so its claims are unenforced",
            "- Files: scripts/nothing_real_bbbb.py",
            "- Blocked by: none",
        ]
    text = "# Lanes" + NL + NL + "## OPEN" + NL + NL + NL.join(blocks) + NL
    with open(tmp_path / ".syndicate" / "lanes.md", "w", encoding="utf-8",
              newline=NL) as fh:
        fh.write(text)
    return tmp_path


def _run(project, *args):
    return subprocess.run(
        [sys.executable, str(project / "scripts" / "hoist_open_lanes.py"), *args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(project), timeout=300)


def test_the_tool_does_not_crash_when_it_HAS_work(tmp_path):
    """The reachability test -- this is the case that raised NameError."""
    r = _run(_project(tmp_path, stranded=True))
    combined = r.stdout + r.stderr
    assert "NameError" not in combined, combined[-1200:]
    assert r.returncode == 0, combined[-1200:]
    assert "stranded-open-lane" in r.stdout


def test_dry_run_writes_nothing(tmp_path):
    p = _project(tmp_path, stranded=True)
    before = (p / ".syndicate" / "lanes.md").read_bytes()
    r = _run(p)
    assert r.returncode == 0
    assert "DRY RUN" in r.stdout
    assert (p / ".syndicate" / "lanes.md").read_bytes() == before


def test_apply_moves_the_block_inside_the_open_section(tmp_path):
    p = _project(tmp_path, stranded=True)
    r = _run(p, "--apply")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1200:]
    lines = (p / ".syndicate" / "lanes.md").read_text(encoding="utf-8").split(NL)
    oh = next(i for i, l in enumerate(lines) if l.startswith("## OPEN"))
    ah = next(i for i, l in enumerate(lines) if l.startswith("## Archived lanes"))
    st = [i for i, l in enumerate(lines) if l.startswith("### stranded-open-lane")]
    assert len(st) == 1, "the block must not be duplicated"
    assert oh < st[0] < ah, "the block must end up inside ## OPEN"


def test_a_clean_ledger_is_a_no_op(tmp_path):
    """The control. Without it, the crash test could pass for the wrong reason --
    the tool exiting 0 because it found nothing at all."""
    r = _run(_project(tmp_path, stranded=False))
    assert r.returncode == 0, (r.stdout + r.stderr)[-800:]
    assert "nothing to move" in r.stdout


def test_apply_leaves_a_mid_line_bare_CR_intact(tmp_path):
    """End-to-end byte safety, not just the helper in isolation.

    lanes.md carries exactly one mid-line bare CR, inside a peer's verdict line.
    Before scripts/ledger_io.py every one of these tools read with universal
    newlines, which maps that CR to a line break -- splitting the line. 74da0acd
    had to repair that split once, and archive_released_lanes.py reproduced it.
    """
    p = _project(tmp_path, stranded=True)
    lanes = p / ".syndicate" / "lanes.md"
    raw = lanes.read_bytes()
    marker = b"- Goal: this block sits BELOW the archive marker"
    assert raw.count(marker) == 1
    # plant a bare CR mid-line, exactly the shape lanes.md has
    planted = raw.replace(marker, b"- Goal: payload cut from 68 MB" + bytes([13])
                          + b'" -- below the archive marker', 1)
    lanes.write_bytes(planted)
    lone = lambda b: b.count(bytes([13])) - b.count(bytes([13, 10]))
    assert lone(planted) == 1

    r = _run(p, "--apply")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1200:]
    after = lanes.read_bytes()
    assert lone(after) == 1, "the bare CR was consumed -- the line was split"
    kept = [l for l in after.split(bytes([10])) if b"68 MB" in l]
    assert len(kept) == 1, "the line was split at the bare CR"
    assert b"below the archive marker" in kept[0], "the halves are no longer one line"

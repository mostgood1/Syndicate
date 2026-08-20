#!/usr/bin/env python3
"""Tests for `ledger-append-guard.py` -- reachability, and NOT crying wolf.

Run: py -3 .claude/hooks/test_ledger_append_guard.py

WHY THIS EXISTS. The guard identified its target with
`relpath(file_path, CLAUDE_PROJECT_DIR) in (LANES, STATE)`. Every session works
in its own linked worktree (`scripts/session_worktree.py`), so that relpath was
`../../../../../tmp/syndicate-sessions/<lane>/.syndicate/state.md` and the guard
returned 0 before evaluating any predicate.

MEASURED 2026-08-20, the identical violating edit against both trees:

    primary tree   exit=2  BLOCKED
    worktree       exit=0  ALLOWED   <- the guard never ran

An inert guard and a satisfied guard look the same from outside, which is how
this survived: it read as "passing".

THE BULK OF THIS FILE IS FALSE-POSITIVE CASES, on purpose. Turning the guard on
for every worktree session only helps if it stays silent on the edits people
actually make -- editing a lane block in place, opening a new lane, correcting a
line in state.md. `learnings.md` records that a guard which blocks correct work
is one people route around, which costs more than the guard was worth.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HOOKS, "ledger-append-guard.py")

LANES = "# Lanes\n\n### alpha — OPEN\n- Goal: x\n\n### beta — OPEN\n- Goal: y\n\n## Archived lanes\n\n### gamma — CLOSED\n- done\n"
STATE = "# State\n\n## [odds] sources\nFoo is live.\n\n## [sim] engine\nBar is live.\n"


def _write(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def _ask(path, tool_input, project_dir, tool="Edit"):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir)
    env.pop("SYNDICATE_LEDGER_GUARD", None)
    ti = dict(tool_input)
    ti["file_path"] = path
    payload = {"tool_name": tool, "tool_input": ti,
               "cwd": os.path.dirname(path)}
    p = subprocess.run([sys.executable, GUARD], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stderr


def main():
    base = tempfile.mkdtemp(prefix="append_guard_test_")
    results = []

    def check(label, got, want):
        results.append((label, got, want))

    try:
        # Two independent trees. `primary` stands in for CLAUDE_PROJECT_DIR;
        # `wt` stands in for a session worktree. Neither is the real repo.
        primary = os.path.join(base, "primary")
        wt = os.path.join(base, "worktree")
        for tree in (primary, wt):
            _write(tree, ".syndicate/lanes.md", LANES)
            _write(tree, ".syndicate/state.md", STATE)

        wt_lanes = os.path.join(wt, ".syndicate", "lanes.md")
        wt_state = os.path.join(wt, ".syndicate", "state.md")
        pr_state = os.path.join(primary, ".syndicate", "state.md")

        # ---- REACHABILITY: the bug this fixes ---------------------------
        dated = {"old_string": "## [odds] sources",
                 "new_string": "## [odds] sources\n\n### 2026-08-20 a dated note\n"}
        check("state.md dated heading, PRIMARY tree -> block",
              _ask(pr_state, dated, primary)[0], 2)
        check("state.md dated heading, WORKTREE -> block (was silently inert)",
              _ask(wt_state, dated, primary)[0], 2)

        dupe = {"old_string": "### beta — OPEN\n- Goal: y",
                "new_string": "### beta — OPEN\n- Goal: y\n\n### alpha — OPEN\n- Goal: second block"}
        check("lanes.md second block for an existing lane, WORKTREE -> block",
              _ask(wt_lanes, dupe, primary)[0], 2)

        below = {"old_string": "### gamma — CLOSED\n- done",
                 "new_string": "### gamma — CLOSED\n- done\n\n### delta — OPEN\n- Goal: z"}
        check("lanes.md new block BELOW the archive marker, WORKTREE -> block",
              _ask(wt_lanes, below, primary)[0], 2)

        # ---- NOT CRYING WOLF: the edits people actually make -------------
        check("editing an existing lane block IN PLACE -> allow",
              _ask(wt_lanes, {"old_string": "- Goal: y",
                              "new_string": "- Goal: y, revised today"}, primary)[0], 0)

        check("opening a NEW lane above the archive marker -> allow",
              _ask(wt_lanes, {"old_string": "### beta — OPEN\n- Goal: y",
                              "new_string": "### beta — OPEN\n- Goal: y\n\n### delta — OPEN\n- Goal: z"},
                   primary)[0], 0)

        check("closing a lane (status text change) -> allow",
              _ask(wt_lanes, {"old_string": "### alpha — OPEN",
                              "new_string": "### alpha — CLOSED"}, primary)[0], 0)

        check("correcting a line in state.md -> allow",
              _ask(wt_state, {"old_string": "Foo is live.",
                              "new_string": "Foo was retired 2026-08-20."}, primary)[0], 0)

        check("a NON-dated new ## section in state.md -> allow",
              _ask(wt_state, {"old_string": "## [sim] engine",
                              "new_string": "## [live] lens\nNew.\n\n## [sim] engine"},
                   primary)[0], 0)

        check("Write tool replacing lanes.md with clean content -> allow",
              _ask(wt_lanes, {"content": LANES.replace("Goal: y", "Goal: y2")},
                   primary, tool="Write")[0], 0)

        check("Write tool introducing a duplicate block -> block",
              _ask(wt_lanes, {"content": LANES + "\n### alpha — OPEN\n- dupe\n"},
                   primary, tool="Write")[0], 2)

        check("MultiEdit, all edits benign -> allow",
              _ask(wt_lanes, {"edits": [
                  {"old_string": "- Goal: x", "new_string": "- Goal: x1"},
                  {"old_string": "- Goal: y", "new_string": "- Goal: y1"}]},
                   primary, tool="MultiEdit")[0], 0)

        # ---- SCOPE: files that merely share a name ----------------------
        other = _write(wt, "docs/lanes.md", LANES + "\n### alpha — OPEN\n- dupe\n")
        check("docs/lanes.md is NOT the ledger -> allow",
              _ask(other, {"old_string": "- Goal: x", "new_string": "- Goal: x1"},
                   primary)[0], 0)

        code, _ = _ask(os.path.join(wt, "syndicate", "app.py"),
                       {"old_string": "a", "new_string": "b"}, primary)
        check("an ordinary source file is ignored", code, 0)

        # ---- FAIL OPEN ---------------------------------------------------
        check("old_string not present -> fails open",
              _ask(wt_lanes, {"old_string": "NOT IN THE FILE",
                              "new_string": "x"}, primary)[0], 0)
        check("a missing file -> fails open",
              _ask(os.path.join(wt, ".syndicate", "gone.md"),
                   {"old_string": "a", "new_string": "b"}, primary)[0], 0)
        check("off switch honoured",
              _ask(pr_state, dated, primary)[0] if os.environ.get("X") else
              subprocess.run([sys.executable, GUARD],
                             input=json.dumps({"tool_name": "Edit",
                                               "tool_input": dict(dated, file_path=pr_state)}),
                             capture_output=True, text=True,
                             env=dict(os.environ, CLAUDE_PROJECT_DIR=primary,
                                      SYNDICATE_LEDGER_GUARD="off")).returncode, 0)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    failed = 0
    for label, got, want in results:
        ok = got == want
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  exit={got} want={want}  {label}")
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

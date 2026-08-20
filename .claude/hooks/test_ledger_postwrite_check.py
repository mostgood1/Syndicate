#!/usr/bin/env python3
"""Tests for `ledger-postwrite-check.py` -- which trees it watches, and dedup.

Run: py -3 .claude/hooks/test_ledger_postwrite_check.py

WHY THIS EXISTS. The hook resolved a single `root` from `CLAUDE_PROJECT_DIR`,
the PRIMARY checkout, while the Bash command it reacts to runs in the session's
own linked worktree. A Bash write is the ONLY thing this hook exists to catch,
and worktree Bash writes were invisible to it -- so a session could break its own
lanes.md from Bash and hear nothing from any of the three guards.

The other half was misattribution: watching only the shared tree means the file
changes under sessions that did not touch it, and each of them announced
"BROKEN by a write just now". Observed 2026-08-20 against a session whose
command was a `grep`. The hook sees a (mtime, size) change, never an author.

Every case builds throwaway trees -- never the live ledger, which a parallel
session can rewrite mid-run.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HOOKS, "ledger-postwrite-check.py")

CLEAN = "# Lanes\n\n### alpha — OPEN\n- Goal: x\n\n### beta — OPEN\n- Goal: y\n"
DUPE = CLEAN + "\n### alpha — OPEN\n- Goal: a second block\n"


def _tree(base, name, lanes):
    root = os.path.join(base, name)
    os.makedirs(os.path.join(root, ".syndicate"), exist_ok=True)
    with open(os.path.join(root, ".syndicate", "lanes.md"), "w", encoding="utf-8") as fh:
        fh.write(lanes)
    subprocess.run(["git", "init", "-q"], capture_output=True, cwd=root)
    return root


def _run(cwd, project_dir, tmpdir):
    """Invoke the hook as PostToolUse(Bash) would. Returns (exit, stderr)."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir,
               TMPDIR=tmpdir, TEMP=tmpdir, TMP=tmpdir)
    env.pop("SYNDICATE_LEDGER_POSTCHECK", None)
    payload = {"tool_name": "Bash", "tool_input": {"command": "grep -n x file"},
               "cwd": cwd}
    p = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stderr


def _touch(root, text):
    """Rewrite lanes.md so its (mtime, size) signature changes."""
    p = os.path.join(root, ".syndicate", "lanes.md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def main():
    base = tempfile.mkdtemp(prefix="postwrite_test_")
    results = []

    def check(label, got, want):
        results.append((label, got, want))

    try:
        # Each case gets its own state dir so dedup state never leaks between them.
        def statedir(n):
            d = os.path.join(base, "state%d" % n)
            os.makedirs(d, exist_ok=True)
            return d

        # ---- REACHABILITY: the bug this fixes --------------------------
        wt = _tree(base, "wt_broken", DUPE)
        primary = _tree(base, "primary_clean", CLEAN)
        code, err = _run(wt, primary, statedir(1))
        check("broken WORKTREE + clean primary -> warn (was invisible)", code, 2)
        # The hook names the tree in git's spelling (long Windows path, forward
        # slashes); `wt` is the raw tempdir string, which may be 8.3 short with
        # backslashes. Compare resolved, or this asserts on path formatting.
        def _norm(s):
            return os.path.normcase(os.path.realpath(s)).replace("\\", "/")
        check("  ...and names the worktree it found it in",
              _norm(wt) in _norm(err.split("(in ")[1].split(")")[0])
              if "(in " in err else False, True)

        # ---- MISATTRIBUTION ---------------------------------------------
        code, err = _run(primary, _tree(base, "p2", DUPE), statedir(2))
        check("broken PRIMARY while session sits elsewhere -> still warn", code, 2)
        check("  ...no longer claims the session wrote it",
              "by a write just now" in err, False)
        check("  ...says the change may be another session's",
              "not who made it" in err, True)

        # ---- TRANSITION, NOT STATE --------------------------------------
        sd = statedir(3)
        wt2 = _tree(base, "wt_twice", DUPE)
        clean_p = _tree(base, "p_clean2", CLEAN)
        first = _run(wt2, clean_p, sd)[0]
        second = _run(wt2, clean_p, sd)[0]
        check("first sighting warns", first, 2)
        check("unchanged file is SILENT on the next call", second, 0)
        _touch(wt2, DUPE + "\n### beta — OPEN\n- and another\n")
        check("re-warns after the file changes again", _run(wt2, clean_p, sd)[0], 2)

        # ---- PER-TREE STATE ----------------------------------------------
        sd = statedir(4)
        a = _tree(base, "tree_a", DUPE)
        b = _tree(base, "tree_b", DUPE)
        check("worktree reported on first call", _run(a, b, sd)[0], 2)
        check("both trees deduped after being seen once", _run(a, b, sd)[0], 0)

        # ---- QUIET WHEN CLEAN --------------------------------------------
        sd = statedir(5)
        c1 = _tree(base, "clean_a", CLEAN)
        c2 = _tree(base, "clean_b", CLEAN)
        check("both trees clean -> silent", _run(c1, c2, sd)[0], 0)

        # ---- SAME TREE TWICE IS NOT REPORTED TWICE ------------------------
        sd = statedir(6)
        one = _tree(base, "same_tree", DUPE)
        code, err = _run(one, one, sd)
        check("cwd == CLAUDE_PROJECT_DIR -> deduped to one root", code, 2)
        check("  ...reported exactly once",
              err.count(".syndicate/lanes.md"), 1)

        # ---- FAIL OPEN ----------------------------------------------------
        sd = statedir(7)
        check("a non-Bash tool is ignored",
              subprocess.run([sys.executable, HOOK],
                             input=json.dumps({"tool_name": "Edit",
                                               "tool_input": {}, "cwd": one}),
                             capture_output=True, text=True,
                             env=dict(os.environ, CLAUDE_PROJECT_DIR=one,
                                      TMPDIR=sd, TEMP=sd, TMP=sd)).returncode, 0)
        check("off switch honoured",
              subprocess.run([sys.executable, HOOK],
                             input=json.dumps({"tool_name": "Bash",
                                               "tool_input": {"command": "ls"},
                                               "cwd": one}),
                             capture_output=True, text=True,
                             env=dict(os.environ, CLAUDE_PROJECT_DIR=one,
                                      TMPDIR=statedir(8), TEMP=statedir(8),
                                      TMP=statedir(8),
                                      SYNDICATE_LEDGER_POSTCHECK="off")).returncode, 0)
        check("a cwd that does not exist -> falls back, does not crash",
              _run(os.path.join(base, "nope"), c1, statedir(9))[0], 0)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    failed = 0
    for label, got, want in results:
        ok = got == want
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  got={got} want={want}  {label}")
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

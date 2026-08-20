#!/usr/bin/env python3
"""Tests for `ledger-commit-guard.py` -- WHICH TREE it reads, and WHICH ENV.

Run: py -3 .claude/hooks/test_ledger_commit_guard.py

EVERY CASE BUILDS ITS OWN THROWAWAY REPOS. The first version of this suite
asserted against the live primary tree, which happened to have two duplicated
lane blocks at the time. A parallel session trimmed them mid-run and three cases
flipped -- the guard was correct and the TEST was stale. A guard test that
depends on shared mutable state measures the ledger, not the guard.

WHAT REGRESSED HERE ONCE (2026-08-20), and what these cases pin:

  WHICH TREE  `root` was `CLAUDE_PROJECT_DIR` -- the PRIMARY checkout -- while
              the commit runs wherever the shell is. Sessions live in their own
              worktrees (`scripts/session_worktree.py`), so the guard read a
              DIFFERENT REPOSITORY than the one being committed. Measured: a
              session in `C:/tmp/syndicate-sessions/soccer-board-mlb-parity` was
              blocked over duplicate lane blocks that existed only in the
              primary tree; its own `lanes.md` was clean and
              `check_lane_invariants.py` said INVARIANTS HOLD there.

              Both directions matter. The false POSITIVE blocks honest work and
              -- worse -- printed `trim_lane_blocks.py --apply` as the remedy,
              which run in the tree being complained about would rewrite OTHER
              sessions' lane blocks to satisfy a check about a file the
              committing session never touched. The false NEGATIVE is the half
              `commit-guard.py`'s docstring calls the one that matters: a broken
              lanes.md in the committing worktree was never examined at all.

  WHICH ENV   `SYNDICATE_ALLOW_LEDGER_COMMIT=1 git commit ...` as an inline
              prefix is still just TEXT when a PreToolUse hook runs -- the shell
              has not assigned it yet -- so `os.environ.get` never saw it. The
              documented escape hatch did not exist.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HOOKS, "ledger-commit-guard.py")

# Split so this file's own text never matches the guard's COMMIT_RE when a
# session greps or cats it inside a Bash command.
GC = "git " + "commit"

CLEAN_LANES = "# Lanes\n\n### alpha — OPEN\n- Goal: x\n\n### beta — OPEN\n- Goal: y\n"
DUPE_LANES = CLEAN_LANES + "\n### alpha — OPEN\n- Goal: a second block\n"


def _mkrepo(base, name, lanes_text):
    root = os.path.join(base, name)
    os.makedirs(os.path.join(root, ".syndicate"))
    q = dict(capture_output=True, cwd=root)
    subprocess.run(["git", "init", "-q"], **q)
    subprocess.run(["git", "config", "user.email", "t@t"], **q)
    subprocess.run(["git", "config", "user.name", "t"], **q)
    with open(os.path.join(root, ".syndicate", "lanes.md"), "w", encoding="utf-8") as fh:
        fh.write(lanes_text)
    return root


def _ask(cmd, cwd, project_dir, env_extra=None):
    """Run the hook as Claude Code would, and return (exit, stderr)."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir)
    env.pop("SYNDICATE_ALLOW_LEDGER_COMMIT", None)
    env.update(env_extra or {})
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}
    p = subprocess.run([sys.executable, GUARD], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, cwd=cwd)
    return p.returncode, p.stderr


def main():
    base = tempfile.mkdtemp(prefix="ledger_guard_test_")
    results = []

    def check(label, got, want, extra_ok=True):
        results.append((label, got, want, extra_ok))

    try:
        dupe = _mkrepo(base, "dupe_tree", DUPE_LANES)
        clean = _mkrepo(base, "clean_tree", CLEAN_LANES)
        lanes_rel = ".syndicate/lanes.md"

        # ---- WHICH TREE -------------------------------------------------
        code, err = _ask(f"{GC} -m x -- {lanes_rel}", clean, dupe)
        check("clean tree committed, DIRTY primary -> allow (was the false block)",
              code, 0)

        code, err = _ask(f"{GC} -m x -- {lanes_rel}", dupe, clean)
        check("dirty tree committed, CLEAN primary -> block (the false negative)",
              code, 2, "MORE THAN ONE block" in err)

        # Compare against git's OWN spelling of the root. `mkdtemp` hands back a
        # Windows 8.3 short path (`C:\Users\TEMPAD~1\...`) while
        # `rev-parse --show-toplevel` returns the long form, so asserting on the
        # tempdir string fails for a reason that has nothing to do with the guard.
        toplevel = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True,
                                  cwd=dupe).stdout.strip()
        code, err = _ask(f"{GC} -m x -- {lanes_rel}", dupe, dupe)
        check("refusal names the tree it actually read",
              code, 2, bool(toplevel) and toplevel in err)

        code, err = _ask(f"cd {clean} && {GC} -m x -- {lanes_rel}", dupe, dupe)
        check("a `cd` before the commit is followed", code, 0)

        code, err = _ask(f"git -C {clean} commit -m x -- {lanes_rel}", dupe, dupe)
        check("`-C <dir>` on the invocation is followed", code, 0)

        code, err = _ask(f"cd {dupe} && {GC} -m x -- {lanes_rel}", clean, clean)
        check("`cd` INTO a dirty tree is followed too", code, 2,
              "MORE THAN ONE block" in err)

        # ---- WHICH CONTENT ----------------------------------------------
        # Stage the broken file, then clean the working tree. A plain commit
        # records the INDEX; a pathspec commit records the WORKING FILE.
        subprocess.run(["git", "add", lanes_rel], capture_output=True, cwd=dupe)
        with open(os.path.join(dupe, ".syndicate", "lanes.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(CLEAN_LANES)

        code, err = _ask(f"{GC} -m x", dupe, clean)
        check("plain commit reads the STAGED blob -> block", code, 2,
              "MORE THAN ONE block" in err)

        code, err = _ask(f"{GC} -m x -- {lanes_rel}", dupe, clean)
        check("same index, pathspec commit reads the WORKING file -> allow",
              code, 0)

        # ---- WHICH ENV ---------------------------------------------------
        dupe2 = _mkrepo(base, "dupe_tree2", DUPE_LANES)
        code, _ = _ask(f"SYNDICATE_ALLOW_LEDGER_COMMIT=1 {GC} -m x -- {lanes_rel}",
                       dupe2, dupe2)
        check("INLINE `VAR=1` prefix override is honoured", code, 0)

        code, _ = _ask(f"export SYNDICATE_ALLOW_LEDGER_COMMIT=1; {GC} -m x -- {lanes_rel}",
                       dupe2, dupe2)
        check("`export VAR=1;` before the commit is honoured", code, 0)

        code, _ = _ask("export SYNDICATE_ALLOW_LEDGER_COMMIT=1; "
                       f"unset SYNDICATE_ALLOW_LEDGER_COMMIT; {GC} -m x -- {lanes_rel}",
                       dupe2, dupe2)
        check("an intervening `unset` wins -> still blocks", code, 2)

        code, _ = _ask(f"SYNDICATE_ALLOW_LEDGER_COMMIT= {GC} -m x -- {lanes_rel}",
                       dupe2, dupe2)
        check("an EMPTY value is not set -> still blocks", code, 2)

        code, _ = _ask(f"{GC} -m x -- {lanes_rel}", dupe2, dupe2,
                       {"SYNDICATE_ALLOW_LEDGER_COMMIT": "1"})
        check("a real environment variable still overrides", code, 0)

        # ---- FAIL OPEN ---------------------------------------------------
        code, _ = _ask("git status", dupe2, dupe2)
        check("a non-commit git command is ignored", code, 0)
        code, _ = _ask("echo hello", dupe2, dupe2)
        check("a non-git command is ignored", code, 0)
        code, _ = _ask(f"{GC} -m x -- {lanes_rel}", base, base)
        check("outside any repo -> fails open", code, 0)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    failed = 0
    for label, got, want, extra_ok in results:
        ok = got == want and extra_ok
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  exit={got} want={want}  {label}")
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

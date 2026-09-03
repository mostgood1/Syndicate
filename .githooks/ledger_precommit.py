#!/usr/bin/env python3
"""Ledger invariants at `git commit` time, for commits of any origin.

Reads the content the commit would RECORD -- `git show :<path>`, which resolves
against `GIT_INDEX_FILE`. That matters: `git commit -- <pathspec>` builds a
TEMPORARY index and points `GIT_INDEX_FILE` at it, so reading the working file
or the main index would both be wrong for exactly the commit shape that caused
the 2026-09-02 clobber.

Exit codes are a contract with `pre-commit`: 1 means a real violation and blocks,
EVERYTHING ELSE means this checker could not form an opinion and the commit
proceeds. Never raise past main().
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys


def _git(root, *args):
    try:
        r = subprocess.run(["git", "-C", root, *args],
                           capture_output=True, timeout=20)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
    except Exception:
        return None


def main():
    if os.environ.get("SYNDICATE_ALLOW_LEDGER_COMMIT") == "1":
        return 0
    root = _git(".", "rev-parse", "--show-toplevel")
    if not root:
        return 0
    root = root.strip()
    sys.path.insert(0, str(pathlib.Path(root) / ".claude" / "hooks"))
    try:
        from ledger_invariants import TRACKED, violations
    except Exception:
        return 0

    report = []
    for rel in TRACKED:
        text = _git(root, "show", ":" + rel)
        if not text:
            continue
        try:
            bad = violations(rel, text, root)
        except TypeError:
            # AN OLDER `ledger_invariants.py` TAKES ONLY (rel, text). Worktrees in
            # this repo sit at many different commits, so the hook WILL meet the
            # 2-arg version -- and letting the TypeError fall into the blanket
            # `except` below turned the whole check into a silent no-op. Measured
            # 2026-09-02: freshly installed in the primary tree, the hook ran,
            # raised, failed open, and reported nothing. DEGRADE to the predicates
            # that version does have rather than going quiet.
            try:
                bad = violations(rel, text)
            except Exception:
                continue
        except Exception:
            continue
        if bad:
            report.append((rel, bad))
    if not report:
        return 0

    w = sys.stderr.write
    w("\nBLOCKED by pre-commit: this commit would record a ledger file that "
      "fails its invariants.\n\n")
    for rel, bad in report:
        w(rel + "\n")
        for what, how in bad:
            w("  * " + what + "\n" + how + "\n")
        w("\n")
    w("Checked the STAGED content (what the commit would record), in " + root + "\n")
    w("Same predicates as .claude/hooks/ledger-commit-guard.py -- one source,\n"
      "  .claude/hooks/ledger_invariants.py\n\n")
    w("Override (say why in the ledger):\n")
    w("  SYNDICATE_ALLOW_LEDGER_COMMIT=1 git commit ...\n")
    w("  git commit --no-verify ...\n")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # fail open, always

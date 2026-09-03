#!/usr/bin/env python3
"""WHICH TREES DID THIS SESSION JUST WRITE? Shared by the PostToolUse hooks.

Extracted from `ledger-postwrite-check.py` 2026-09-03, verbatim, when
`lane-postwrite-check.py` needed the identical answer. `learnings.md`
2026-08-20 is explicit about why this cannot be copied: when a guard defect is
about the ENVIRONMENT all guards share -- which repo, which index, which env,
WHICH TREE -- fix it in a shared module and migrate the others, or the next
guard written will re-make it.

That is not hypothetical for this particular function. Every hook in this
directory has had the same bug at least once: resolving `CLAUDE_PROJECT_DIR`
(the PRIMARY checkout) while the command it is reacting to ran in the session's
own linked worktree. `ledger-append-guard` was SILENTLY INERT that way for its
whole existence; `ledger-postwrite-check` was blind in exactly the place it was
most needed, and blamed the wrong session when it did speak; `commit-guard`
produced three false positives in one session from it. The answer below is the
one that survived all three.

Two measurements are baked in and should not be undone casually:

  A FILESYSTEM WALK, NOT `git rev-parse --show-toplevel`. Measured on Windows:
  41 ms per call for the git subprocess against 0.0 ms for the walk, for the
  identical answer. These hooks run after EVERY Bash command, and a slow guard
  gets switched off -- which `learnings.md` calls a quieter way of crying wolf.

  `realpath`, NOT `abspath`, for dedupe. `CLAUDE_PROJECT_DIR` can carry an 8.3
  short component (the TEMPAD~1 spelling of the user directory) while git
  reports the long path; `abspath` normalises separators but does not expand
  short names, so one directory compared unequal and got scanned -- and
  reported -- twice.

The worktree comes FIRST in `roots()`: it is the tree this session actually
writes. The primary checkout is second because it is the shared copy every
other session reads at start.
"""
import os

def ledger_root(start):
    """Nearest ancestor of `start` that HOLDS a ledger, or None.

    Deliberately a filesystem walk and NOT `git rev-parse --show-toplevel`,
    which is what the sibling guards use. This hook runs after EVERY Bash
    command, and its docstring promises to be ~free; measured on Windows, the
    git subprocess costs 41ms per call against 0.0ms for the walk, for the
    identical answer. It also asks the question this hook actually has -- "which
    tree holds the files I am about to stat" -- rather than a git question it
    does not care about, so it still works in a tree that is not a repo.
    """
    try:
        d = os.path.abspath(start)
    except Exception:
        return None
    marker = os.path.join(".syndicate", "lanes.md")
    while True:
        if os.path.exists(os.path.join(d, marker)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def roots(payload):
    """Every tree this session could plausibly have just written, deduped.

    The worktree the command ran in comes FIRST -- it is the one this session
    actually writes -- with the primary checkout second because it is the shared
    copy every other session reads at start. Order matters only for reporting.
    """
    cwd = ((payload.get("cwd") or "").strip()
           or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    out, seen = [], set()
    for cand in (ledger_root(cwd) if os.path.isdir(cwd) else None,
                 os.environ.get("CLAUDE_PROJECT_DIR"),
                 cwd):
        if not cand or not os.path.isdir(cand):
            continue
        # `realpath`, not `abspath`: `git rev-parse --show-toplevel` returns the
        # LONG Windows path with forward slashes, while `CLAUDE_PROJECT_DIR` may
        # carry an 8.3 short component (`C:\Users\TEMPAD~1\...`). `abspath`
        # normalises separators but does NOT expand short names, so the same
        # directory compared unequal and the tree was scanned -- and reported --
        # twice. `realpath` resolves both to one spelling.
        try:
            key = os.path.normcase(os.path.realpath(cand))
        except Exception:
            key = os.path.normcase(os.path.abspath(cand))
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out

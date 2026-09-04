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


def _git_dir(root):
    """The gitdir for `root`, following the `.git` FILE a linked worktree uses."""
    g = os.path.join(root, ".git")
    if os.path.isdir(g):
        return g
    try:
        with open(g, encoding="utf-8") as fh:
            line = fh.read().strip()
        if line.startswith("gitdir:"):
            p = line.split(":", 1)[1].strip()
            return p if os.path.isabs(p) else os.path.normpath(os.path.join(root, p))
    except Exception:
        pass
    return None


def head_sig(root):
    """A cheap string that CHANGES WHEN HEAD MOVES, or "" if it cannot be read.

    Exists so a postwrite hook can tell "the user wrote this file" from "a
    `git rebase`/`checkout`/`pull` rewrote it". Without that distinction a
    watcher on a shared tree fires constantly: measured 2026-09-03 by session
    c38d3e5c, `lane-postwrite-check` warned on two claimed files after a
    `git rebase origin/main` that the reporting session had not edited at all.
    In this tree rebases are routine, so that is the cry-wolf failure every
    guard here is written to avoid.

    FILE READS ONLY -- no `git` subprocess. Same budget rule as `roots()`: this
    runs after every Bash command, and 41 ms of subprocess is what that
    docstring already rejected. Two small reads: `HEAD`, plus the ref it names.

    Refs are looked for in the gitdir AND in `commondir`, because a linked
    worktree keeps its own `HEAD` but shares `refs/`. A packed ref resolves to
    no file at all; that is why the ref's (mtime, size) is a fallback and why
    the whole thing degrades to "" rather than raising. "" means UNKNOWN, and
    the caller must decide what to do with that -- it must not be confused with
    "HEAD did not move".
    """
    gd = _git_dir(root)
    if not gd:
        return ""
    try:
        with open(os.path.join(gd, "HEAD"), encoding="utf-8") as fh:
            head = fh.read().strip()
    except Exception:
        return ""
    if not head.startswith("ref:"):
        return head                      # detached: HEAD holds the sha itself

    ref = head.split(":", 1)[1].strip()
    common = gd
    try:
        with open(os.path.join(gd, "commondir"), encoding="utf-8") as fh:
            c = fh.read().strip()
        common = c if os.path.isabs(c) else os.path.normpath(os.path.join(gd, c))
    except Exception:
        pass
    for base in (gd, common):
        p = os.path.join(base, *ref.split("/"))
        try:
            with open(p, encoding="utf-8") as fh:
                return head + "|" + fh.read().strip()
        except Exception:
            continue
    # Packed ref, or unreadable: fall back to whatever moves when it moves.
    for base in (gd, common):
        try:
            st = os.stat(os.path.join(base, "packed-refs"))
            return head + "|packed:%d:%d" % (int(st.st_mtime_ns), st.st_size)
        except OSError:
            continue
    return ""

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

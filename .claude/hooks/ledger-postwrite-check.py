#!/usr/bin/env python3
"""PostToolUse hook - surfaces a broken LEDGER FILE at WRITE time.

Generalises `lanes-postwrite-check.py`, which this replaces, from `lanes.md` to
all three files the ledger's invariants are defined over: `lanes.md`, `state.md`
and `learnings.md`. The predicates live in `ledger_invariants.py` so the
commit-boundary guard enforces exactly the same set.

THE GAP IT FILLS. `ledger-append-guard.py` (PreToolUse) sees only
`Edit|Write|MultiEdit`, so a Bash write is invisible to it. `ledger-commit-guard.py`
catches the same damage but only when someone COMMITS, which can be an hour
later. `check_lane_invariants.py` / `state_key_check.py` run at session start,
far too late. In between, a broken file sits in the SHARED tree being read by
every other session.

IT WARNS, IT CANNOT BLOCK -- PostToolUse runs after the write. The damage exists
either way; the point is that nobody builds on top of it for an hour.

~FREE ON EVERY CALL, because it runs after EVERY Bash command: it stats the
tracked files first and parses NOTHING unless a (mtime, size) changed. State
lives in the OS temp dir keyed by repo path, never in the repo -- a hook that
littered the tree it guards would be caught by its own siblings.

That budget is why the tree is found by a FILESYSTEM WALK and not by
`git rev-parse --show-toplevel`, which is what the sibling guards use: measured
on Windows, the git subprocess is 41ms per Bash call against 0.0ms for the walk,
for the identical answer. Watching two trees instead of one costs ~6ms total on
top of interpreter startup (106ms measured end-to-end, ~100ms of it Python
booting). `commit-guard.py` records the same lesson from the other direction --
5.3s of per-path subprocesses, batched down to 3 spawns -- because a slow guard
gets switched off, which `learnings.md` calls a quieter way of crying wolf.

REPORTS ON TRANSITION, NOT ON STATE. Firing on every call while a file is broken
is the "a warning that always fires is ignored" failure `session-start.sh`
already documents. It speaks when a file BECOMES broken, or breaks again after
changing, and is silent otherwise -- including when the breakage is another
session's and has already been reported once.

IT CHECKS EVERY TREE THIS SESSION COULD HAVE WRITTEN -- the worktree the command
ran in AND the primary checkout -- fixed 2026-08-20. It previously resolved only
`CLAUDE_PROJECT_DIR`, which is the PRIMARY tree, while the Bash command it is
reacting to runs in the session's own linked worktree
(`scripts/session_worktree.py`). Both halves of that were wrong:

  IT WAS BLIND WHERE IT WAS MOST NEEDED. A Bash write is the ONLY thing this
  hook exists to catch, and a worktree session's Bash writes land in the
  worktree's `.syndicate/`. Those files were never stat'ed, so a session could
  break its own `lanes.md` from Bash and hear nothing from any of the three
  guards -- `ledger-append-guard` does not see Bash, this did not see the
  worktree, and `ledger-commit-guard` only speaks at commit time.

  IT BLAMED THE WRONG SESSION. Watching only the shared primary tree means the
  file changes under sessions that did not touch it, and every one of them
  reported "BROKEN by a write just now". Observed 2026-08-20: this fired at a
  session whose command was a `grep`, about duplicate lane blocks another
  session had written earlier. The wording asserted a causal link the hook
  cannot establish -- it sees a (mtime, size) change, never an author -- so it
  now says a file CHANGED AND IS BROKEN, and names the tree.

State is per-tree (`_state_path` keys on the absolute root), so the worktree and
the primary tree dedupe independently and one cannot silence the other.

FAILS OPEN on anything unexpected. Override: `SYNDICATE_LEDGER_POSTCHECK=off`.
"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ledger_invariants import TRACKED, violations
except Exception:
    sys.exit(0)

OFF_ENV = "SYNDICATE_LEDGER_POSTCHECK"


def _state_path(root):
    key = hashlib.sha1(os.path.abspath(root).encode("utf-8")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"syndicate-ledger-check-{key}.json")


def _ledger_root(start):
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


def _roots(payload):
    """Every tree this session could plausibly have just written, deduped.

    The worktree the command ran in comes FIRST -- it is the one this session
    actually writes -- with the primary checkout second because it is the shared
    copy every other session reads at start. Order matters only for reporting.
    """
    cwd = ((payload.get("cwd") or "").strip()
           or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    out, seen = [], set()
    for cand in (_ledger_root(cwd) if os.path.isdir(cwd) else None,
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


def _scan(root):
    """(violations, state_written) for one tree. Never raises."""
    spath = _state_path(root)
    try:
        with open(spath, encoding="utf-8") as fh:
            prev = json.load(fh)
    except Exception:
        prev = {}
    if not isinstance(prev, dict):
        prev = {}

    report, new_state = [], dict(prev)
    for rel in TRACKED:
        path = os.path.join(root, *rel.split("/"))
        try:
            st = os.stat(path)
            sig = [int(st.st_mtime_ns), st.st_size]
        except OSError:
            continue
        # THE CHEAP EXIT: this file did not change, so do not read it.
        if prev.get(rel, {}).get("sig") == sig:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                bad = violations(rel, fh.read())
        except Exception:
            continue
        new_state[rel] = {"sig": sig, "ok": not bad}
        if bad:
            report.append((rel, bad))

    try:
        with open(spath, "w", encoding="utf-8") as fh:
            json.dump(new_state, fh)
    except Exception:
        pass
    return report


def main():
    if os.environ.get(OFF_ENV, "").lower() == "off":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in ("Bash", "PowerShell"):
        return 0

    findings = []
    for root in _roots(payload):
        try:
            for rel, bad in _scan(root):
                findings.append((root, rel, bad))
        except Exception:
            continue

    if not findings:
        return 0

    # NOT "a write just now": this hook sees a (mtime, size) change, never an
    # author. On the shared primary tree the writer is very often another
    # session, and claiming otherwise sent people looking through their own
    # command for a write that was not there.
    sys.stderr.write("LEDGER INVARIANTS BROKEN -- a tracked file CHANGED and now "
                     "fails its invariants.\nThe write already happened; this is a "
                     "warning, not a block. It may have\nbeen another session: the "
                     "check sees the change, not who made it.\n\n")
    for root, rel, bad in findings:
        sys.stderr.write(f"{rel}   (in {root})\n")
        for what, how in bad:
            sys.stderr.write(f"  * {what}\n{how}\n")
        sys.stderr.write("\n")
    sys.stderr.write(
        "These files are read by every other session and the lane system's\n"
        "exclusivity rests on lanes.md, so this is worth fixing before anything else.\n"
        "Fix it in the tree named above -- running a cleanup in the WRONG tree\n"
        "rewrites another session's ledger.\n"
        "A commit touching the affected file will be refused until it is clean.\n"
        f"Silence: {OFF_ENV}=off\n")
    return 2


sys.exit(main())

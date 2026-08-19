#!/usr/bin/env python3
"""PostToolUse hook - surfaces a broken LEDGER FILE at WRITE time.

Generalises `lanes-postwrite-check.py`, which this replaces, from `lanes.md` to
all three files the ledger's invariants are defined over: `lanes.md`, `state.md`
and `learnings.md`. The predicates live in `ledger_invariants.py` so the
commit-boundary guard enforces exactly the same set.

THE GAP IT FILLS. `lanes-append-guard.py` (PreToolUse) sees only
`Edit|Write|MultiEdit`, so a Bash write is invisible to it. `ledger-commit-guard.py`
catches the same damage but only when someone COMMITS, which can be an hour
later. `check_lane_invariants.py` / `state_key_check.py` run at session start,
far too late. In between, a broken file sits in the SHARED tree being read by
every other session.

IT WARNS, IT CANNOT BLOCK -- PostToolUse runs after the write. The damage exists
either way; the point is that nobody builds on top of it for an hour.

~FREE ON EVERY CALL, because it runs after EVERY Bash command: it stats the
three files first and parses NOTHING unless a (mtime, size) changed. State lives
in the OS temp dir keyed by repo path, never in the repo -- a hook that littered
the tree it guards would be caught by its own siblings.

REPORTS ON TRANSITION, NOT ON STATE. Firing on every call while a file is broken
is the "a warning that always fires is ignored" failure `session-start.sh`
already documents. It speaks when a file BECOMES broken, or breaks again after
changing, and is silent otherwise -- including when the breakage is another
session's and has already been reported once.

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


def main():
    if os.environ.get(OFF_ENV, "").lower() == "off":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in ("Bash", "PowerShell"):
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
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
        path = os.path.join(root, rel)
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

    if not report:
        return 0

    sys.stderr.write("LEDGER INVARIANTS BROKEN by a write just now "
                     "(warning -- the write already happened):\n\n")
    for rel, bad in report:
        sys.stderr.write(f"{rel}\n")
        for what, how in bad:
            sys.stderr.write(f"  * {what}\n{how}\n")
        sys.stderr.write("\n")
    sys.stderr.write(
        "These files are read by every other session and the lane system's\n"
        "exclusivity rests on lanes.md, so this is worth fixing before anything else.\n"
        f"A commit touching the affected file will be refused until it is clean.\n"
        f"Silence: {OFF_ENV}=off\n")
    return 2


sys.exit(main())

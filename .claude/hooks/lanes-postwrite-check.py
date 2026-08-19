#!/usr/bin/env python3
"""PostToolUse hook - surfaces a broken `lanes.md` at WRITE time, not commit time.

THE GAP THIS FILLS. Three guards already exist and each misses this window:
`lanes-append-guard.py` (PreToolUse) sees only `Edit|Write|MultiEdit`, so a Bash
write is invisible to it; `ledger-commit-guard.py` (PreToolUse on Bash) catches
the same damage but only when someone COMMITS, which can be an hour later; and
`check_lane_invariants.py` runs at session start, which is far too late. In
between, a broken `lanes.md` sits in the shared tree being READ by every other
session -- and `lanes.md` is the file the lane system's exclusivity rests on.

IT WARNS, IT CANNOT BLOCK. PostToolUse runs after the command has already
written. That is the honest limit of catching this here: the damage exists, the
point is that nobody works on top of it for an hour. `ledger-commit-guard.py`
remains the thing that stops it becoming durable.

IT MUST BE ~FREE, because it runs after EVERY Bash call. A stat is taken first
and the file is not parsed at all unless (mtime, size) changed since the last
run. State lives in the OS temp dir keyed by repo path, never in the repo -- a
hook that litters the tree it guards would be caught by its own siblings.

IT REPORTS ON TRANSITION, NOT ON STATE. Firing on every call while the file is
broken would train people to ignore it, which is how the "warning that always
fires" failure documented in `session-start.sh` starts. It speaks when the file
BECOMES broken, or breaks again after changing, and stays quiet otherwise --
including when the breakage is another session's and already reported.

FAILS OPEN on anything unexpected. Override: `SYNDICATE_LANES_POSTCHECK=off`.
"""
import hashlib
import json
import os
import re
import sys
import tempfile

LANES = ".syndicate/lanes.md"
OFF_ENV = "SYNDICATE_LANES_POSTCHECK"
HEADER_RE = re.compile(r"(?m)^###\s+(\S+)\s")
ARCHIVE_RE = re.compile(r"(?m)^## Archived lanes")


def _state_path(root):
    key = hashlib.sha1(os.path.abspath(root).encode("utf-8")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"syndicate-lanes-check-{key}.json")


def _violations(text):
    out = []
    counts = {}
    for m in HEADER_RE.finditer(text):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    dupes = sorted(s for s, n in counts.items() if n > 1)
    if dupes:
        out.append("more than one block for: " + ", ".join(dupes[:5]))
    arch = ARCHIVE_RE.search(text)
    if arch:
        below = sorted(set(HEADER_RE.findall(text[arch.start():])))
        if below:
            out.append("block(s) below `## Archived lanes`: " + ", ".join(below[:5]))
    return out


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
    path = os.path.join(root, LANES)
    try:
        st = os.stat(path)
        sig = [int(st.st_mtime_ns), st.st_size]
    except OSError:
        return 0

    spath = _state_path(root)
    prev = {}
    try:
        with open(spath, encoding="utf-8") as fh:
            prev = json.load(fh)
    except Exception:
        prev = {}

    # THE CHEAP EXIT: nothing wrote to lanes.md, so do not read it.
    if prev.get("sig") == sig:
        return 0

    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        bad = _violations(text)
    except Exception:
        return 0

    try:
        with open(spath, "w", encoding="utf-8") as fh:
            json.dump({"sig": sig, "ok": not bad}, fh)
    except Exception:
        pass

    if not bad:
        return 0

    sys.stderr.write(
        "lanes.md INVARIANTS BROKEN by a write just now (warning -- the write already happened):\n"
        + "".join(f"  * {b}\n" for b in bad)
        + "This file is read by every other session and the lane system's exclusivity\n"
        "rests on it, so it is worth fixing before doing anything else:\n"
        "  py -3 scripts/hoist_open_lanes.py --apply     # blocks below the marker\n"
        "  py -3 scripts/trim_lane_blocks.py --apply     # duplicate/superseded blocks\n"
        "  py -3 scripts/check_lane_invariants.py        # confirm\n"
        f"A commit will be refused until this is clean. Silence it: {OFF_ENV}=off\n")
    return 2


sys.exit(main())

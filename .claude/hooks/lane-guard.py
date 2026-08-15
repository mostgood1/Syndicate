#!/usr/bin/env python3
"""PreToolUse hook - blocks edits to files claimed by another OPEN lane.

Lower value while running a single session; keep it wired for when a second
session comes back. Fails open on any parse error: a broken guard that blocks
all edits is worse than no guard.

Parsing notes (measured against the real .syndicate/lanes.md, 2026-08-13):
the claim block is NOT a single "- Files: a, b, c" line. 7 of 8 lanes write
"- Files (exclusive to this lane):" and then one nested bullet per path, with
the path in backticks. Deeper bullets under those hold symbol names and line
numbers, not paths, so a token only counts as a claim if it looks like a path
(has a separator, or a short file extension). Paths are normalised to forward
slashes because os.path.relpath returns backslashes on Windows and the ledger
is written with forward slashes.
"""
import json, os, re, sys

TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
HEADER_RE = re.compile(r"^###\s")
# Status is the field between the 1st and 2nd em-dash, and it is FREE TEXT.
# Reading it as one word (the old `(\w+)`) silently unprotected a live lane:
# `memory-guard-reclaimable` was relabelled "— DEPLOYED, MEASUREMENT OPEN —",
# whose first word is DEPLOYED, so its four claimed files stopped being
# guarded with nothing reporting it. Match the WORD anywhere in the field:
# accepts "DEPLOYED, MEASUREMENT OPEN", rejects "OPENED"/"REOPENED"/"CLOSED".
LANE_RE = re.compile(r"^###\s+(\S+)\s+—\s*([^—]*)")
OPEN_RE = re.compile(r"\bOPEN\b")
FILES_RE = re.compile(r"^\s*-\s*Files\b[^:]*:(.*)$")
FIELD_RE = re.compile(r"^-\s*\w")
PATHISH_RE = re.compile(r"^[\w.\-]+\.\w{1,5}$")


# A bullet inside a `- Files:` block that DISCLAIMS a path rather than claiming
# it. Measured 2026-08-15: `ask-sport-coverage` wrote
# "**NOT claimed, deliberately:** `ask_the_syndicate_adapter.py` -- held by OPEN
# lane `ask-headline-from-board`" and this parser turned that sentence into a
# CLAIM of that file, blocking the lane that actually owned it from editing it.
# The reverse fired at the same time between the same two lanes. `state.md`
# already recorded the defect ("a regex over a hand-written ledger read 'NOT
# claimed, deliberately' as a claim. Read the block, not a pattern match over
# it.") -- this is that fix.
#
# Deliberately matched on INTENT WORDS rather than on formatting: the ledger is
# hand-written and the same disclaimer appears as `**NOT claimed:**`,
# `NOT claimed, deliberately:`, `Collision check: CLEAR`, and
# `Read-only dependency:`. Erring toward skipping is the safe direction here --
# a missed claim leaves an edit unguarded, while a phantom claim blocks the
# lane's own owner and has no override short of editing someone else's ledger.
_DISCLAIMER_MARKERS = (
    "not claimed",
    "collision check",
    "read-only dependency",
    "not touched",
    "held by",
    "claimed by",
    "ownership checked",
    "zero mentions",
    "no lane",
)


def _is_disclaimer(line):
    """True when this Files-block bullet talks ABOUT a path instead of claiming it."""
    text = line.lstrip("- ").strip().strip("*_").lower()
    return any(marker in text for marker in _DISCLAIMER_MARKERS)


def _norm(p):
    return p.replace("\\", "/").strip("/")


def _paths_in(text):
    """Pull path-looking tokens out of a claim line."""
    out = []
    for tok in re.split(r"[,\s]+", text or ""):
        tok = tok.strip().strip("`<>*_()[].,;")
        if not tok or tok.lower() in ("n/a", "none", "fill", "in", "tbd"):
            continue
        if "/" in tok or "\\" in tok or PATHISH_RE.match(tok):
            norm = _norm(tok)
            if norm:
                out.append(norm)
    return out


def _claims(text):
    """Yield (slug, claimed_path) for every OPEN lane."""
    slug = None
    open_lane = False
    in_files = False
    for line in text.splitlines():
        # Every "### " line ends the previous lane, parseable or not. Without
        # this branch a header that fails LANE_RE (e.g. "### (superseded lane
        # detail...)") fell through and INHERITED the previous lane's open
        # state, attributing its Files block to the wrong slug.
        if HEADER_RE.match(line):
            m = LANE_RE.match(line)
            if m:
                slug = m.group(1)
                open_lane = bool(OPEN_RE.search(m.group(2)))
            else:
                slug, open_lane = None, False
            in_files = False
            continue

        m = FILES_RE.match(line)
        if m:
            in_files = True
            if open_lane:
                for f in _paths_in(m.group(1)):
                    yield slug, f
            continue

        if in_files:
            stripped = line.strip()
            # A new top-level field ("- Goal:", "- Hypothesis:") or a blank
            # run ends the claim block; nested bullets continue it.
            if not stripped or (FIELD_RE.match(line) and not line[:1].isspace()):
                in_files = False
                continue
            if open_lane and stripped.startswith("-") and not _is_disclaimer(stripped):
                for f in _paths_in(stripped.lstrip("- ")):
                    yield slug, f


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name", "") not in TOOLS:
        return 0

    path = (payload.get("tool_input") or {}).get("file_path")
    if not path:
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    lanes_file = os.path.join(root, ".syndicate", "lanes.md")
    if not os.path.exists(lanes_file):
        return 0

    try:
        rel = _norm(os.path.relpath(path, root))
    except Exception:
        return 0

    # Never guard the ledger or the harness config itself.
    if rel.startswith(".syndicate") or rel.startswith(".claude"):
        return 0

    # PER-SESSION MARKER, falling back to the global one.
    #
    # This file's own docstring said "lower value while running a single
    # session". Measured 2026-08-15 with FIVE live sessions in this worktree:
    # `.syndicate/.current-lane` is a single slot every session writes, so it
    # names whoever wrote last, and the guard then blocks a session from
    # editing files ITS OWN OPEN LANE claims. Three consecutive edits were
    # blocked that way in one session while no real cross-lane conflict
    # existed -- the guard was firing on marker contention, not on the thing
    # it exists to catch. A guard that blocks correct work is one people
    # route around, which costs more than the guard was ever worth.
    #
    # `.current-lane.<session_id>` gives each session its own slot, so the
    # marker stops being a contended lock. The global file is still read when
    # no per-session file exists, so a session that never writes one behaves
    # EXACTLY as before -- this cannot break a session that has not opted in.
    current = ""
    session_marker_used = False
    session_id = str(payload.get("session_id") or "").strip()
    # Defensive: the id goes into a filename, and it arrives from outside.
    safe_session_id = re.sub(r"[^A-Za-z0-9._-]", "", session_id)[:128]
    if safe_session_id:
        session_marker = os.path.join(root, ".syndicate", f".current-lane.{safe_session_id}")
        if os.path.exists(session_marker):
            try:
                with open(session_marker, encoding="utf-8") as fh:
                    current = fh.read().strip()
                session_marker_used = bool(current)
            except Exception:
                current = ""

    marker = os.path.join(root, ".syndicate", ".current-lane")
    if not current and os.path.exists(marker):
        try:
            with open(marker, encoding="utf-8") as fh:
                current = fh.read().strip()
        except Exception:
            current = ""

    try:
        with open(lanes_file, encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return 0

    conflict = None
    try:
        for slug, f in _claims(text):
            if slug == current:
                continue
            if rel == f or rel.endswith("/" + f) or f.endswith("/" + rel):
                conflict = slug
    except Exception:
        return 0

    if conflict:
        sys.stderr.write(
            f"BLOCKED: {rel} is claimed by OPEN lane '{conflict}'.\n"
            f"Current lane: '{current or 'none'}'"
            f"{' (per-session marker)' if session_marker_used else ' (global marker)'}.\n"
            "Close or reassign that lane, or work a different file. "
            "Do not edit across lanes.\n"
            "If this IS your lane, you are on the shared global marker while "
            "another session holds it. Write your slug to "
            f".syndicate/.current-lane.{safe_session_id or '<session_id>'} "
            "instead -- that slot is yours alone and nothing else rewrites it.\n"
        )
        return 2
    return 0


sys.exit(main())

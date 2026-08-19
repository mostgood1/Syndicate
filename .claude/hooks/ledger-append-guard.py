#!/usr/bin/env python3
"""PreToolUse hook - stops the ledger growing the ways it actually grows.

Covers `lanes.md` (two predicates) and `state.md` (one). All three are DELTA
predicates: they compare the file BEFORE and AFTER the edit. That is what lets
them forbid a pattern the file already contains instances of, without blocking
the status quo -- `state.md` holds 2 dated sub-headings today and this guard
forbids ADDING a third, saying nothing about those two.

WHY A DELTA AND NOT A STATE CHECK. `ledger_invariants.py` holds the state
predicates, enforced at write time and at commit time. "Appending instead of
editing" is not a property of a file, it is a property of a CHANGE, so it cannot
live there and must be caught at the tool call.

  lanes.md   a SECOND block for a lane that already has one -- the
             append-instead-of-edit failure that took the file to 2.12x its cap
             with one lane holding 16 blocks / 44,905 B.
             a block BELOW `## Archived lanes` -- `lane-guard` reads lanes.md and
             nothing else, so the next archive pass drops those claims SILENTLY.
  state.md   a NEW DATED `### ` sub-heading -- the observable form of the
             "EDIT THE LINE" failure. The file was collapsed THREE TIMES for
             "dated snapshots of a story whose ending was elsewhere in the same
             file", and that chronology gets built one append at a time.

IT SIMULATES THE EDIT rather than pattern-matching the new string, because a
guard that inspects `new_string` alone cannot tell "added a second block" from
"rewrote the one that was there" and would block the behaviour it exists to
encourage.

THE state.md PREDICATE ROUTES RATHER THAN JUST REFUSING. A dated record is often
legitimate -- it simply belongs in `deploys.md`, `lanes.md` or `learnings.md`,
which is what the file's own header already says. The message names the right
home instead of leaving the writer stuck.

FAILS OPEN on any parse or read error. Off switch: `SYNDICATE_LEDGER_GUARD=off`.
"""
import json
import os
import re
import sys

TOOLS = ("Edit", "Write", "MultiEdit")
LANES = ".syndicate/lanes.md"
STATE = ".syndicate/state.md"
OFF_ENV = "SYNDICATE_LEDGER_GUARD"

HEADER_RE = re.compile(r"(?m)^###\s+(\S+)\s")
ARCHIVE_RE = re.compile(r"(?m)^## Archived lanes")
STATE_DATED_SUB = re.compile(r"(?m)^###\s+.*?(?:20\d\d-\d\d-\d\d|\d\d:\d\dZ)")


def _counts(text):
    """(per-slug block count, blocks below the archive HEADING) for lanes.md.

    The marker is matched as a HEADING, never a substring: prose that merely
    mentions `## Archived lanes` moved this boundary once already and inflated a
    violation count from 7 to 11.
    """
    per = {}
    for m in HEADER_RE.finditer(text):
        per[m.group(1)] = per.get(m.group(1), 0) + 1
    arch = ARCHIVE_RE.search(text)
    below = len(HEADER_RE.findall(text[arch.start():])) if arch else 0
    return per, below


def _after(payload, current):
    """The file content this tool call would produce, or None if unknown."""
    name = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    if name == "Write":
        return ti.get("content")
    edits = ti.get("edits") if name == "MultiEdit" else [ti]
    if not isinstance(edits, list):
        return None
    text = current
    for e in edits:
        if not isinstance(e, dict):
            return None
        old, new = e.get("old_string"), e.get("new_string")
        if old is None or new is None or old not in text:
            return None
        text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def main():
    if os.environ.get(OFF_ENV, "").lower() == "off":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in TOOLS:
        return 0

    path = (payload.get("tool_input") or {}).get("file_path") or ""
    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    try:
        rel = os.path.relpath(path, root).replace("\\", "/")
    except Exception:
        return 0
    if rel not in (LANES, STATE):
        return 0

    try:
        with open(os.path.join(root, *rel.split("/")), encoding="utf-8", errors="replace") as fh:
            current = fh.read()
        after = _after(payload, current)
        if after is None:
            return 0
    except Exception:
        return 0

    if rel == STATE:
        try:
            gained = len(STATE_DATED_SUB.findall(after)) - len(STATE_DATED_SUB.findall(current))
        except Exception:
            return 0
        if gained > 0:
            sys.stderr.write(
                "BLOCKED: this edit adds a DATED `### ` sub-heading to state.md.\n\n"
                "state.md's own rule is EDIT THE LINE: when a fact changes, overwrite the\n"
                "line that is now wrong. Appending a dated sub-section builds a CHRONOLOGY,\n"
                "and a reader then has to reconstruct the current truth from it instead of\n"
                "reading it. This file has been collapsed THREE TIMES for exactly that.\n\n"
                "If the record genuinely needs its own dated entry, it has a home:\n"
                "  a MEASUREMENT and its working   -> .syndicate/deploys.md (append-only)\n"
                "  lane state / what a session did -> .syndicate/lanes.md, log/<today>.md\n"
                "  a rule learned the hard way     -> .syndicate/learnings.md\n\n"
                f"Override for this session: {OFF_ENV}=off\n")
            return 2
        return 0

    try:
        before_per, before_below = _counts(current)
        after_per, after_below = _counts(after)
    except Exception:
        return 0

    dupes = sorted(s for s, n in after_per.items()
                   if n > before_per.get(s, 0) and before_per.get(s, 0) >= 1)
    if dupes:
        sys.stderr.write(
            "BLOCKED: this edit adds a SECOND block for a lane that already has one: "
            + ", ".join(dupes) + ".\n"
            "`lanes.md` carries STATUS -- one lane, one block. EDIT the existing block's\n"
            "header in place instead of appending a new one, and put the narrative in\n"
            ".syndicate/log/<today>.md (which /checkpoint step 2 already requires).\n"
            "If the old block is worth keeping, move it VERBATIM to lanes_history.md.\n"
            "Appending is how this file reached 2.12x its cap with one lane holding 16\n"
            f"blocks. Override for this session: {OFF_ENV}=off\n")
        return 2

    if after_below > before_below:
        sys.stderr.write(
            "BLOCKED: this edit puts a `### ` lane block BELOW the `## Archived lanes`\n"
            "heading. Insert it at the END of the `## OPEN` section instead -- find\n"
            "`## OPEN`, scan to the next `## `, and put the block before it.\n"
            "This is not about size. `lane-guard` reads lanes.md and NOTHING else, so\n"
            "the next archive pass moves that block to lanes_closed.md and its file\n"
            "claims stop being enforced SILENTLY -- `#466`, where 7 OPEN lanes were\n"
            f"found in that state. Override: {OFF_ENV}=off\n")
        return 2

    return 0


sys.exit(main())

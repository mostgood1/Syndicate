#!/usr/bin/env python3
"""PreToolUse hook - stops `lanes.md` growing the two ways it actually grows.

WHY A HOOK AND NOT AN INSTRUCTION. Both append sites were fixed in PROSE on
2026-08-18 -- `/lane` step 5 (insert at the end of `## OPEN`, not EOF) and
`/checkpoint` step 4 (edit your block in place, never append a second). Prose is
what failed the first time: `lanes.md` reached 2.12x its 120,000-byte cap with
one lane holding 16 blocks / 44,905 B, and after a trim it was back over cap
within EIGHT HOURS. A rule nothing enforces waits for a reader who is in a hurry.

IT REFUSES EXACTLY TWO THINGS, both measured failures:

  DUPLICATE BLOCK  the edit would leave a `### <slug>` with MORE blocks than it
                   has now. That is the /checkpoint failure -- append a status
                   block instead of editing the existing one.
  BLOCK BELOW THE  the edit would add a `### ` block after the first
  ARCHIVE MARKER   `^## Archived lanes` heading. That is the /lane failure, and
                   it is worse than size: `lane-guard` reads `lanes.md` and
                   NOTHING else, so the next archive pass moves that block to
                   `lanes_closed.md` and its file claims stop being enforced
                   SILENTLY. `#466`.

EVERYTHING ELSE IS ALLOWED, deliberately. Editing a block in place leaves the
per-slug count unchanged. Opening a genuinely new lane under `## OPEN` takes its
slug 0 -> 1 and sits above the marker. REMOVING blocks is always fine -- that is
what `trim_lane_blocks.py` and `archive_released_lanes.py` do, and they write via
Python from Bash anyway, which this hook never sees.

IT SIMULATES THE EDIT RATHER THAN GUESSING. For Write it reads `content`; for
Edit/MultiEdit it applies old->new to the file exactly as the tool would, then
compares before/after. A guard that pattern-matches the NEW STRING alone cannot
tell "added a second block" from "rewrote the one that was there", and would
block the correct behaviour it exists to encourage.

FAILS OPEN on any parse or read error, like every other guard here: a broken
guard that blocks all edits is worse than no guard. Off switch:
`SYNDICATE_LANES_GUARD=off`.
"""
import json
import os
import re
import sys

TOOLS = ("Edit", "Write", "MultiEdit")
HEADER_RE = re.compile(r"(?m)^###\s+(\S+)\s")
ARCHIVE_RE = re.compile(r"(?m)^## Archived lanes")


def _counts(text):
    """(per-slug block count, number of blocks below the archive HEADING).

    The marker is matched as a HEADING, never as a substring: prose that merely
    mentions `## Archived lanes` moved this boundary once already and inflated a
    violation count from 7 to 11 (see check_lane_invariants.py).
    """
    per = {}
    for m in HEADER_RE.finditer(text):
        per[m.group(1)] = per.get(m.group(1), 0) + 1
    arch = ARCHIVE_RE.search(text)
    below = 0
    if arch:
        below = len(HEADER_RE.findall(text[arch.start():]))
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
    if os.environ.get("SYNDICATE_LANES_GUARD", "").lower() == "off":
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
    if rel != ".syndicate/lanes.md":
        return 0

    lanes = os.path.join(root, ".syndicate", "lanes.md")
    try:
        with open(lanes, encoding="utf-8", errors="replace") as fh:
            current = fh.read()
        after = _after(payload, current)
        if after is None:
            return 0
        before_per, before_below = _counts(current)
        after_per, after_below = _counts(after)
    except Exception:
        return 0

    dupes = sorted(s for s, n in after_per.items() if n > before_per.get(s, 0) and before_per.get(s, 0) >= 1)
    if dupes:
        sys.stderr.write(
            "BLOCKED: this edit adds a SECOND block for a lane that already has one: "
            + ", ".join(dupes) + ".\n"
            "`lanes.md` carries STATUS -- one lane, one block. EDIT the existing block's\n"
            "header in place instead of appending a new one, and put the narrative in\n"
            ".syndicate/log/<today>.md (which /checkpoint step 2 already requires).\n"
            "If the old block is worth keeping, move it VERBATIM to lanes_history.md.\n"
            "Appending is how this file reached 2.12x its cap with one lane holding 16\n"
            "blocks. Override for this session: SYNDICATE_LANES_GUARD=off\n")
        return 2

    if after_below > before_below:
        sys.stderr.write(
            "BLOCKED: this edit puts a `### ` lane block BELOW the `## Archived lanes`\n"
            "heading. Insert it at the END of the `## OPEN` section instead -- find\n"
            "`## OPEN`, scan to the next `## `, and put the block before it.\n"
            "This is not about size. `lane-guard` reads lanes.md and NOTHING else, so\n"
            "the next archive pass moves that block to lanes_closed.md and its file\n"
            "claims stop being enforced SILENTLY -- `#466`, where 7 OPEN lanes were\n"
            "found in that state. Override: SYNDICATE_LANES_GUARD=off\n")
        return 2

    return 0


sys.exit(main())

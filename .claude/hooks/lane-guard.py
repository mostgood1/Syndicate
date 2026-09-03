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
# THE PARSER LIVES IN `lane_claims.py` AS OF 2026-09-03, and every incident
# comment moved with it verbatim. It is shared because a SECOND copy of this
# logic is not hypothetical here -- f57a02f2, landed the same day, had to add
# the `never` marker to TWO files by hand and says so in its own message
# ("kept verbatim-identical"). `learnings.md` 2026-08-20 is the standing rule:
# a defect in what all the guards share must be fixed in a shared module, or
# the next guard re-makes it. Two new callers arrived the day this moved.
#
# The extraction was verified to change no decision: the claim set parsed from
# the live `lanes.md` is identical before and after, and
# `test_lane_guard_hyphen.py` is green either side.
#
# IT FAILS OPEN ON AN IMPORT ERROR, BUT NEVER SILENTLY. This file's contract is
# fail-open -- a broken guard that blocks every edit is worse than no guard --
# and that is kept. What is NOT kept is the silence: "an inert guard and a
# satisfied guard are indistinguishable from outside" is this repo's own phrase
# for how `ledger-append-guard` read as passing for its entire existence. A
# missing shared module now says so on stderr every time.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lane_claims import (
        _claims,
        _malformed_headers,
        _norm,
        is_exempt,
        matches,
    )
    from lane_marker import current_lane, safe_session_id as safe_session_id_of
except Exception as exc:  # pragma: no cover - only when the module is missing
    sys.stderr.write((
        "lane-guard: CANNOT IMPORT lane_claims (%s). NO LANE CLAIM IS BEING "
        "ENFORCED on this edit. Restore .claude/hooks/lane_claims.py"
    ) % exc + chr(10))
    sys.exit(0)


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
    #
    # `rel` is root-relative, so this ONLY caught the primary tree. A session
    # editing the SAME logical `.syndicate/lanes.md` from an isolated worktree
    # (`C:/tmp/syndicate-sessions/<lane>/.syndicate/lanes.md`, per
    # `session_worktree.py`) gets a `rel` like
    # `../../../../tmp/syndicate-sessions/<lane>/.syndicate/lanes.md` -- it
    # does not start with ".syndicate", so the exemption silently failed to
    # apply and the file fell through to ordinary claim-checking. Measured
    # 2026-08-18: this is what let a false claim on `lanes.md` (see the
    # `_claimable_prefix` fix above) block a worktree session from closing its
    # own lane, on a file this guard was never supposed to check at all.
    # Check the PATH ITSELF for a `.syndicate`/`.claude` segment, not its
    # position relative to `root` -- true in both the primary tree and any
    # worktree, since both mirror the same internal layout.
    if is_exempt(path):
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
    #
    # THE READ ITSELF MOVED TO `lane_marker.py` 2026-09-03, and it fixed a live
    # defect on the way. There were two copies of this: the one that used to sit
    # here read plain UTF-8 and `.strip()`, while `deploy-guard.py` read
    # `utf-8-sig` and took `splitlines()[0]`. A marker file written with a BOM
    # therefore resolved to the lane slug for DEPLOYS and to the literal string
    # U+FEFF for EDITS -- and U+FEFF matches no lane, so that session was locked
    # out of editing its OWN claimed files, by a guard telling it to write the
    # marker it had already written. One such marker was sitting in
    # `.syndicate/` when this was found (`.current-lane.92987093...`, three
    # bytes: ef bb bf). The tolerant read is now the only read.
    current, session_marker_used = current_lane(root, payload.get("session_id"))
    safe_session_id = safe_session_id_of(payload.get("session_id"))

    # The fallback to the bare `.syndicate/.current-lane` moved into
    # `current_lane()` with the rest of the read -- same order, same precedence.

    try:
        with open(lanes_file, encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return 0

    # MALFORMED HEADERS: report always, block the owner.
    #
    # Reporting alone was the old behaviour by accident -- the session-start
    # digest counted them and nobody acted, so the count grew 1 -> 5 in one day.
    # A count is not a finding until it names something and stops someone.
    try:
        malformed = _malformed_headers(text)
    except Exception:
        malformed = []

    if malformed:
        sys.stderr.write(
            "LANE HEADER(S) USE ASCII HYPHENS. They need the em-dash U+2014 that "
            "lane-guard and the session-start digest both parse on:\n")
        for _slug, _line in malformed:
            sys.stderr.write("    " + _line[:120] + "\n")
        sys.stderr.write(
            "Their claims ARE enforced here, so nothing is unguarded -- but the "
            "digest will not list them as OPEN, so an arriving session sees no "
            "claim on those paths. Fix the separators.\n")

    if current and any(_slug == current for _slug, _ in malformed):
        # Deliberately NOT printing a literal em-dash: this hook's stderr is
        # re-encoded by the console, and an instruction to use U+2014 that
        # arrives as a mangled byte is worse than no instruction at all.
        sys.stderr.write(
            "\nBLOCKED: your own lane header for '" + current + "' uses ASCII "
            "hyphens, so the digest does not list your lane as OPEN and an "
            "arriving session sees no claim on your files.\n"
            "Replace both separators with U+2014 (the em-dash character) so the\n"
            "header reads:   ### " + current + " <U+2014> OPEN <U+2014> <status>\n"
            "Copy the separator from any other OPEN lane header rather than "
            "typing it -- that is the reliable way to get the right codepoint.\n"
            "Then re-run your edit. Verify with:\n"
            "    bash .claude/hooks/session-start.sh | grep -i guarded\n"
            "Blocked rather than warned because the warning was already being "
            "printed and ignored while the count grew to five.\n")
        return 2

    conflict = None
    try:
        for slug, f in _claims(text):
            if slug == current:
                continue
            if matches(rel, f):
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

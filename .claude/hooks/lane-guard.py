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
# THE SAME HEADER WRITTEN WITH ASCII HYPHENS. LANE_RE requires U+2014, so a
# header written `### slug - OPEN - ...` did not parse AT ALL -- and an unparsed
# header is an UNGUARDED lane, silently. Measured 2026-08-17: one live lane sat
# in that state with three claimed files unprotected, one of them contended with
# a lane closed minutes earlier; by day's end the digest reported FIVE of them.
#
# The fix is deliberately two-sided, because rejecting alone leaves the gap open:
# these headers are PARSED, so their claims are enforced like any other lane, AND
# reported loudly, and the owning session is blocked from editing until it fixes
# the separator. Protection first, pressure second.
ASCII_LANE_RE = re.compile(r"^###\s+(\S+)\s+-\s*([^-]*)")
# `- Files:` and `- **Files (...):**` are the same field. Measured 2026-08-18:
# 32 of 37 Files declarations used the bare form and 5 used the bold one, and
# those 5 matched NOTHING -- they declared files that no hook could see, which is
# the worst state available: the ledger says a file is held and the guard lets
# anyone edit it.
#
# THE COLON IS OPTIONAL, because two of the five wrap the header across lines and
# the colon lands on the second ("- **Files (all NEW -- collision-checked ...").
# `[^:]*` cannot span a newline, so requiring it would still miss those two.
# Continuation lines are picked up by the `in_files` loop either way.
FILES_RE = re.compile(r"^\s*-\s*\*{0,2}Files\b[^:]*:?(.*)$")
# FIELD_RE MUST learn the bold form at the same time, and this is the dangerous
# half. It is what ENDS a claim block. Teaching FILES_RE about `- **Files` while
# leaving this bare would start the block and never stop it: the fields in these
# blocks run `- **Goal:**`, `- **Files:**`, `- **DELIBERATELY OUT OF SCOPE**`
# with no blank line between them, so the parser would read every later bullet as
# a claim. Over-claiming blocks sessions from files nobody holds, which is a
# different failure and not a smaller one.
FIELD_RE = re.compile(r"^-\s*\*{0,2}\w")
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
#
# "not touch" (present tense) was MISSING. Measured 2026-08-19:
# basketball-model-owner wrote "Does NOT touch board_enrichment.py,
# run_live_odds_refresh_worker.py, or wnba_fixture_identity.py (held by
# wnba-live-tier / wnba-phase2-migration)." -- the recognized marker "held by"
# sits AFTER the three filenames, so `_claimable_prefix` had nothing earlier to
# cut at and included all three as claims. That blocked `wnba-edge-263` from
# editing `board_enrichment.py`, a file the sentence explicitly disclaims and
# whose named would-be claimants were both already closed. "not touch" is a
# substring of the existing "not touched", so it subsumes that entry (covers
# both tenses) without changing where either function looks for it.
_DISCLAIMER_MARKERS = (
    "not claimed",
    "collision check",
    "read-only dependency",
    "not touched",
    "not touch",
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


def _claimable_prefix(line):
    """The part of a Files line that still claims, i.e. everything BEFORE any
    disclaimer marker.

    A DISCLAIMER GOVERNS WHAT FOLLOWS IT, and treating it as a veto over the
    whole line loses real claims. The ledger writes them in one breath:

        - **Files (exclusive to this lane):** `live_refresh_loop.py`,
          `tests/test_pregame_cadence_fixture_aware.py` (new). Collision check
          RUN 2026-08-15 against all OPEN lanes: both CLEAR.

    "Collision check ... CLEAR" is a marker, so a whole-line veto silently
    dropped the test file sitting in front of it -- a file the lane plainly
    claims. Cutting at the marker keeps that path and still discards everything
    the sentence goes on to mention.

    The 2026-08-15 incident is preserved exactly: "**NOT claimed, deliberately:**
    `ask_the_syndicate_adapter.py`" puts the marker at the front, so the
    claimable prefix is empty and the file stays unclaimed -- which is the whole
    reason this machinery exists.
    """
    low = line.lower()
    positions = [low.find(m) for m in _DISCLAIMER_MARKERS]
    positions = [p for p in positions if p != -1]
    return line[:min(positions)] if positions else line


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
            if not m:
                # Malformed separator: still a lane, still claims its files.
                m = ASCII_LANE_RE.match(line)
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
                # THE SAME DISCLAIMER-STRIPPING CONTINUATION LINES ALREADY GET.
                # Measured 2026-08-18: `basketball-model-owner`'s Files line ran
                # "- Files: <real paths>. ... Collision check: no other OPEN lane
                # claims any `data/wnba_source/**` path (grepped `lanes.md`,
                # clean)." all on ONE physical line (no colon before "Files:",
                # so [^:]* stops at the FIRST colon and (.*) swallows the whole
                # rest of the line, disclaimer included). `lanes.md` -- mentioned
                # only as the file that WAS grepped, not a claim -- got read as
                # this lane's own path and blocked an unrelated worktree session
                # from writing `.syndicate/lanes.md` at all. Continuation lines
                # already run through `_claimable_prefix` for exactly this
                # reason; the initial line never did, which is the gap.
                for f in _paths_in(_claimable_prefix(m.group(1))):
                    yield slug, f
            continue

        if in_files:
            stripped = line.strip()
            # A new top-level field ("- Goal:", "- Hypothesis:") or a blank
            # run ends the claim block; nested bullets continue it.
            if not stripped or (FIELD_RE.match(line) and not line[:1].isspace()):
                in_files = False
                continue
            # WRAPPED CONTINUATION LINES COUNT, not just nested `-` bullets.
            # Requiring a leading "-" missed the commonest shape in this file --
            # a Files declaration wrapped across lines:
            #
            #   - Files (claimed 2026-08-15, collision check CLEAR via ...
            #     own `_claims()`): `syndicate/features/shared/clv_join.py`,
            #     `tests/test_clv_close_timing.py` (new).
            #
            # Both paths live on lines that begin with a word, so both were
            # invisible. `clv_join.py` looked guarded only because the SAME name
            # appears in prose further down under a `-`, which the block used to
            # run into; the real declaration never parsed. An accidental claim
            # from prose is not protection -- it moves the moment the prose does.
            #
            # Safe because the block is bounded: FIELD_RE ends it at the next
            # top-level field, so only the declaration's own lines are read, and
            # `_is_disclaimer` still skips "NOT claimed, deliberately" bullets.
            if open_lane:
                for f in _paths_in(_claimable_prefix(stripped).lstrip("- ")):
                    yield slug, f


def _malformed_headers(text):
    """Lane headers needing U+2014 that were written with ASCII hyphens.

    Returns [(slug, header_line)]. These DO parse for claim purposes (see
    `_claims`) so no lane goes unguarded -- but every other reader keyed on the
    em-dash, including the session-start digest, still disagrees about them.
    """
    out = []
    for line in text.splitlines():
        if not HEADER_RE.match(line):
            continue
        if LANE_RE.match(line):
            continue
        m = ASCII_LANE_RE.match(line)
        if m and OPEN_RE.search(m.group(2)):
            out.append((m.group(1), line.strip()))
    return out


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
    norm_path = _norm(path)
    if any(
        norm_path == marker or norm_path.startswith(marker + "/") or ("/" + marker + "/") in ("/" + norm_path)
        for marker in (".syndicate", ".claude")
    ):
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

#!/usr/bin/env python3
"""The lane-claim parser, shared. Extracted from `lane-guard.py` 2026-09-03.

WHY IT MOVED. `learnings.md` carries a standing rule from 2026-08-20: when a
guard defect is about something all the guards share, fix it in a SHARED module
and migrate the others, or the next guard written will re-make it. This parser
is that thing. Every comment in here is a past incident -- a disclaimer read as
a claim, a bold `- **Files:**` header matching nothing, an ASCII-hyphen header
that parsed as no lane at all, a leading dot stripped so every `.syndicate/`
claim guarded nothing.

THE DUPLICATION WAS ACTIVE, NOT THEORETICAL, and it cost something the same day
this moved. Commit f57a02f2 added the `never` marker because two lanes both
wrote "**never `render.yaml`**" -- a PROHIBITION -- and were reported as
CONTESTING the repo's highest-blast-radius file. Its own message records the
tax: "Added to BOTH the script and .claude/hooks/lane-guard.py, which are kept
verbatim-identical". Two files, hand-synced, on a parser whose every line is a
past incident. `lane-postwrite-check.py` and `scripts/check_lane_claims.py`
were about to make that four. They import this instead.

`scripts/check_lane_invariants.py` HAS BEEN MIGRATED, 2026-09-04. This note used
to say it "still holds its own copy and should be migrated when its OPEN lane
(`ncaaf-live-cadence`) closes -- editing it now would be the cross-lane write
these guards exist to prevent." That blocker was a PHANTOM: `ncaaf-live-cadence`
never claimed the file, it mentioned it in prose inside its `- Files:` block
("caught by `check_lane_invariants.py`"), which the parser below reads as a
claim. So the deferral was real, correctly observed, and rested on nothing.
Cleared by splicing a top-level bullet before that lane's trailing prose; its
four declared paths were untouched and are still guarded.

What the delay cost is worth recording, because it is the argument for this
module: the copy had drifted in four ways by the time it was migrated, and the
test that was supposed to catch drift had ITSELF been broken since this
extraction -- it scraped `lane-guard.py` for definitions that had moved here.
Worst case, a `- Files:` line naming `scripts/archive_released_lanes.py` yielded
the checker ZERO claims, so its two-holder invariant passed vacuously and
printed INVARIANTS HOLD.

THE MOVE WAS VERBATIM. The functions below are byte-for-byte what
`lane-guard.py` held, comments included, so this extraction changes no
enforcement decision. That was checked, not assumed: the claim set parsed from
the live `lanes.md` before and after the move is IDENTICAL, and
`test_lane_guard_hyphen.py` is green either side.

NOTHING IN HERE DOES I/O, reads an env var, or knows what a hook is. Callers
own the tree, the marker and the exit code -- which is the half of `lane-guard`
that has been wrong three separate times (relpath vs. the worktree, the shared
marker slot, the `.syndicate`/`.claude` exemption) and is deliberately NOT
shared, because each caller wants a different answer to it.
"""
import os
import re

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
# The extension must START WITH A LETTER. `\w{1,5}` accepted `15.0`, `1.5` and
# every other version-shaped token as a claimed path -- the phantom class
# `learnings.md` named on 2026-08-31 ("reject tokens that do not look like
# paths: catches `1/p`, `15.0`") and which was written up but never fixed here.
# Real extensions are alphabetic; nothing in the repo has a digit-leading one.
# Tokens containing a separator are unaffected -- `_paths_in` accepts those on
# the "/" arm without consulting this pattern at all.
PATHISH_RE = re.compile(r"^[\w.\-]+\.[A-Za-z]\w{0,4}$")


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
#
# "read-only reference" was ALSO MISSING. Measured 2026-08-19:
# `nfl-player-props-calibration-fix` wrote "Read-only reference:
# `docs/ai_context/todo.md`" -- an explicit disclaimer, phrased differently
# from the already-recognized "Read-only dependency:" -- and neither
# `_is_disclaimer` nor `_claimable_prefix` recognized it, so the path read as
# a genuine claim. That blocked `nhl-model-owner` from editing `todo.md`, a
# file every lane in this repo edits constantly as a shared append-only
# ledger.
#
# "not taken" was ALSO MISSING -- the third instance of the same class in one
# day. Measured 2026-08-19: `wnba-edge-263` wrote "**BLOCKED, not taken:**
# `scripts/refresh_wnba_oddsapi_props.py`. `lane-guard` caught this live --
# `basketball-model-owner`'s Files block ... explicitly holds WRITE on this
# exact file ... **Not editing it.**" -- a disclaimer stating the OPPOSITE of a
# claim, written specifically BECAUSE this hook had just enforced the real
# owner's claim correctly. Neither `_is_disclaimer` nor `_claimable_prefix`
# recognized "not taken", so the path re-read as `wnba-edge-263`'s OWN claim --
# and blocked `basketball-model-owner`, the file's actual, stated, correctly-
# enforced owner, from editing their own file. A correct block followed by a
# stale record of that block turning into a phantom counter-claim is a new
# failure shape, not a repeat of the first two: those were disclaimers about a
# file the writer never touched; this one is a disclaimer ABOUT THIS HOOK'S
# OWN PRIOR ENFORCEMENT, and it still needs the same fix.
#
# "released"/"claim released" was ALSO MISSING -- the fourth instance,
# measured 2026-08-19 while FIXING the third. `soccer-odds-capture-cadence-
# gap` released `basketball-model-owner`'s completed-but-unclosed claim on
# `artifact_publisher.py` (their own header already said "no further action
# identified as ready") and wrote "**`syndicate/features/shared/
# artifact_publisher.py` claim RELEASED 2026-08-19 by `soccer-odds-capture-
# cadence-gap`**..." into THEIR Files block as the release note. "released"
# was not a recognized marker, so that sentence's own path mention re-read as
# a claim under the still-OPEN `basketball-model-owner` header -- and blocked
# the very session that had just released it, in its own worktree, on the
# very next edit. Same shape as "not taken": a disclaimer about this hook's
# own prior state (here, a claim transfer) needs the same fix as a
# disclaimer about a file never touched.
_DISCLAIMER_MARKERS = (
    "not claimed",
    "collision check",
    "read-only dependency",
    "read-only reference",
    "not touched",
    "not touch",
    "not taken",
    "released",
    "held by",
    "claimed by",
    "ownership checked",
    "zero mentions",
    "no lane",
    # 2026-09-03: `render.yaml` was reported CONTESTED by the two lanes most
    # carefully avoiding it -- both wrote "**never `render.yaml`**", a
    # PROHIBITION, and every marker above spells the same idea a different way
    # ("not touch", "not taken", "released") while `never` was missing. On the
    # repo's highest-blast-radius file, that is the worst place to cry wolf.
    # Safe as a PREFIX cut: a path BEFORE the word is still claimed, so
    # "`a.py` (never deployed)" keeps claiming `a.py`.
    "never",
)


def _mask_backticked(line):
    """`line` with every backtick-quoted span blanked out, same length.

    A MARKER INSIDE A PATH IS PART OF THE FILENAME, NOT A DISCLAIMER. Found
    2026-09-03 by a lane that tried to claim `scripts/archive_released_lanes.py`
    -- whose NAME contains "released" -- and got `scripts/archive` instead,
    because `_claimable_prefix` cut at the marker it found inside the filename.
    The cut is a PREFIX, so it did not merely mangle that one token: every path
    listed AFTER it on the same line was dropped too. A three-file Files line
    became one broken token, and both the lane and the guard read that as normal.

    The ledger writes paths in backticks by convention, and every disclaimer
    incident on record puts its marker in PROSE, outside them:
    "**NOT claimed, deliberately:** `x.py`", "Collision check: CLEAR",
    "held by OPEN lane `other`", "**never `render.yaml`**". So blanking the
    quoted spans before looking for markers keeps every one of those working and
    stops the parser reading a filename as a sentence about a filename.

    Positions are preserved (same length) so the caller can cut the ORIGINAL
    string at an index found in the mask.
    """
    out = []
    inside = False
    for ch in line:
        if ch == "`":
            inside = not inside
            out.append("`")
        else:
            out.append("\x00" if inside else ch)
    return "".join(out)


def _is_disclaimer(line):
    """True when this Files-block bullet talks ABOUT a path instead of claiming it.

    NOT CALLED BY `_claims()` -- kept because `archive_released_lanes.py` reads
    it, and because it documents the predicate `_claimable_prefix` implements
    positionally. It was ALSO named in a comment inside `_claims` that claimed
    it did the skipping; it never has, and that comment is now corrected.
    """
    text = _mask_backticked(line.lstrip("- ").strip().strip("*_")).lower()
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
    # Markers are located in the BACKTICK-MASKED copy so a marker word occurring
    # inside a quoted path (`scripts/archive_released_lanes.py`) is not read as a
    # sentence about that path -- see `_mask_backticked`. The mask is the same
    # length as the line, so the index found there cuts the ORIGINAL correctly.
    low = _mask_backticked(line).lower()
    positions = [low.find(m) for m in _DISCLAIMER_MARKERS]
    positions = [p for p in positions if p != -1]
    return line[:min(positions)] if positions else line


def _norm(p):
    return p.replace("\\", "/").strip("/")


def _paths_in(text):
    """Pull path-looking tokens out of a claim line."""
    out = []
    for tok in re.split(r"[,\s]+", text or ""):
        # STRIP ASYMMETRICALLY. The right side keeps the original set; the
        # left side is the same set MINUS the dot, because a LEADING dot is
        # part of the path, not punctuation.
        #
        # Measured 2026-08-31: the symmetric strip turned `.syndicate/x.md`
        # into `syndicate/x.md`, and since matching is `rel.endswith("/" + f)`,
        # `.syndicate/x.md`.endswith("/syndicate/x.md") is FALSE -- so EVERY
        # claim under a dot-directory (`.syndicate/`, `.claude/`) named a file
        # it could never match and guarded nothing, silently. One live instance:
        # `exchange-join-refusals` on a findings doc.
        #
        # The right side must keep the dot so a trailing sentence period still
        # goes; dropping it there leaves a token like ``x.py`.`` ending in a
        # backtick, which is how the first cut of this fix broke a DIFFERENT
        # claim while repairing this one.
        tok = tok.strip().rstrip("`<>*_()[].,;").lstrip("`<>*_()[],;")
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
            # `_claimable_prefix` still cuts at "NOT claimed, deliberately".
            # (An earlier version of this comment credited `_is_disclaimer`,
            # which `_claims` has never called. Corrected 2026-09-03.)
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


# --- Convenience wrappers. These are the ONLY new code in this file. ---


def claims_by_path(text):
    """{claimed_path: {slug, ...}} over every OPEN lane."""
    out = {}
    for slug, f in _claims(text):
        out.setdefault(f, set()).add(slug)
    return out


def matches(rel, claimed):
    """The claim-vs-path test, exactly as `lane-guard.main()` writes it.

    Shared so a second caller cannot invent a subtly different one. The
    suffix arms are what let a bare `check_lane_invariants.py` in the ledger
    guard `scripts/check_lane_invariants.py` on disk -- and `learnings.md`
    records a case where a suffix match hid a path bug by accident, so this
    is deliberately NOT tightened here without re-reading that entry.
    """
    return rel == claimed or rel.endswith("/" + claimed) or claimed.endswith("/" + rel)


def is_exempt(path):
    """True for the ledger and the harness config, which are never lane-guarded.

    Same predicate `lane-guard.main()` applies, and it is load-bearing for any
    reconciliation built on top: `.syndicate/lanes.md` is claimed by an OPEN
    lane RIGHT NOW and is modified constantly by every session that
    checkpoints. A watcher without this exemption warns forever, and a warning
    that always fires is one people learn to scroll past -- which is how this
    repo has already lost two guards.

    Checks the PATH ITSELF for a `.syndicate`/`.claude` segment rather than its
    position relative to a root, so it is true in the primary tree and in any
    linked worktree alike. That distinction is not cosmetic: it is the exact
    bug fixed in `lane-guard` on 2026-08-18.
    """
    norm = _norm(path)
    return any(
        norm == marker or norm.startswith(marker + "/") or ("/" + marker + "/") in ("/" + norm)
        for marker in (".syndicate", ".claude")
    )

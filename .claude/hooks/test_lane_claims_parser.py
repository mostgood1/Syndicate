#!/usr/bin/env python3
"""Pathological fixtures for the shared lane-claim parser.

WHY THIS EXISTS. Until 2026-09-03 the only regression net for this parser was a
differential against the LIVE `lanes.md`: parse it with the old code and the
new, assert the claim sets match. Session c38d3e5c pointed out the flaw and it
is a good one -- the rows that discriminate a correct parser from a subtly
wrong one are the PATHOLOGICAL ones, and those are being repaired as fast as
they are found. Two phantom-shaped rows were fixed that same day. Over today's
ledger both parsers now agree trivially on rows that no longer test anything,
and the differential goes green while testing less each week.

So the corpus is pinned HERE, synthetic, and only grows. Every case below is a
real incident already written up in `lane_claims.py`'s own comments; this file
turns those comments into assertions. It reads no ledger and no git history:
`learnings.md` forbids a guard test that asserts against the live ledger, and
asserting against a historical revision has the same defect one step removed --
it still depends on a file this repo rewrites.

Run: python .claude/hooks/test_lane_claims_parser.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lane_claims import _claims, _paths_in, _claimable_prefix, matches, is_exempt

PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print("  %s  %-62s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        print("          got  %r" % (got,))
        print("          want %r" % (want,))


def claims(text):
    return sorted(set(_claims(text)))


def lane(slug, status, body):
    return "### %s \u2014 %s \u2014 opened 2026-09-03 \u2014 session x\n%s\n" % (slug, status, body)


print("HEADER PARSING")

check("em-dash header, OPEN, claims its file",
      claims(lane("a", "OPEN", "- Files: `x/a.py`")),
      [("a", "x/a.py")])

check("CLOSED lane claims nothing",
      claims(lane("a", "CLOSED", "- Files: `x/a.py`")), [])

# `\bOPEN\b` rejects REOPENED by design. Asserted so the intent is explicit and
# so nobody 'fixes' it into a substring match, which is the v2 bug the
# session-start hook records: "NO LANE WAS EVER OPENED" counted as open.
check("REOPENED is NOT open -- its claims are unenforced (by design)",
      claims(lane("a", "**REOPENED 2026-09-03 for the READ side**", "- Files: `x/a.py`")),
      [])
check("OPENED is not OPEN either",
      claims(lane("a", "OPENED", "- Files: `x/a.py`")), [])
check("free-text status containing the word OPEN still counts",
      claims(lane("a", "DEPLOYED, MEASUREMENT OPEN", "- Files: `x/a.py`")),
      [("a", "x/a.py")])

# ASCII hyphens: a header written `### slug - OPEN - ...` must STILL claim, or
# the lane is silently unguarded. Five sat in that state on 2026-08-17.
check("ASCII-hyphen header still claims (protection before pressure)",
      claims("### a - OPEN - opened 2026-09-03\n- Files: `x/a.py`\n"),
      [("a", "x/a.py")])

check("a `### ` header that parses as nothing does not inherit the last lane",
      claims(lane("a", "OPEN", "- Files: `x/a.py`")
             + "### (superseded lane detail follows)\n- Files: `x/stolen.py`\n"),
      [("a", "x/a.py")])

print()
print("THE Files BLOCK, in every shape the ledger writes it")

check("bold `- **Files (...):**` form (32-of-37 vs 5-of-37 drift, 2026-08-18)",
      claims(lane("a", "OPEN", "- **Files (exclusive to this lane):** `x/a.py`")),
      [("a", "x/a.py")])

check("wrapped continuation line, no leading dash",
      claims(lane("a", "OPEN", "- Files (claimed 2026-09-03):\n  `x/a.py`,\n  `x/b.py` (new).")),
      [("a", "x/a.py"), ("a", "x/b.py")])

check("nested bullets continue the block",
      claims(lane("a", "OPEN", "- Files:\n  - `x/a.py`\n  - `x/b.py`")),
      [("a", "x/a.py"), ("a", "x/b.py")])

check("a new top-level field ends the block",
      claims(lane("a", "OPEN", "- Files: `x/a.py`\n- Goal: rewrite `x/notmine.py`")),
      [("a", "x/a.py")])

check("dot-directory paths survive (the 2026-08-31 leading-dot strip)",
      claims(lane("a", "OPEN", "- Files: `.syndicate/f.md`, `.claude/hooks/h.py`")),
      [("a", ".claude/hooks/h.py"), ("a", ".syndicate/f.md")])

print()
print("DISCLAIMERS -- a prefix cut, not a whole-line veto")

check("marker at the FRONT disclaims everything after it",
      claims(lane("a", "OPEN", "- Files:\n  - **NOT claimed, deliberately:** `x/theirs.py`")),
      [])

check("marker MID-LINE keeps the paths before it",
      claims(lane("a", "OPEN", "- Files: `x/a.py`, `x/b.py`. Collision check RUN: CLEAR.")),
      [("a", "x/a.py"), ("a", "x/b.py")])

check("`held by` after the filenames still disclaims them (2026-08-19)",
      claims(lane("a", "OPEN", "- Files: `x/a.py`\n  - Does NOT touch `x/b.py` (held by other-lane).")),
      [("a", "x/a.py")])

check("`never` is a PROHIBITION, not a claim (f57a02f2)",
      claims(lane("a", "OPEN", "- Files: `x/a.py`, and **never `render.yaml`**")),
      [("a", "x/a.py")])

check("`released` retires a claim",
      claims(lane("a", "OPEN", "- Files: released: `x/a.py`")), [])

print()
print("A FILENAME IS NOT A DISCLAIMER  <-- found 2026-09-03, in this lane's own block")

# `scripts/archive_released_lanes.py` CONTAINS the marker "released". The prefix
# cut fired inside the filename, truncating it to `scripts/archive_` -> and
# because the cut is a PREFIX, every path after it on the line went too. The
# lane declaring it silently held one mangled token instead of three files.
check("a path whose FILENAME contains a marker word is still claimed",
      _paths_in(_claimable_prefix("- Files: `scripts/archive_released_lanes.py`")),
      ["scripts/archive_released_lanes.py"])

check("  ^ and the paths AFTER it survive (the prefix cut dropped them)",
      _paths_in(_claimable_prefix(
          "- Files: `scripts/archive_released_lanes.py`, `x/a.py`, `x/b.py`")),
      ["scripts/archive_released_lanes.py", "x/a.py", "x/b.py"]),

check("  ^ a marker in PROSE after that path still disclaims what follows",
      _paths_in(_claimable_prefix(
          "- Files: `scripts/archive_released_lanes.py`, held by other-lane: `x/b.py`")),
      ["scripts/archive_released_lanes.py"])

check("  ^ and a real front-loaded disclaimer is unaffected",
      _paths_in(_claimable_prefix(
          "- **NOT claimed:** `scripts/archive_released_lanes.py`")),
      [])

print()
print("TOKENISATION")

check("prose words are not paths",
      _paths_in("the rule is that we grep for it"), [])
check("a version-like token is not a path", _paths_in("15.0 and 1/p"), ["1/p"])
check("trailing sentence punctuation is stripped",
      _paths_in("`x/a.py`."), ["x/a.py"])

print()
print("MATCHING AND EXEMPTION")

check("bare filename claim guards the real path (suffix arm)",
      matches("scripts/check_lane_invariants.py", "check_lane_invariants.py"), True)
check("suffix arm does not match a different directory's same-named file",
      matches("a/x.py", "b/x.py"), False)
check(".syndicate/ is exempt", is_exempt(".syndicate/lanes.md"), True)
check(".claude/ is exempt", is_exempt(".claude/settings.json"), True)
check("a worktree path is exempt too (not root-relative)",
      is_exempt("C:/tmp/syndicate-sessions/lane/.syndicate/lanes.md"), True)
check("ordinary source is not exempt", is_exempt("syndicate/blueprints/ops.py"), False)

print()
print("%d/%d passed" % (PASS, PASS + FAIL))
sys.exit(1 if FAIL else 0)

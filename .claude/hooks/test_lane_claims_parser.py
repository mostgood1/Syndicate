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
print("check_lane_claims SEVERITY: fail on what can never resolve, report the rest")

# These drive `scripts/check_lane_claims.py` end to end against throwaway repos.
# The split exists because the first version failed on all nine broken shapes it
# found, three of which needed no action -- and this runs at every session start,
# where a check that cries wolf gets ignored. Raised by session c38d3e5c.
import json
import shutil
import subprocess
import tempfile

# .../Syndicate/.claude/hooks/<this file>  -> three levels up is the repo.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKER = os.path.join(REPO, "scripts", "check_lane_claims.py")
_TMP = []


def run_checker(files_line, extra_files=()):
    """(exit_code, stdout) for a one-lane ledger claiming `files_line`."""
    d = tempfile.mkdtemp(prefix="claimcheck-")
    _TMP.append(d)
    shutil.copytree(os.path.join(REPO, ".claude", "hooks"),
                    os.path.join(d, ".claude", "hooks"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(d, "scripts"))
    shutil.copy(CHECKER, os.path.join(d, "scripts", "check_lane_claims.py"))
    os.makedirs(os.path.join(d, ".syndicate"))
    with open(os.path.join(d, ".syndicate", "lanes.md"), "w", encoding="utf-8") as fh:
        fh.write("## OPEN\n\n### a — OPEN — x\n- Files: %s\n" % files_line)
    for rel in extra_files:
        p = os.path.join(d, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("x\n")
    subprocess.run(["git", "init", "-q", d], capture_output=True)
    subprocess.run(["git", "-C", d, "add", "-A"], capture_output=True)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=d)
    r = subprocess.run([sys.executable, os.path.join(d, "scripts", "check_lane_claims.py")],
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout


rc, out = run_checker("`a/real.py`", extra_files=["a/real.py"])
check("a claim on a file that exists -> clean", (rc, "[ok" in out), (0, True))

rc, out = run_checker("`scripts/{build_recon,verify_gate}.py`", extra_files=["scripts/build_recon.py"])
check("brace expansion FAILS (can never resolve)", rc, 1)

rc, out = run_checker("`data/live/box_*.json`", extra_files=["data/live/box_1.json"])
check("a glob FAILS (claims match literally)", rc, 1)

rc, out = run_checker("`away_key`/`home_key` stamping", extra_files=["a/real.py"])
check("prose read as a path FAILS", rc, 1)

# The worked example from this repo: live -> lines. Demoting every absent path to
# a warning would have let this through, which is why the neighbour check exists.
rc, out = run_checker("`tests/test_ncaaf_live_autorun.py`",
                      extra_files=["tests/test_ncaaf_lines_autorun.py"])
check("absent path WITH a near neighbour FAILS (a typo)", rc, 1)
check("  ^ and the message names the neighbour",
      "test_ncaaf_lines_autorun.py" in out and "TYPO" in out, True)

rc, out = run_checker("`tests/test_something_entirely_new.py`", extra_files=["a/real.py"])
check("absent path with NO neighbour is REPORTED, not failed", rc, 0)
check("  ^ but it is still printed", "does not exist" in out, True)
check("  ^ and named", "test_something_entirely_new.py" in out, True)

for d in _TMP:
    shutil.rmtree(d, ignore_errors=True)

print()
print("%d/%d passed" % (PASS, PASS + FAIL))
sys.exit(1 if FAIL else 0)

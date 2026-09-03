"""Check `.syndicate/lanes.md`'s INVARIANTS -- never which lane holds what.

WHY THIS EXISTS. The lane system's whole purpose is that two sessions never edit
one file at once, and `lane-guard.py` enforces that per-edit. Nothing checks the
LEDGER ITSELF, so the failures that matter are the ones the guard cannot see:

- **A file claimed by two OPEN lanes.** The guard blocks the second editor with a
  message naming the first, which reads like a normal conflict rather than a
  ledger defect. Measured 2026-08-17: FOUR files were in this state at once.

- **An OPEN lane filed under `## Archived lanes`.** Archiving moves its body to
  `lanes_closed.md`, which `lane-guard` never reads (it opens `lanes.md` only),
  so the lane's file protection disappears SILENTLY. Found 2026-08-16 with seven
  such lanes, and again within the hour on a lane someone restored.

- **A phantom claim.** `_claims()` treats every indented line under `- Files:` as
  a claim, so a disclaimer written there ("X names `foo.py` as a candidate --
  a DIFFERENT file") claims `foo.py`. `ask-sport-coverage` was bitten by this and
  it blocked another lane's one-line fix.

WHY IT ASSERTS PROPERTIES AND NEVER NAMES A LANE. The first version of this check
hardcoded the lane it expected to hold a path, and reported a false failure an
hour later -- not because anything broke, but because that lane closed and
another legitimately took the file. **Exactly one holder was true the whole
time.** The roster turns over hourly here; a check naming a lane has a shelf life
measured in hours, a check naming a property does not.

PARSING IS COPIED FROM `lane-guard.py`, NOT IMPORTED. That module is a hook: it
runs `main()` at import and, with stdin at EOF, calls `sys.exit()` -- which kills
the importing script with **exit code 0 and no output**. Two attempts to reuse it
died exactly that way and looked like "the parser returned nothing". If the four
regexes or the disclaimer-marker tuple below ever drift from the hook's, this
check silently measures something else; `tests/test_check_lane_invariants.py`
pins all five against the hook's source.

CONFIRMED DRIFT, 2026-08-19: `FILES_RE` here was missing the hook's bold-form
(`\\*{0,2}`) and optional-colon (`:?`) support, and `claims()` never learned the
hook's disclaimer-marker stripping at all (see `_claimable_prefix` below) -- so
a lane that wrote "RELEASED, no longer claimed: `X`" under its `- Files:` block
still read here as a live claim on `X`, and a second lane's genuine claim on the
same file then reported as a false two-holder contest. `lane-guard.py` itself
had already learned to strip that disclaimer; this file just hadn't copied the
fix. Both are fixed now; `test_disclaimer_markers_match_the_hook_source` guards
the marker tuple the same way `test_regex_matches_the_hook_source` guards the
regexes, so this is the second drift caught, not the first, and should be the
last for these two.

    py -3 scripts/check_lane_invariants.py [path]
    exit 0 = invariants hold, 1 = violated, 2 = could not read

Deliberately NOT enforced: the phantom-claim scan is a HINT, printed and never
failed on, because it cannot distinguish a genuine multi-line `Files:` list from
prose. A check that cries wolf gets ignored, and this file already has enough
things nobody reads.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

# Copied verbatim from `.claude/hooks/lane-guard.py`. See the module docstring.
HEADER_RE = re.compile(r"^###\s")
LANE_RE = re.compile(r"^###\s+(\S+)\s+—\s*([^—]*)")
OPEN_RE = re.compile(r"\bOPEN\b")
FILES_RE = re.compile(r"^\s*-\s*\*{0,2}Files\b[^:]*:?(.*)$")

# Also copied verbatim from lane-guard.py's `_DISCLAIMER_MARKERS`. A bullet
# under `- Files:` that talks ABOUT a path ("released", "held by", "not
# taken", ...) instead of claiming it. See the hook's own docstring for the
# full incident history behind each entry -- this file only needs to
# reproduce the list, not re-derive it, and `test_disclaimer_markers_match_
# the_hook_source` keeps the two from drifting apart the way `FILES_RE` did.
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

PATH_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+")
PROSE_HINT_RE = re.compile(r"\bnames?\b|\bDIFFERENT file\b|\bcandidate\b|\bclaimed by\b")


# The two markers `git` writes that CANNOT occur in prose. `=======` is
# deliberately NOT in this tuple: a markdown setext H1 underline is a run of
# `=` on its own line, so keying on it would refuse a legitimate ledger. The
# open/close markers carry seven chars plus a label and have no honest reading.
_CONFLICT_MARKERS = ("<<<<<<< ", ">>>>>>> ")


def conflict_markers(text: str) -> list[tuple[int, str]]:
    """Unresolved merge markers, as (line number, line).

    ----------------------------------------------------------------------
    WHY THIS RUNS BEFORE EVERY OTHER CHECK
    ----------------------------------------------------------------------

    MEASURED 2026-08-30. `.syndicate/lanes.md` sat in the shared tree as `UU`
    with markers at lines 3724/3778/3966 -- a `git stash pop` nobody finished --
    and this script printed **INVARIANTS HOLD** against it. It parsed BOTH
    sides as real lanes, so `mlb-resolver-write-side-effect` existed twice and
    was counted as two legitimate blocks rather than as the signature of a
    corrupted file.

    That is worse than having no check. This script is what a session runs
    BEFORE committing the ledger, so a green here is exactly the reassurance
    that precedes writing the damage in. Three OPEN lanes existed only inside
    the "Stashed changes" side, with zero copies in HEAD and zero in
    `origin/main`; resolving toward the other side would have dropped them to
    zero copies anywhere -- the `todo.md` scenario CLAUDE.md warns about.

    A CONFLICTED FILE IS NOT A LEDGER WITH VIOLATIONS. It is a file whose
    contents are two files, so every downstream count is meaningless -- claims,
    headings, holders. Hence a distinct exit code (3) and an early return: the
    honest answer is "this cannot be checked", not "this failed", and certainly
    not "this passed".
    """
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(_CONFLICT_MARKERS):
            found.append((number, line.rstrip()))
    return found


def _claimable_prefix(line: str) -> str:
    """Everything in `line` before the first disclaimer marker -- copied from
    lane-guard.py's function of the same name. A marker GOVERNS WHAT FOLLOWS
    IT, so this is a prefix cut, not a whole-line veto: a claim that precedes
    a disclaimer ("`a.py`, `b.py` (new). Collision check: CLEAR.") keeps its
    real paths and only drops what the disclaimer talks about."""
    low = line.lower()
    positions = [low.find(m) for m in _DISCLAIMER_MARKERS]
    positions = [p for p in positions if p != -1]
    return line[:min(positions)] if positions else line


def claims(text: str) -> set[tuple[str, str]]:
    """(slug, path) for every OPEN lane, exactly as `lane-guard._claims` does."""
    out: set[tuple[str, str]] = set()
    slug, open_lane, in_files = None, False, False
    for line in text.splitlines():
        if HEADER_RE.match(line):
            m = LANE_RE.match(line)
            slug, open_lane = (m.group(1), bool(OPEN_RE.search(m.group(2)))) if m else (None, False)
            in_files = False
            continue
        m = FILES_RE.match(line)
        if m:
            in_files = True
            if open_lane:
                out.update((slug, f) for f in PATH_RE.findall(_claimable_prefix(m.group(1))))
            continue
        if in_files and open_lane:
            stripped = line.strip()
            # A new top-level field ends the block; a continuation bullet
            # (`- \`path\``) does not.
            if stripped.startswith("- ") and not stripped.startswith("- `"):
                in_files = False
                continue
            out.update((slug, f) for f in PATH_RE.findall(_claimable_prefix(line)))
    return out


def contested_files(claim_set) -> dict[str, list[str]]:
    by_file = collections.defaultdict(set)
    for slug, path in claim_set:
        by_file[path].add(slug)
    return {p: sorted(s) for p, s in by_file.items() if len(s) > 1}


def open_lanes_under_archived(text: str) -> list[str]:
    """OPEN lanes filed below the `## Archived lanes` HEADING.

    THE MARKER MUST BE MATCHED AS A HEADING, NOT AS A SUBSTRING. This used
    `text.index("## Archived lanes")`, a plain substring search, so any PROSE
    that merely mentioned the heading moved the slice to wherever that sentence
    sat -- and this file's whole job is to be trusted about where lanes live.

    Measured 2026-08-18, and self-inflicted, which is the useful part: a session
    wrote an orphan-sweep record into the TOP of `lanes.md` containing the
    sentence "THE 7 REMAINING `OPEN`-UNDER-`## Archived lanes` ARE NOT MINE TO
    FIX." That put the literal marker at lines 56 and 58, ABOVE `## OPEN`, so
    the slice began above every open lane and the check reported **11 strays
    where there were 7**. The four extras -- `ask-sport-coverage`,
    `live-game-line-projection` (twice) and `refresh-worker-oom-recurrence` --
    are filed correctly under `## OPEN` and were never strays at all.

    The failure direction is what makes it worth a docstring: a report of MORE
    violations than exist reads as vigilance, so nobody doubts it. The 7 -> 11
    jump was written up as "four other sessions opened lanes while the count was
    being watched" -- a plausible story for a number that had a mechanical
    cause. An instrument that cannot be wrong in the reassuring direction still
    has to be checked in the alarming one.

    `(?m)^## Archived lanes` costs nothing and cannot be moved by prose, because
    a heading is the one thing prose cannot accidentally be.
    """
    m0 = re.search(r"(?m)^## Archived lanes", text)
    if not m0:
        return []
    arch = text[m0.start():]
    return [m.group(1) for m in re.finditer(r"(?m)^### (\S+) —\s*([^—]*)", arch)
            if OPEN_RE.search(m.group(2))]


def prose_paths_in_files_blocks(text, claim_set=None):
    """Indented lines that look like prose AND name a path. HINT ONLY.

    Each hit is `(line, claims_it)`. THE SECOND HALF IS THE POINT: this hint used
    to announce that every line it found "becomes a CLAIM", which stopped being
    true when `claims()` learned the hook's disclaimer stripping (see
    `_claimable_prefix`). A line reading "released: `x.py`" is flagged here --
    correctly, a human should confirm the marker is deliberate -- but it claims
    NOTHING, and saying otherwise sends the reader to fix a ledger that is right.

    Measured 2026-09-02: that exact wording was read off this tool for
    `artifact_publisher.py` and reported as a live false claim. The path was
    never in the claim set; the MESSAGE was the defect. Sibling of the standing
    rule that a healthy reading is evidence only once you know what makes it read
    unhealthy -- here an UNhealthy reading was emitted for a healthy ledger.

    Membership is tested against the REAL claim set rather than re-deriving it,
    so this can never drift from what the guard actually enforces.
    """
    if claim_set is None:
        claim_set = claims(text)
    claimed_paths = {path for _slug, path in claim_set}
    hits, in_files = [], False
    for line in text.splitlines():
        if HEADER_RE.match(line):
            in_files = False
            continue
        if FILES_RE.match(line):
            in_files = True
            continue
        if in_files:
            stripped = line.strip()
            if stripped.startswith("- ") and not stripped.startswith("- `"):
                in_files = False
                continue
            if PROSE_HINT_RE.search(line) and PATH_RE.search(line):
                claims_it = any(p in claimed_paths for p in PATH_RE.findall(line))
                hits.append((stripped[:100], claims_it))
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=".syndicate/lanes.md")
    ap.add_argument("--quiet", action="store_true", help="print only violations")
    args = ap.parse_args(argv)

    try:
        text = pathlib.Path(args.path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read {args.path}: {exc}")
        return 2

    # BEFORE ANY PARSING. See `conflict_markers`: a conflicted file is two
    # files, so every count below would be computed over both sides at once.
    conflicted = conflict_markers(text)
    if conflicted:
        print(f"[FAIL] {args.path} has UNRESOLVED MERGE MARKERS -- not a ledger")
        for number, line in conflicted:
            print(f"        line {number}: {line[:72]}")
        print()
        print("CANNOT CHECK: resolve the conflict first. Do NOT commit this file.")
        print("A lane may exist on ONLY ONE side -- resolving toward the other")
        print("drops it to zero copies. Diff both sides before choosing.")
        return 3

    claim_set = claims(text)
    contested = contested_files(claim_set)
    stray = open_lanes_under_archived(text)
    prose = prose_paths_in_files_blocks(text, claim_set)

    if not args.quiet:
        print(f"{args.path}: {len(re.findall(r'(?m)^### ', text))} headings, "
              f"{len({s for s, _ in claim_set})} OPEN lanes, {len(claim_set)} claims")
        print()

    print(f"[{'FAIL' if contested else 'ok  '}] every claimed file has exactly one OPEN holder")
    for path, holders in sorted(contested.items()):
        print(f"        {path}")
        print(f"          held by: {', '.join(holders)}")

    print(f"[{'FAIL' if stray else 'ok  '}] no OPEN lane under '## Archived lanes'")
    for slug in stray:
        print(f"        {slug}  (its claims survive, but archiving it would drop them)")

    really = [line for line, claims_it in prose if claims_it]
    disclaimed = [line for line, claims_it in prose if not claims_it]
    print(f"[hint] {len(prose)} prose line(s) inside a '- Files:' block name a path: "
          f"{len(really)} DO claim it, {len(disclaimed)} disclaimed by a marker")
    for line in really[:5]:
        print(f"        CLAIMS      {line}")
    for line in disclaimed[:5]:
        print(f"        disclaimed  {line}  <- verify the marker is intended")

    failures = []
    if contested:
        failures.append(f"{len(contested)} contested file(s)")
    if stray:
        failures.append(f"{len(stray)} OPEN lane(s) under Archived")
    print()
    print("INVARIANTS HOLD" if not failures else "VIOLATED: " + "; ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

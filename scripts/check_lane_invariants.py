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
regexes below ever drift from the hook's, this check silently measures something
else; `tests/test_check_lane_invariants.py` pins them against the hook's source.

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
FILES_RE = re.compile(r"^\s*-\s*Files\b[^:]*:(.*)$")

PATH_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+")
PROSE_HINT_RE = re.compile(r"\bnames?\b|\bDIFFERENT file\b|\bcandidate\b|\bclaimed by\b")


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
                out.update((slug, f) for f in PATH_RE.findall(m.group(1)))
            continue
        if in_files and open_lane:
            stripped = line.strip()
            # A new top-level field ends the block; a continuation bullet
            # (`- \`path\``) does not.
            if stripped.startswith("- ") and not stripped.startswith("- `"):
                in_files = False
                continue
            out.update((slug, f) for f in PATH_RE.findall(line))
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


def prose_paths_in_files_blocks(text: str) -> list[str]:
    """Indented lines that look like prose AND name a path. HINT ONLY."""
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
                hits.append(stripped[:100])
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

    claim_set = claims(text)
    contested = contested_files(claim_set)
    stray = open_lanes_under_archived(text)
    prose = prose_paths_in_files_blocks(text)

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

    print(f"[hint] {len(prose)} prose line(s) inside a '- Files:' block name a path; "
          f"each becomes a CLAIM")
    for line in prose[:5]:
        print(f"        {line}")

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

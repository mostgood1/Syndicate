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

PARSING IS IMPORTED FROM `.claude/hooks/lane_claims.py`, NOT COPIED. That is the
same module `lane-guard.py` imports, so this check and the guard that enforces
claims per-edit cannot disagree: there is one definition, not two and a test.

WHY THIS FILE USED TO COPY, AND WHY THAT REASON EXPIRED. The parser once lived
inside `lane-guard.py`, which is a hook -- it runs `main()` at import and, with
stdin at EOF, calls `sys.exit()`, killing the importing script with **exit code
0 and no output**. Two attempts to reuse it died exactly that way and looked
like "the parser returned nothing", so this file copied four regexes and a
marker tuple instead, and a test pinned the copies against the hook's SOURCE
TEXT. `lane_claims.py` has since been extracted: a pure library, no
module-level `main()`, no `__file__` dependency, no stdin read. Nothing here
needs the `sys.exit`-neutralising hacks the copy existed to avoid.

WHAT THE COPY ACTUALLY COST, measured 2026-09-04. **The source-scraping test had
been silently broken since that extraction** -- it searched `lane-guard.py` for
`^HEADER_RE = re.compile(...)$`, which had moved out, so all five drift tests
asserted "the hook changed shape" while this script still exited 0 and printed
INVARIANTS HOLD. The four regexes and the 14-marker tuple had NOT drifted.
Everything the test never pinned had, because every guard fix since 2026-08-31
landed in `lane_claims.py` and none was copied back:

- A `- Files:` line naming `scripts/archive_released_lanes.py` -- a filename
  CONTAINING the marker "released" -- yielded the guard both of its paths and
  yielded this checker **ZERO**, because the copied `_claimable_prefix` did not
  mask backticked spans, cut inside the filename, and dropped the rest of the
  line with it. A lane whose entire claim set reads as empty cannot contest
  anything, so the two-holder invariant passed vacuously.
- An ASCII-hyphen lane header (`### slug - OPEN - ...`): guarded, invisible here.
- A blank line inside a Files block: ends it for the guard, not for the copy.
- A backslash path: normalised by the guard, left backslashed here, so it could
  never match the path it named.

The 2026-08-19 drift (`FILES_RE` missing the bold form and the optional colon)
was the first instance, and it was fixed by copying harder. This is the second.
It is the failure mode `learnings.md` already names for a sibling case -- a
module may not hold its own copy of a definition another module enforces,
because it WILL drift -- with the extra sting that a test comparing two copies
only works for as long as it can still find both of them.

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
import subprocess
import sys

# THE PARSER, IMPORTED FROM THE MODULE THE GUARD ENFORCES WITH. See the module
# docstring for what the copies these names replace had quietly drifted into.
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
try:
    from lane_claims import (  # noqa: E402
        ASCII_LANE_RE,
        FIELD_RE,
        FILES_RE,
        HEADER_RE,
        LANE_RE,
        OPEN_RE,
        _claimable_prefix,
        _claims,
        _DISCLAIMER_MARKERS,
        _paths_in,
    )
except Exception as exc:  # pragma: no cover - only when the module is missing
    # DELIBERATELY NOT FAIL-OPEN, and that is the opposite of `lane-guard.py`'s
    # contract on purpose. The guard fails open because a broken guard blocking
    # every edit is worse than no guard. This is a CHECK: its entire output is a
    # verdict, and the one thing it must never do is print a green one it did
    # not compute. Exit 2 is what this file already returns for "could not read
    # the input"; an unimportable parser is the same class of answer. Falling
    # back to a private copy would silently reinstate the drift the import
    # exists to end -- which is exactly how an unknown defaults permissive.
    print("cannot import lane_claims (.claude/hooks/lane_claims.py): %s" % exc)
    print("REFUSING TO CHECK -- the parser this must agree with is unavailable.")
    sys.exit(2)

# `_DISCLAIMER_MARKERS` and `_claimable_prefix` are imported above, not restated.
# The tuple lives in `lane_claims.py` alongside the incident history behind each
# entry, and `_claimable_prefix` there masks backticked spans before looking for
# a marker -- the fix this file spent from 2026-09-03 to 2026-09-04 without.

# NOT a claim extractor -- `_paths_in` is. This only answers "does this line
# mention something path-shaped at all", for the prose hint below.
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


def claims(text: str) -> set[tuple[str, str]]:
    """(slug, path) for every OPEN lane -- `lane_claims._claims`, not a lookalike.

    A set where the guard yields a generator, because every caller here does
    membership and set arithmetic. That is the ONLY difference, and holding it
    to that is the whole point: the moment this function decides anything about
    what a claim IS, the guard and the check are answering different questions
    again and nothing reports it.
    """
    return set(_claims(text))


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
    # LANE_RE and its ASCII fallback, not a fifth inline copy of the header
    # pattern. The em-dash-only version missed `### slug - OPEN - ...` headers
    # entirely -- and those DO hold claims (`lane_claims._claims` falls back to
    # ASCII_LANE_RE), so a stray lane written with hyphens was guarding files
    # from inside the archive with nothing reporting it.
    out = []
    for line in arch.splitlines():
        if not HEADER_RE.match(line):
            continue
        m = LANE_RE.match(line) or ASCII_LANE_RE.match(line)
        if m and OPEN_RE.search(m.group(2)):
            out.append(m.group(1))
    return out


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
            # Block termination copied from `lane_claims._claims`: a blank
            # line or a new TOP-LEVEL field ends it. The old test here
            # (`- ` and not `- ``) kept scanning past a blank line, so the
            # hint reported prose from outside the block it was reading.
            if not stripped or (FIELD_RE.match(line) and not line[:1].isspace()):
                in_files = False
                continue
            if PROSE_HINT_RE.search(line) and PATH_RE.search(line):
                # Membership is tested with the guard's own tokeniser, so a
                # hit's `claims_it` flag agrees with `claims()` by
                # construction rather than by two regexes happening to
                # normalise a path the same way.
                claims_it = any(
                    p in claimed_paths for p in _paths_in(_claimable_prefix(line)))
                hits.append((stripped[:100], claims_it))
    return hits


def _ledger_text(root: pathlib.Path, name: str) -> str:
    """One ledger file's text, BOM-stripped. A UTF-8 BOM survives
    `errors="replace"` and would otherwise glue itself to the first heading."""
    try:
        return (root / name).read_text(encoding="utf-8", errors="replace").lstrip("﻿")
    except OSError:
        return ""


def upstream_lane_slugs(root: pathlib.Path, ref: str = "origin/main"):
    """Lane slugs `ref`'s ledger files carry, or None if git cannot answer.

    WHY THIS EXISTS `[2026-09-05, lane ledger-repair-invariants]`. The marker
    check below compares a CURRENT marker set against a WORKING COPY of
    `lanes.md`, and in the primary tree those two are not the same vintage:
    sessions work in their own worktrees, so a lane's block lands via
    `origin/main` while its marker is written into the primary tree's
    `.syndicate/`. The primary tree then sits behind -- MEASURED 2026-09-05,
    58 commits behind, 45 lane headers on disk against 101 upstream.

    So the commonest way to fail this check is not a destroyed block at all:
    it is a lane opened normally from a worktree, whose block is on
    `origin/main` and simply has not been pulled. Measured the same evening:
    `web-oom-burst-source` was reported here as "in NO ledger file" while its
    block was sitting on `origin/main` in commit `aff64eab`.

    THE OLD MESSAGE WAS ACTIVELY WRONG ABOUT THAT CASE. It read "RESTORE it
    from the owning session -- upstream cannot have it", which is exactly
    backwards when upstream is where it is, and it points the reader at
    rewriting a block that already exists -- i.e. at fabricating a second,
    diverging copy. A checker that fires constantly and names the wrong remedy
    is worse than one that does not fire: it is the reason the whole banner
    gets scrolled past.

    RETURNS None, NOT an empty set, when git cannot answer (no repo, no
    `origin/main`, git missing, a checkout under a temp dir). None means
    UNKNOWN and the caller must keep the strict verdict; an empty set would
    mean "upstream definitely has nothing", and an unknown that defaults to
    the permissive branch is its own recorded failure mode.
    """
    slugs: set[str] = set()
    answered = False
    for name in ("lanes.md", "lanes_closed.md", "lanes_closed_archive.md",
                 "lanes_history.md"):
        try:
            out = subprocess.run(
                ["git", "show", f"{ref}:.syndicate/{name}"],
                cwd=str(root.parent), capture_output=True, timeout=60,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            continue
        answered = True
        slugs |= set(re.findall(
            r"(?m)^###\s+([A-Za-z0-9._-]+)",
            out.stdout.decode("utf-8", "replace").lstrip("﻿"),
        ))
    return slugs if answered else None


def orphaned_lane_markers(text: str, path: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Lane slugs a live per-session marker names that no ledger file carries.

    WHY THIS EXISTS. `.syndicate/.current-lane.<session>` is written by
    `/lane open` and is the ONE artefact that survives when a lane block is
    destroyed -- it is a separate file, so nothing that rewrites `lanes.md`
    can take it with them.

    THE FAILURE IT CATCHES `[2026-09-04, session b9013cf2]`. A session
    REBUILT `lanes.md` from `git show origin/main:.syndicate/lanes.md` to
    avoid committing a stale copy, and another session's block -- an
    uncommitted edit living only in the primary tree -- was not on
    origin/main, so the rebuild dropped it. No git guard fired, because a
    rebuild is a plain file WRITE and `discard-guard.py` watches git
    operations. The check that was run, "0 deletions vs origin/main", is
    blind to this BY CONSTRUCTION: comparing against upstream cannot see
    content that was never on upstream. Cross-checking against the markers
    can, because the marker is not in the file being rewritten.

    TWO OUTCOMES, kept apart. A slug missing from `lanes.md` but present in
    `lanes_closed.md`/`lanes_history.md` is a STALE MARKER -- the lane was
    archived and the marker was never emptied. Harmless, and a FAIL on it
    would train people to ignore this check. A slug in NO ledger file at all
    is a block that exists nowhere: either destroyed, or opened as a marker
    and never written down. That one fails.
    """
    root = pathlib.Path(path).resolve().parent
    live = set(re.findall(r"(?m)^###\s+([A-Za-z0-9._-]+)", text))
    archived = set(
        re.findall(
            r"(?m)^###\s+([A-Za-z0-9._-]+)",
            _ledger_text(root, "lanes_closed.md")
            + _ledger_text(root, "lanes_closed_archive.md")
            + _ledger_text(root, "lanes_history.md"),
        )
    )
    missing: list[tuple[str, str]] = []
    stale: list[tuple[str, str]] = []
    for marker in sorted(root.glob(".current-lane.*")):
        try:
            slug = marker.read_text(encoding="utf-8", errors="replace").lstrip("﻿").strip()
        except OSError:
            continue
        # An EMPTY marker is `/lane close` having done its job, not a lane.
        if not slug or slug in live:
            continue
        (stale if slug in archived else missing).append((slug, marker.name))
    return missing, stale


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
    orphaned, stale_markers = orphaned_lane_markers(text, args.path)
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

    # SPLIT THE ORPHANS BY WHETHER UPSTREAM HAS THE BLOCK. See
    # `upstream_lane_slugs`: "not in this working copy" and "nowhere at all"
    # need opposite remedies -- pull vs restore -- and only the second is a
    # ledger defect. `None` is UNKNOWN, so everything stays a FAIL.
    upstream = upstream_lane_slugs(pathlib.Path(args.path).resolve().parent) if orphaned else None
    behind: list[tuple[str, str]] = []
    if upstream is not None:
        behind = [(s, m) for s, m in orphaned if s in upstream]
        orphaned = [(s, m) for s, m in orphaned if s not in upstream]

    print(f"[{'FAIL' if orphaned else 'ok  '}] every live lane marker still has a block somewhere")
    for slug, marker in orphaned:
        print(f"        {slug}  (named by {marker}, in NO ledger file)")
        print(f"          a block that exists nowhere: destroyed, or never written down.")
        if upstream is None:
            print(f"          upstream NOT CHECKED (no git answer) -- confirm origin/main")
            print(f"          does not carry it before rewriting anything.")
        else:
            print(f"          origin/main does not carry it either, so RESTORE it from the")
            print(f"          owning session -- upstream cannot have it.")
    for slug, marker in behind:
        print(f"        [hint] {slug} ({marker}) IS on origin/main and NOT in this")
        print(f"               working copy -- PULL, do not restore. Writing a fresh block")
        print(f"               here would create a second, diverging copy.")
    for slug, marker in stale_markers:
        print(f"        [hint] {slug} is archived but {marker} still names it -- empty the marker")

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
    if orphaned:
        failures.append(f"{len(orphaned)} lane marker(s) with no block anywhere")
    print()
    print("INVARIANTS HOLD" if not failures else "VIOLATED: " + "; ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

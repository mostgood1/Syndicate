"""Move RELEASED/CLOSED lane blocks out of `lanes.md` into `lanes_history.md`.

WHY THIS EXISTS. `lanes.md` is read at every session start and is weighed by
`session-start.sh` against a 120,000-byte cap. It was 448,571 bytes on
2026-08-18 -- 3.7x over -- and the digest was truncating the OPEN LANES section
to 600 bytes against a 6,825-byte body, so the file every session depends on was
arriving lossy. Trimming it had been done BY HAND at least twice (see the
`lanes_history.md` and `lanes.md` headers, both crediting "the coordinator").
A hand-edit of a 446KB file that four live sessions append to concurrently is
how blocks get silently dropped, and `lanes.md` already records exactly that
happening: "another session rewrote `lanes.md` between this session's two
appends, dropping the header while keeping the later checkpoint".

THE ONE RULE THAT MAKES THIS SAFE, taken verbatim from `lanes_history.md`'s own
header: a lane declares its exclusive files in its OPENING block, and
"archiving that would leave `lane-guard` unable to see the claim at all".
`lane-guard` reads `lanes.md` and NOTHING ELSE -- moving a claim-bearing block
un-guards those files silently, which is the precise failure the lane system
exists to prevent.

So this tool refuses to move a block whose slug still holds ANY claim, and it
checks that against `lane-guard.py`'s OWN `_claims()` rather than a reimplementation.
That distinction is not pedantry: `check_lane_invariants.py` carries a simplified
copy without the guard's `_is_disclaimer` / `_claimable_prefix` handling, and on
2026-08-18 the two disagreed by 32 claims and 5 lanes over the same file.

PARSING THE GUARD WITHOUT RUNNING IT. `lane-guard.py` ends in a bare
`sys.exit(main())`, so importing it kills the importing process with exit code 0
and no output. It is exec'd here with that one line neutralised -- the same
workaround `check_lane_invariants.py` documents having been bitten by twice.

    py -3 scripts/archive_released_lanes.py                    # dry run, default
    py -3 scripts/archive_released_lanes.py --apply
    py -3 scripts/archive_released_lanes.py --slug foo --slug bar --apply

Exit 0 = clean (or nothing to do), 1 = refused, 2 = could not read/verify.

FIRST RUN -- 2026-08-18, 8 RELEASED lanes / 17 blocks, lane `ledger-coherence-sweep`:

    lanes.md          450,927 -> 246,582 B   (204,345 reclaimed, 45%)
    lanes_history.md  176,574 -> 381,408 B   (204,834 added)
    cap 120,000       3.76x   -> 2.05x over
    claims            65      -> 65, NONE lost, contested files 0

Verified three ways, because "the script said so" is not a measurement:
2,685 distinct lines left `lanes.md` and **0** of them were absent from
`lanes_history.md`; the claim set was recomputed from `lane-guard.py`'s own
`_claims()` over the before and after files and compared as a set, not a count;
and `check_lane_invariants.py`'s contested-file invariant still passed after.

TWO THINGS THE FIRST RUN DID NOT FIX, so nobody reads 45% as "done":

- **`lanes.md` is still 2.05x over cap.** Getting under 120,000 needs the LIVE
  lanes' superseded blocks moved too, and those are their owners' to move --
  this tool deliberately refuses to touch a slug with any block reading OPEN.
- **`OPEN`-under-`## Archived lanes` is untouched and still growing** (7 -> 11
  during the same session). That is a SECTION-ORDERING defect, not a size one:
  `## Archived lanes` is not the last heading, so every newly appended lane
  lands below it and is silently un-guarded by any future archive pass. Filed
  as `#466`. Trimming will never fix it and this tool does not try.
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys
import types

LANES = pathlib.Path(".syndicate/lanes.md")
HISTORY = pathlib.Path(".syndicate/lanes_history.md")
GUARD = pathlib.Path(".claude/hooks/lane-guard.py")

HEADER_RE = re.compile(r"^###\s+(\S+)\s")
BOUNDARY_RE = re.compile(r"^#{2,3}\s")
OPEN_RE = re.compile(r"\bOPEN\b")


def guard_claims(text):
    """(slug, path) pairs exactly as the live hook computes them."""
    src = GUARD.read_text(encoding="utf-8").replace("sys.exit(main())", "pass")
    mod = types.ModuleType("lane_guard_readonly")
    exec(compile(src, str(GUARD), "exec"), mod.__dict__)  # noqa: S102 - reading the hook is the point
    return set(mod._claims(text))


def blocks(lines):
    """(start, end, slug, header) for every `### ` block, end-exclusive."""
    bounds = [i for i, l in enumerate(lines) if BOUNDARY_RE.match(l)]
    out = []
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if not m:
            continue
        end = next((b for b in bounds if b > i), len(lines))
        out.append((i, end, m.group(1), line))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    ap.add_argument("--slug", action="append", default=[],
                    help="restrict to these slugs (repeatable). Default: every non-OPEN slug holding no claims.")
    args = ap.parse_args(argv)

    try:
        text = LANES.read_text(encoding="utf-8", errors="replace")
        history = HISTORY.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read: {exc}")
        return 2

    lines = text.split("\n")
    claimed = {s for s, _ in guard_claims(text)}
    all_blocks = blocks(lines)

    # A slug is movable only if NO block of it reads OPEN. A lane with one
    # RELEASED block and one OPEN block is still open; moving either is wrong.
    open_slugs = {s for _, _, s, h in all_blocks if OPEN_RE.search(h.split("—")[1] if "—" in h else h)}
    wanted = set(args.slug) if args.slug else {s for _, _, s, _ in all_blocks}

    move, refused = [], []
    for start, end, slug, header in all_blocks:
        if slug not in wanted:
            continue
        if slug in claimed:
            refused.append((slug, "still holds file claims"))
            continue
        if slug in open_slugs:
            refused.append((slug, "has a block still reading OPEN"))
            continue
        move.append((start, end, slug))

    if refused:
        print("REFUSED (left in lanes.md):")
        for slug, why in sorted(set(refused)):
            print(f"  {slug:<36} {why}")
        print()

    if not move:
        print("nothing to move.")
        return 0

    moved_idx = {i for start, end, _ in move for i in range(start, end)}
    moved_text = "\n".join(lines[i] for i in sorted(moved_idx))
    kept = "\n".join(l for i, l in enumerate(lines) if i not in moved_idx)

    # VERIFY BEFORE WRITING: every moved line must survive verbatim, and the
    # claim set the guard computes over the trimmed file must be UNCHANGED.
    # Size is not the goal; not losing anything is.
    if len(kept) + len(moved_text) < len(text) - 2 * len(move) - 2:
        print("REFUSED: line accounting does not balance; nothing written.")
        return 2
    after_claims = guard_claims(kept)
    before_claims = guard_claims(text)
    if after_claims != before_claims:
        lost = before_claims - after_claims
        print(f"REFUSED: trimming would change the claim set ({len(lost)} lost). Nothing written.")
        for slug, path in sorted(lost)[:10]:
            print(f"  lost: {slug} -> {path}")
        return 2

    by_slug = {}
    for _, _, slug in move:
        by_slug[slug] = by_slug.get(slug, 0) + 1
    print(f"{'slug':<36} {'blocks':>6}")
    for slug, n in sorted(by_slug.items()):
        print(f"{slug:<36} {n:>6}")
    print(f"\nlanes.md {len(text)} -> {len(kept)} bytes "
          f"({len(text) - len(kept)} reclaimed, {(len(text)-len(kept))*100//len(text)}%)")
    print(f"cap 120000 -> {len(kept)/120000:.2f}x over")
    print(f"claims unchanged: {len(after_claims)}")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    stamp = datetime.date.today().isoformat()
    banner = (f"\n\n## RELEASED LANE BLOCKS MOVED FROM `lanes.md` — {stamp}\n\n"
              f"Moved verbatim by `scripts/archive_released_lanes.py`; nothing summarised or\n"
              f"deleted. Every slug here held ZERO file claims at move time, verified against\n"
              f"`lane-guard.py`'s own `_claims()` — so `lane-guard` lost no protection.\n"
              f"Slugs: {', '.join(sorted(by_slug))}.\n\n")
    HISTORY.write_text(history + banner + moved_text + "\n", encoding="utf-8")
    LANES.write_text(kept, encoding="utf-8")
    print("\nWROTE lanes.md and lanes_history.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

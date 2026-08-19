"""Move OPEN lane blocks out of `## Archived lanes` and back under `## OPEN`.

WHY. `lane-guard` reads `lanes.md` and NOTHING else. Archiving moves a lane's
body to `lanes_closed.md`, so an OPEN lane sitting inside an archived section
loses its file protection the moment anyone runs an archive pass -- silently,
with nothing reporting it, because from the guard's side the claim simply
ceased to exist. `check_lane_invariants.py` fails on exactly this and it is
filed as `#466`.

THIS TOOL EDITS OTHER LANES' BLOCKS, WHICH THE PROTOCOL NORMALLY FORBIDS.
It exists only to be run under an explicit user mandate to fix `#466`, and it
is deliberately narrow: it moves a block VERBATIM and changes not one byte of
its content, so no lane's recorded state, claims or history is altered -- only
which section the block sits in. A lane's own words stay its own.

WHAT IT REFUSES TO DO, because those are the ways this goes wrong:

- It will not move a block that is not OPEN. Released and closed lanes belong
  where they are; `archive_released_lanes.py` is the tool for those.
- It will not run if the claim set changes. Recomputed with `lane-guard.py`'s
  OWN `_claims()` before and after and compared AS A SET, not as a count --
  two claims swapping owners keeps the count identical and is a catastrophe.
- It will not run if any line would be lost or duplicated.

ORDER IS PRESERVED. Blocks are re-inserted at the end of `## OPEN` in the order
they appeared, so a reader diffing before/after sees a move and not a shuffle.

    py -3 scripts/hoist_open_lanes.py                 # dry run, default
    py -3 scripts/hoist_open_lanes.py --apply

Exit 0 = clean (or nothing to do), 1 = refused, 2 = could not read/verify.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import types

LANES = pathlib.Path(".syndicate/lanes.md")
GUARD = pathlib.Path(".claude/hooks/lane-guard.py")

HEADER_RE = re.compile(r"^###\s+(\S+)\s")
BOUNDARY_RE = re.compile(r"^#{2,3}\s")
SECTION_RE = re.compile(r"^##\s")
OPEN_RE = re.compile(r"\bOPEN\b")
ARCHIVED_RE = re.compile(r"(?m)^## Archived lanes")
OPEN_SECTION_RE = re.compile(r"(?m)^## OPEN\s*$")


def guard_claims(text):
    """(slug, path) pairs exactly as the live hook computes them."""
    src = GUARD.read_text(encoding="utf-8").replace("sys.exit(main())", "pass")
    mod = types.ModuleType("lane_guard_readonly")
    exec(compile(src, str(GUARD), "exec"), mod.__dict__)  # noqa: S102
    return set(mod._claims(text))


def status_field(header):
    """The free text between the 1st and 2nd em-dash, where the status lives."""
    parts = re.split(r"\s[—-]\s", header, maxsplit=2)
    return parts[1] if len(parts) > 1 else header


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = ap.parse_args(argv)

    try:
        text = LANES.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read {LANES}: {exc}")
        return 2

    lines = text.split("\n")
    arch = ARCHIVED_RE.search(text)
    opensec = OPEN_SECTION_RE.search(text)
    if not arch or not opensec:
        print("REFUSED: could not locate both '## OPEN' and '## Archived lanes'.")
        return 2
    arch_line = text[:arch.start()].count("\n")
    open_line = text[:opensec.start()].count("\n")
    if open_line > arch_line:
        print("REFUSED: '## OPEN' appears after '## Archived lanes'; not a case this tool handles.")
        return 2

    # End of the ## OPEN section = the next `## ` heading after it.
    open_end = next((i for i, l in enumerate(lines)
                     if i > open_line and SECTION_RE.match(l)), len(lines))

    bounds = [i for i, l in enumerate(lines) if BOUNDARY_RE.match(l)]
    move = []
    for i, line in enumerate(lines):
        if i <= arch_line:
            continue
        m = HEADER_RE.match(line)
        if not m or not OPEN_RE.search(status_field(line)):
            continue
        end = next((b for b in bounds if b > i), len(lines))
        move.append((i, end, m.group(1)))

    if not move:
        print("nothing to move -- no OPEN lane below the archive marker.")
        return 0

    print(f"{'slug':<36} {'lines':>6}")
    for start, end, slug in move:
        print(f"{slug:<36} {end - start:>6}")

    moved_idx = {i for s, e, _ in move for i in range(s, e)}
    block_text = ["\n".join(lines[s:e]).rstrip("\n") for s, e, _ in move]
    kept = [l for i, l in enumerate(lines) if i not in moved_idx]

    # Re-insert at the end of ## OPEN, adjusting for lines removed before it.
    removed_before = sum(1 for i in moved_idx if i < open_end)
    insert_at = open_end - removed_before
    out = kept[:insert_at] + [""] + [b for t in block_text for b in (t, "")] + kept[insert_at:]
    new_text = "\n".join(out)

    # --- verification, before any write ---
    before, after = guard_claims(text), guard_claims(new_text)
    if before != after:
        lost, gained = before - after, after - before
        print(f"REFUSED: claim set changed (lost {len(lost)}, gained {len(gained)}). Nothing written.")
        for s, p in sorted(lost)[:8]:
            print(f"  lost:   {s} -> {p}")
        for s, p in sorted(gained)[:8]:
            print(f"  gained: {s} -> {p}")
        return 2

    # COMPARE THE FINAL TEXT, NOT THE LIST THAT BUILT IT. `out` holds whole
    # multi-line block strings as single elements, so counting over it treats a
    # 292-line block as one "line" and the comparison is meaningless -- it
    # reported "5 lost, 5 duplicated" against a transformation that was
    # correct. Re-split what will actually be written.
    from collections import Counter
    out_lines = new_text.split("\n")
    c_before, c_after = Counter(l for l in lines if l.strip()), Counter(l for l in out_lines if l.strip())
    if c_before != c_after:
        missing = list((c_before - c_after).elements())[:5]
        extra = list((c_after - c_before).elements())[:5]
        print(f"REFUSED: content changed ({len(missing)} lost, {len(extra)} duplicated). Nothing written.")
        for l in missing:
            print(f"  lost:      {l[:88]}")
        for l in extra:
            print(f"  duplicate: {l[:88]}")
        return 2

    still = [s for _, _, s in move]
    print(f"\nmoved {len(move)} block(s) into '## OPEN': {', '.join(still)}")
    print(f"claims unchanged: {len(after)}   non-blank lines unchanged: {sum(c_after.values())}")
    print(f"lanes.md {len(text)} -> {len(new_text)} bytes")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    # RE-READ IMMEDIATELY BEFORE WRITING. This is a read-modify-write against a
    # file several live sessions append to continuously -- `lanes.md` moved by
    # 6,015 bytes between a backup and this script's own read during the very
    # run this check was added for. Writing a buffer computed from a stale read
    # silently DELETES whatever landed in between, which is the failure
    # `lanes.md` already records ("another session rewrote lanes.md between this
    # session's two appends, dropping the header while keeping the later
    # checkpoint"). Cheap, and it turns a silent data loss into a retry.
    try:
        current = LANES.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"REFUSED: cannot re-read before writing: {exc}")
        return 2
    if current != text:
        print("REFUSED: lanes.md changed while this ran "
              f"({len(text)} -> {len(current)} bytes). Another session wrote to it.")
        print("Nothing written. Re-run -- the transformation is idempotent.")
        return 1

    LANES.write_text(new_text, encoding="utf-8")
    print("\nWROTE lanes.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

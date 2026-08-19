"""Move SUPERSEDED lane blocks out of `lanes.md` into `lanes_history.md`.

WHY A THIRD LANE TOOL. `archive_released_lanes.py` works per LANE -- it moves a
slug only when every one of its blocks is non-OPEN. That cannot touch the real
bulk, because the biggest consumers are *superseded checkpoint blocks belonging
to lanes that are still alive*: one lane had 16 blocks totalling 44,905 bytes
with the current status in only one of them. This tool works per BLOCK.

THE KEEP RULE, and both halves are load-bearing. A block stays if:

  1. it is CLAIM-BEARING -- `lane-guard` reads `lanes.md` and nothing else, so
     moving a block that declares `Files:` silently un-guards those paths. This
     is the rule `lanes_history.md`'s own header states: "PLUS any block that
     declares file claims -- a lane declares its exclusive files in its OPENING
     block, and archiving that would leave lane-guard unable to see the claim
     at all."
  2. or its header READS OPEN -- even with no claims. An open lane that
     vanishes from `lanes.md` disappears from the session-start digest, and a
     lane nobody can see is a lane two sessions will collide on.

Everything else is a dated checkpoint whose story ended, and `lanes_history.md`
is where those live. Nothing is summarised and nothing is deleted.

A LANE WHOSE BLOCKS ARE *ALL* SUPERSEDED LEAVES `lanes.md` ENTIRELY. That is
intended -- it means the lane holds no claims and is not open, i.e. it is done
-- but it is the one effect worth knowing about before running this, so it is
reported explicitly rather than buried in a byte count.

VERIFICATION BEFORE WRITING, all three, because a ledger edit that loses a claim
is worse than a large file:

  - claim set recomputed with `lane-guard.py`'s OWN `_claims()` and compared AS
    A SET, never as a count: two claims swapping owners leaves the count
    identical and is a catastrophe.
  - every non-blank line conserved across `lanes.md` + `lanes_history.md`.
  - `lanes.md` re-read immediately before the write and the run abandoned if it
    changed, because several live sessions append to it continuously.

    py -3 scripts/trim_lane_blocks.py                  # dry run, default
    py -3 scripts/trim_lane_blocks.py --apply
    py -3 scripts/trim_lane_blocks.py --cap 120000     # report against a budget

Exit 0 = clean (or nothing to do), 1 = refused, 2 = could not read/verify.
"""
from __future__ import annotations

import argparse
import collections
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


def load_guard():
    """The live hook, exec'd with its trailing `sys.exit(main())` neutralised.

    Importing it normally kills the importer with exit 0 and no output.
    """
    src = GUARD.read_text(encoding="utf-8").replace("sys.exit(main())", "pass")
    mod = types.ModuleType("lane_guard_readonly")
    exec(compile(src, str(GUARD), "exec"), mod.__dict__)  # noqa: S102
    return mod


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    ap.add_argument("--cap", type=int, default=120000, help="byte budget to report against")
    args = ap.parse_args(argv)

    g = load_guard()
    try:
        text = LANES.read_text(encoding="utf-8", errors="replace")
        history = HISTORY.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read: {exc}")
        return 2

    lines = text.split("\n")
    bounds = [i for i, l in enumerate(lines) if BOUNDARY_RE.match(l)]

    move, kept_slugs, moved_slugs = [], set(), collections.Counter()
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if not m:
            continue
        slug = m.group(1)
        end = next((b for b in bounds if b > i), len(lines))
        body = "\n".join(lines[i:end])
        # SET, not the generator. `bool(_claims(...))` on the generator object
        # is ALWAYS True -- it reported every block as claim-bearing and made
        # the movable total read as zero.
        claim_bearing = bool(set(g._claims(body)))
        hm = g.LANE_RE.match(line) or g.ASCII_LANE_RE.match(line)
        is_open = bool(g.OPEN_RE.search(hm.group(2))) if hm else False
        if claim_bearing or is_open:
            kept_slugs.add(slug)
        else:
            move.append((i, end, slug))
            moved_slugs[slug] += len(body)

    if not move:
        print("nothing to move -- every block is claim-bearing or reads OPEN.")
        return 0

    moved_idx = {i for s, e, _ in move for i in range(s, e)}
    block_text = ["\n".join(lines[s:e]).rstrip("\n") for s, e, _ in move]
    kept = "\n".join(l for i, l in enumerate(lines) if i not in moved_idx)
    moved_text = "\n\n".join(block_text)

    before, after = set(g._claims(text)), set(g._claims(kept))
    if before != after:
        lost, gained = before - after, after - before
        print(f"REFUSED: claim set changed (lost {len(lost)}, gained {len(gained)}). Nothing written.")
        for s, p in sorted(lost)[:8]:
            print(f"  lost:   {s} -> {p}")
        return 2

    c_before = collections.Counter(l for l in lines if l.strip())
    c_after = collections.Counter(l for l in (kept + "\n" + moved_text).split("\n") if l.strip())
    if c_before != c_after:
        missing = list((c_before - c_after).elements())[:5]
        print(f"REFUSED: {len(missing)} line(s) would be lost. Nothing written.")
        for l in missing:
            print(f"  lost: {l[:88]}")
        return 2

    gone = sorted(s for s in moved_slugs if s not in kept_slugs)
    print(f"{'slug':<38} {'bytes moved':>12}")
    for s, b in moved_slugs.most_common():
        print(f"{s:<38} {b:>12}{'   <- leaves lanes.md entirely' if s in gone else ''}")
    new_size = len(kept)
    print(f"\nblocks moved      : {len(move)}")
    print(f"lanes.md          : {len(text)} -> {new_size} B  ({len(text)-new_size} reclaimed)")
    print(f"cap {args.cap}      : {len(text)/args.cap:.2f}x -> {new_size/args.cap:.2f}x  "
          f"{'UNDER' if new_size < args.cap else '*** STILL OVER ***'}")
    print(f"claims unchanged  : {len(after)}")
    if gone:
        print(f"\n{len(gone)} lane(s) leave lanes.md entirely (no claims, not OPEN): {', '.join(gone)}")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    current = LANES.read_text(encoding="utf-8", errors="replace")
    if current != text:
        print(f"REFUSED: lanes.md changed while this ran ({len(text)} -> {len(current)} B). "
              "Another session wrote to it. Nothing written; re-run.")
        return 1

    stamp = datetime.date.today().isoformat()
    banner = (f"\n\n## SUPERSEDED LANE BLOCKS MOVED FROM `lanes.md` — {stamp}\n\n"
              f"Moved verbatim by `scripts/trim_lane_blocks.py`; nothing summarised or\n"
              f"deleted. Every block here was NEITHER claim-bearing NOR reading OPEN at move\n"
              f"time, verified against `lane-guard.py`'s own `_claims()` — so `lane-guard`\n"
              f"lost no protection and no open lane left the session-start digest.\n\n")
    HISTORY.write_text(history + banner + moved_text + "\n", encoding="utf-8")
    LANES.write_text(kept, encoding="utf-8")
    print("\nWROTE lanes.md and lanes_history.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

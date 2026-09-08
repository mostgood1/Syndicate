"""Fold several `learnings.md` entries into ONE, archiving the originals verbatim.

WHY A TOOL AND NOT A HAND EDIT. Consolidation is the only operation on this
ledger that can DESTROY a rule. `compact_learnings.py` never can -- it keeps the
heading and the rule line in `learnings.md` and moves only the evidence. This
one REMOVES headings from `learnings.md`, and a rule nobody can find is a rule
that gets broken again. Three sessions hand-rolled a lane-claim check on
2026-08-31 and it went wrong three different ways; the same argument applies with
more force to an operation that deletes.

THE PRECEDENT AND ITS DEFECT. `2026-08-20 — ONE ERROR IN FIVE GUISES` folded five
entries into one and moved the originals to `learnings_archive_2026-08-20.md`.
Correct in shape -- and all five rules left the INDEX that day, because
`build_learnings_index.py` spanned `learnings.md`, `learnings_evidence.md` and
`learnings_archive.md` but not the dated file. Measured 2026-09-08: none of the
five was in `learnings_index.md`. Fixed in the generator the same day (it now
spans `learnings_archive_*.md`); this tool REFUSES to run unless that fix is
present, because without it the tool's own output is unfindable by construction.

THE VERIFICATION IS `compact_learnings.py`'s, DELIBERATELY. Counter SUBTRACTION,
never equality: a heading may legitimately appear twice after the move (in the
archive, and quoted inside the consolidated entry), so `before != after` refuses
correct work. The property that matters is that nothing DISAPPEARS. Two levels,
both checked BEFORE any write:

  * every `##`/`###` heading in the input still exists somewhere in the output;
  * every non-blank LINE of a folded block still exists in the archive.

A folded entry's body is never rewritten, summarised or reflowed. It is moved.

    py -3 scripts/consolidate_learnings.py --headings-file folds.txt \\
        --entry-file consolidated.md                       # dry run
    py -3 scripts/consolidate_learnings.py ... --apply

Exit 0 = done (or dry run clean). 2 = refused, nothing written.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import io
import pathlib
import re
import sys

LEARN = pathlib.Path(".syndicate/learnings.md")
GENERATOR = pathlib.Path("scripts/build_learnings_index.py")
SECTION_RE = re.compile(r"^##\s")
ANY_HEAD_RE = re.compile(r"^###?\s")


def _blocks(lines):
    """[(start, end, heading)] for every `## ` section, end-exclusive."""
    heads = [i for i, l in enumerate(lines) if SECTION_RE.match(l)]
    out = []
    for n, i in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        out.append((i, end, lines[i]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--headings-file", required=True,
                    help="one EXACT heading line per line; blanks and # comments ignored")
    ap.add_argument("--entry-file", required=True,
                    help="markdown of the single consolidated entry to append")
    ap.add_argument("--archive", default=None,
                    help="default .syndicate/learnings_archive_<today>.md")
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = ap.parse_args(argv)

    # The generator fix is a PRECONDITION, not a nicety: without it this tool's
    # own output leaves the index, which is the exact defect the 2026-08-20
    # precedent shipped.
    try:
        gen = GENERATOR.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"REFUSED: cannot read {GENERATOR}: {exc}")
        return 2
    if "learnings_archive_*.md" not in gen:
        print("REFUSED: build_learnings_index.py does not span learnings_archive_*.md, "
              "so every rule this tool archives would leave the index. Fix the "
              "generator first. Nothing written.")
        return 2

    archive = pathlib.Path(args.archive or
                           f".syndicate/learnings_archive_{datetime.date.today()}.md")
    try:
        raw = LEARN.read_text(encoding="utf-8")
        entry = io.open(args.entry_file, encoding="utf-8").read().rstrip("\n")
        wanted = [l.rstrip("\n") for l in io.open(args.headings_file, encoding="utf-8")
                  if l.strip() and not l.startswith("#!")]
    except OSError as exc:
        print(f"REFUSED: cannot read: {exc}")
        return 2

    lines = raw.split("\n")
    blocks = _blocks(lines)
    by_head = collections.Counter(h for _, _, h in blocks)

    # Every requested heading must match EXACTLY ONE block. A heading that
    # matches none is a typo or a stale inventory; one that matches several
    # means `lanes.md`'s "one slug, one block" problem has reached this file,
    # and folding either copy would silently drop the other.
    bad = [h for h in wanted if by_head[h] != 1]
    if bad:
        print(f"REFUSED: {len(bad)} heading(s) do not match exactly one block. Nothing written.")
        for h in bad[:8]:
            print(f"  matches {by_head[h]}: {h[:88]}")
        return 2

    keep, folded = [], []
    prev = blocks[0][0] if blocks else len(lines)
    keep.extend(lines[:prev])
    for i, end, head in blocks:
        body = lines[i:end]
        if head in wanted:
            folded.append("\n".join(body).rstrip("\n"))
        else:
            keep.extend(body)

    header = (f"# Consolidated originals — {datetime.date.today()}\n\n"
              f"> Moved VERBATIM from `learnings.md`; nothing edited, summarised or\n"
              f"> reflowed. Folded into a single entry in `learnings.md`; these\n"
              f"> {len(folded)} originals are kept because a consolidated rule must never\n"
              f"> cost the evidence that earned it. Indexed via\n"
              f"> `build_learnings_index.py`, which spans `learnings_archive_*.md`.\n")
    archive_text = header + "\n" + "\n\n".join(folded) + "\n"
    new_learn = "\n".join(keep).rstrip("\n") + "\n\n" + entry + "\n"

    # --- verification, before any write. Subtraction, never equality. ---
    after = (new_learn + "\n" + archive_text).split("\n")
    h_before = collections.Counter(l for l in lines if ANY_HEAD_RE.match(l))
    h_after = collections.Counter(l for l in after if ANY_HEAD_RE.match(l))
    lost = list((h_before - h_after).elements())
    if lost:
        print(f"REFUSED: {len(lost)} heading(s) would be lost. Nothing written.")
        for l in lost[:8]:
            print(f"  lost: {l[:88]}")
        return 2

    c_before = collections.Counter(l for l in lines if l.strip())
    c_after = collections.Counter(l for l in after if l.strip())
    missing = list((c_before - c_after).elements())
    if missing:
        print(f"REFUSED: {len(missing)} line(s) would be lost. Nothing written.")
        for l in missing[:8]:
            print(f"  lost: {l[:88]}")
        return 2

    print(f"folding {len(folded)} entr(ies) into 1")
    print(f"  learnings.md : {len(lines)} -> {len(new_learn.split(chr(10)))} lines")
    print(f"  archive      : {archive} ({len(archive_text)} B, {len(folded)} originals)")
    print(f"  headings lost: 0    lines lost: 0")
    for h in wanted:
        print(f"  folded: {h[:88]}")
    if not args.apply:
        print("DRY RUN — nothing written. Re-run with --apply.")
        return 0

    # utf-8-sig would strip learnings.md's BOM on the way back out; the file has
    # one (ef bb bf) and losing it has bitten this repo before.
    archive.write_text(archive_text, encoding="utf-8", newline="")
    LEARN.write_text(new_learn, encoding="utf-8", newline="")
    print(f"WROTE {LEARN} and {archive}. Now run: py -3 {GENERATOR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Archive superseded prose out of `state.md`: the correction stays, the dead body moves.

WHY THIS IS NOT `compact_learnings.py`, AND WHY IT CANNOT BE. That tool works
because `learnings.md` is append-only DATED SECTIONS whose headings are
themselves the rule, so "everything before <date>" is a safe, mechanical
boundary. `state.md` has no such boundary and never will: it is 176 keyed
sections of CURRENT TRUTH, and its superseded material sits mid-section, inside
live prose, with nothing marking where it ends.

MEASURED 2026-09-03, over the whole file, and this is the finding that shapes
the tool:

  * 31 lines carry a superseded-ish marker.
  * Only 10 paragraph blocks START with one -- and moving those would be
    BACKWARDS. They read "**RETRACTED: the entry that stood here said the fee
    was ZERO.** That was...". The marker paragraph IS THE CORRECTION. Archiving
    it would file the correction away and leave the wrong claim standing.
  * Exactly ONE region in the file designates its own end ("**THIS ENTIRE
    FINDING IS WRONG AND IS RETRACTED.** The body is kept below only so the
    mistake is legible"), worth ~1,500 chars.

ALL 8 "NEEDS A HUMAN" CANDIDATES WERE THEN AUDITED BY HAND, 2026-09-03. NONE
IS ARCHIVABLE. Do not re-run that audit expecting a different answer; re-run it
only against markers ADDED since. Two distinct reasons, and both are structural:

  * SIX have no dead body at all. The superseded claim was DELETED when the
    correction was written, and survives only as a one-sentence quotation
    inside the correction itself -- "the entry that stood here said the fee was
    ZERO", "**RETRACTED: 'soccer box sections render 0 rows'**". The paragraph
    the audit flags IS the entire record. Moving it removes the correction and
    restores nothing. (`venue-fee-economics`, `football-smartsim2`,
    `kalshi-in-play-and-real-fees`, `soccer-live-tier`,
    `mlb-exchange-shopping-value`, `test-intelligence-runtime`.)
  * TWO keep a superseded block ON PURPOSE and say so in the correction:
    "the readings below are the 08-25 state, kept because the diagnosis chain
    in them is still the right one" (`ncaaf-readiness-2026`) and "the paragraph
    above is kept because its CAUTION was right and produced this measurement;
    only its arithmetic is superseded" (`week-scoped-board-window`). Both also
    carry content added AFTER their correction -- ncaaf runs to 2026-08-30, and
    week-scoped holds a "STILL LIVE 2026-09-03" risk plus forward dates through
    09-06 -- so the block is not even uniformly old.

THE CONCLUSION THAT MATTERS FOR ANYONE TRYING TO SHRINK THIS FILE: state.md is
not carrying superseded bloat. Of ~746,500 chars, the marked-superseded
material that could be moved came to 1,460 -- 0.2%, and it has now been moved.
The rest is live current truth. Size here is not a defect to be compacted away,
which is why the cap was raised rather than the file cut.

So a fully automatic compactor for this file would be a lie, and the honest
tool is two things instead:

  AUDIT (default)    rank what a human should look at, with byte counts, so the
                     work is a worklist rather than an archaeology dig.
  ESCORT (--section) the human says WHAT to move; this guarantees NOTHING IS
                     LOST while moving it.

The escort half is the real value. The 2026-09-03 archival pass that reclaimed
3,086 B was done BY HAND with ad-hoc checks; this makes that repeatable, and
refuses rather than half-writes.

VERIFICATION BEFORE ANY WRITE -- four checks, each with a test that makes it
FIRE. A verifier is exactly the kind of code that ships inert:
  1. every `## ` heading present before is present after, across BOTH files
  2. every non-blank line conserved across state.md + the archive
  3. `state_key_check.py`'s invariant re-run on the CANDIDATE text -- one
     subject, one section -- so a move can never leave the file stacked
  4. state.md re-read immediately before the write; a concurrent change is a
     refusal, not a silent overwrite

There is deliberately NO token-level check. One was written -- the 2026-09-03
rule says a line diff is the wrong instrument for a REWORDED ledger -- and it
was removed when its reachability test could not make it fail. This tool never
rewords; it moves lines verbatim, so check 2 is exact and a token check over
the same text is tautological. See the comment in `verify()`.

NOTE ON THE SLUG PATTERN. This uses a PERMISSIVE slug pattern, matching
`ledger_invariants.py` (the hook that actually blocks a commit) rather than the
narrower one `state_key_check.py` used to carry. That narrow pattern
(`[a-z0-9][a-z0-9-]*`) matched neither 9 real sections with an uppercase or
underscore slug NOR the unkeyed pattern, so the reporter counted 167 sections
in a 176-section file. FIXED 2026-09-03 in the same pass that added this tool;
the reporter is now permissive too and flags off-convention slugs without
failing on them. Three implementations of one invariant that disagree is how
the invariant stops meaning anything.

LINE ENDINGS. state.md is CRLF. This reads and writes BYTES and restores the
ending it found: editing it with text-mode I/O rewrites all 11,000 line endings
invisibly, which `git diff` cannot show you (learnings.md, 2026-09-03).

    py -3 scripts/compact_state.py                          # audit
    py -3 scripts/compact_state.py --auto                   # safe subset, dry
    py -3 scripts/compact_state.py --auto --apply
    py -3 scripts/compact_state.py --section <slug> --after "<substring>"

Exit 0 = clean (or nothing to do), 1 = refused, 2 = cannot read/verify.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import pathlib
import re
import sys

STATE = pathlib.Path(".syndicate/state.md")
# SPLIT 2026-09-03: the bodies this tool operates on moved into
# `.syndicate/state_<domain>.md`. state.md keeps the index and the
# cross-cutting subjects, so pointing this at the default now finds almost
# nothing -- pass --file to work on a part. Kept as the default anyway
# because the cross-cutting sections are still real sections.

HEAD = re.compile(r"^## ")
# PERMISSIVE on purpose -- see the note in the module docstring.
SLUG = re.compile(r"^## \[([^\]]+)\]")
STRICT_SLUG = re.compile(r"^## \[([a-z0-9][a-z0-9-]*)\] ")
MARKER = re.compile(
    r"\*\*[^*]{0,90}?(SUPERSEDED|RETRACTED|OVERTURNED|MUST NOT BE QUOTED"
    r"|DO NOT QUOTE|KEPT FOR THE RECORD)"
)
# A marker that hands you its own end boundary: it says the rest is the corpse.
DESIGNATES = re.compile(
    r"(?i)kept (?:below|here) only|body is kept below|SUPERSEDED READING FOLLOWS"
    r"|is kept below|below is (?:kept|superseded)|remains below|left below"
)
# The pointer this tool writes, and therefore the one it must never re-move.
# compact_learnings.py learned this the expensive way: without an idempotence
# marker a re-run "compacts" everything again, reclaiming 0 B while appending a
# duplicate copy of every entry to the archive.
POINTER = "*(superseded body archived in"


def load():
    """Return (lines, crlf, normalised_text)."""
    data = STATE.read_bytes()
    crlf = b"\r\n" in data
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    return text.split("\n"), crlf, text


def sections(lines):
    """[(slug_or_None, header_line, start, end)] over ALL `## ` headers."""
    idx = [i for i, l in enumerate(lines) if HEAD.match(l)]
    out = []
    for n, i in enumerate(idx):
        end = idx[n + 1] if n + 1 < len(idx) else len(lines)
        m = SLUG.match(lines[i])
        out.append((m.group(1) if m else None, lines[i], i, end))
    return out


def blocks(lines, lo, hi):
    """Blank-line-delimited paragraph blocks within [lo, hi)."""
    out, cur, start = [], [], lo
    for i in range(lo, hi):
        if not lines[i].strip():
            if cur:
                out.append((start, i, cur))
                cur = []
        else:
            if not cur:
                start = i
            cur.append(lines[i])
    if cur:
        out.append((start, hi, cur))
    return out


def coherence(lines):
    """state_key_check.py's invariant, re-run on candidate text.

    Returns (stacked, unkeyed, invisible_to_the_strict_pattern)."""
    keyed = collections.defaultdict(list)
    unkeyed, invisible = [], []
    for slug, title, i, e in sections(lines):
        if slug is None:
            unkeyed.append(title[:70])
            continue
        keyed[slug].append(title[:70])
        if not STRICT_SLUG.match(title):
            invisible.append(slug)
    stacked = {s: t for s, t in keyed.items() if len(t) > 1}
    return stacked, unkeyed, invisible


def candidates(lines):
    """(auto, manual) archival candidates, each (chars, slug, line_no, head)."""
    auto, manual = [], []
    for slug, title, i, e in sections(lines):
        if slug is None:
            continue
        if any(POINTER in l for l in lines[i:e]):
            continue
        for s, be, body in blocks(lines, i + 1, e):
            head = body[0]
            if not MARKER.search(head):
                continue
            if DESIGNATES.search(head):
                tail = "\n".join(lines[be:e]).strip()
                if tail:
                    auto.append((len(tail), slug, s + 1, head.strip(), be, e))
            else:
                manual.append((len("\n".join(body)), slug, s + 1, head.strip(), be, e))
    return auto, manual


def audit(lines):
    secs = sections(lines)
    total = len("\n".join(lines))
    print(f"{STATE.name}: {len(lines)} lines, {total} chars, {len(secs)} sections\n")

    auto, manual = candidates(lines)

    print(f"=== AUTO-SAFE ({len(auto)}) -- the marker designates its own remainder ===")
    if not auto:
        print("  none")
    for n, slug, ln, head, be, e in sorted(auto, reverse=True):
        print(f"  {n:>6}ch  [{slug}] L{ln}")
        print(f"          {head[:96]}")
    print(f"  mechanically reclaimable: {sum(a[0] for a in auto)} chars\n")

    print(f"=== NEEDS A HUMAN ({len(manual)}) -- the marker is the CORRECTION, not the corpse ===")
    print("  Moving these would archive the correction and leave the wrong claim.")
    print("  Read each, decide where the dead region ends, then use --section/--after.")
    for n, slug, ln, head, be, e in sorted(manual, reverse=True)[:12]:
        print(f"  {n:>6}ch  [{slug}] L{ln}  {head[:74]}")
    print()

    big = sorted(
        ((len("\n".join(lines[i:e])), s or t[:40]) for s, t, i, e in secs), reverse=True
    )
    print("=== 8 LARGEST SECTIONS (size is not a defect; this is where to look) ===")
    for n, slug in big[:8]:
        print(f"  {n:>6}ch  {slug}")

    stacked, unkeyed, invisible = coherence(lines)
    if invisible:
        print(f"\n=== {len(invisible)} OFF-CONVENTION SLUG(S) (uppercase or '_') ===")
        print("  Checked for stacking here and by state_key_check.py and the commit")
        print("  guard. Normalise to lower-kebab when you next edit the section.")
        for s in sorted(invisible):
            print(f"  [{s}]")
    if stacked:
        print(f"\nSTACKED: {len(stacked)} subject(s) with >1 section -- fix before moving anything.")
    return 0


def verify(before_lines, after_lines, moved, archive_text):
    """All the checks. Returns a list of refusal reasons; empty means go."""
    bad = []
    combined = after_lines + archive_text.split("\n") + moved.split("\n")

    h_before = collections.Counter(l for l in before_lines if HEAD.match(l))
    h_after = collections.Counter(l for l in combined if HEAD.match(l))
    lost = list((h_before - h_after).elements())
    if lost:
        bad.append(f"{len(lost)} heading(s) would be lost: "
                   + "; ".join(x[:60] for x in lost[:3]))

    c_before = collections.Counter(l for l in before_lines if l.strip())
    c_after = collections.Counter(l for l in combined if l.strip())
    gone = list((c_before - c_after).elements())
    if gone:
        bad.append(f"{len(gone)} line(s) would be lost: "
                   + "; ".join(x.strip()[:60] for x in gone[:3]))

    # NO TOKEN-LEVEL CHECK HERE, AND THAT IS DELIBERATE -- it was written, and
    # removed when its own reachability test could not make it fail.
    #
    # The 2026-09-03 rule ("a line-level diff is the wrong instrument for a
    # reworded ledger") is about judging loss when text has been REWORDED. This
    # tool never rewords: it moves lines verbatim, so line-conservation above is
    # EXACT, and a token check over the same verbatim text is tautological --
    # it searched for `moved`'s tokens in a haystack containing `moved` and so
    # could only ever pass. Four checks that can fail beat five where one is
    # decoration; an unfalsifiable guarantee is worse than an absent one because
    # it reads as coverage.
    #
    # If this tool is ever taught to SUMMARISE rather than move, the token check
    # becomes load-bearing and must come back -- with a test that fails without it.
    stacked, unkeyed, _ = coherence(after_lines)
    if stacked:
        bad.append(f"would leave {len(stacked)} stacked subject(s): {sorted(stacked)[:3]}")
    if unkeyed:
        bad.append(f"would leave {len(unkeyed)} unkeyed section(s)")
    return bad


def do_move(lines, crlf, raw, regions, apply_, label):
    """regions: [(slug, lo, hi)] -- move lines[lo:hi] out, leave a pointer."""
    if not regions:
        print(f"{label}: nothing to move.")
        return 0

    stamp = datetime.date.today().isoformat()
    arch_path = pathlib.Path(f".syndicate/state_archive_{stamp}.md")
    archive_text = (arch_path.read_text(encoding="utf-8", errors="replace")
                    if arch_path.exists() else "")

    out, moved_parts = list(lines), []
    # Apply bottom-up so earlier indices stay valid.
    for slug, lo, hi in sorted(regions, key=lambda r: -r[1]):
        body = "\n".join(lines[lo:hi]).strip("\n")
        if not body.strip():
            continue
        moved_parts.append(f"## [{slug}] superseded body, moved {stamp}\n\n{body}")
        out[lo:hi] = ["", f"{POINTER} `{arch_path.name}`)*", ""]
    moved = "\n\n".join(moved_parts)

    bad = verify(lines, out, moved, archive_text)
    reclaimed = len("\n".join(lines)) - len("\n".join(out))
    print(f"{label}: {len(regions)} region(s), {reclaimed} chars reclaimed from state.md")
    for slug, lo, hi in regions:
        print(f"  [{slug}] L{lo + 1}..L{hi}  ({len(chr(10).join(lines[lo:hi]))} ch)")

    if bad:
        print("\nREFUSED. Nothing written:")
        for b in bad:
            print(f"  * {b}")
        return 1

    print("verification: headings conserved, every non-blank line conserved "
          "across both files, coherence holds (one subject, one section)")

    if not apply_:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    current = STATE.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    if current != raw:
        print("REFUSED: state.md changed while this ran. Nothing written; re-run.")
        return 1

    banner = (f"\n\n# SUPERSEDED BODIES MOVED OUT OF `state.md` — {stamp}\n\n"
              f"Moved verbatim by `scripts/compact_state.py`. Nothing summarised or\n"
              f"deleted. The CORRECTION that supersedes each body stays in `state.md`\n"
              f"with a pointer to here.\n\n")
    arch_path.write_text(archive_text + banner + moved + "\n", encoding="utf-8")
    text = "\n".join(out)
    STATE.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print(f"\nWROTE state.md and {arch_path.name}.")
    print("NEXT: py -3 scripts/state_key_check.py")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--auto", action="store_true",
                    help="move only self-delimiting superseded regions")
    ap.add_argument("--section", help="slug to operate on (with --after)")
    ap.add_argument("--after",
                    help="substring of the marker line; moves from after its "
                         "paragraph to the end of that section")
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    ap.add_argument("--file", help="state file to operate on "
                                   "(default .syndicate/state.md; use a state_<domain>.md part)")
    args = ap.parse_args(argv)
    if args.file:
        globals()["STATE"] = pathlib.Path(args.file)

    try:
        lines, crlf, raw = load()
    except OSError as exc:
        print(f"cannot read {STATE}: {exc}")
        return 2

    if args.section or args.after:
        if not (args.section and args.after):
            print("--section and --after must be given together.")
            return 2
        hit = [s for s in sections(lines) if s[0] == args.section]
        if len(hit) != 1:
            print(f"REFUSED: {len(hit)} section(s) match slug {args.section!r}; need exactly 1.")
            return 1
        slug, title, i, e = hit[0]
        marks = [n for n in range(i, e) if args.after in lines[n]]
        if len(marks) != 1:
            print(f"REFUSED: {len(marks)} line(s) in [{slug}] contain {args.after!r}; "
                  f"need exactly 1.")
            return 1
        mi = marks[0]
        owning = [b for b in blocks(lines, i + 1, e) if b[0] <= mi < b[1]]
        lo = owning[0][1] if owning else mi + 1
        if not "\n".join(lines[lo:e]).strip():
            print(f"REFUSED: nothing follows the marker in [{slug}]; nothing to move.")
            return 1
        return do_move(lines, crlf, raw, [(slug, lo, e)], args.apply, "escort move")

    if args.auto:
        auto, _ = candidates(lines)
        regions = [(slug, be, e) for _n, slug, _ln, _h, be, e in auto]
        return do_move(lines, crlf, raw, regions, args.apply, "auto move")

    return audit(lines)


if __name__ == "__main__":
    sys.exit(main())

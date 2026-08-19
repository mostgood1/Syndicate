"""Compact dated `learnings.md` entries: rule stays, evidence moves.

WHY THIS IS SAFE HERE AND WOULD NOT BE ON A PROSE FILE. `learnings.md` is
append-only dated entries whose HEADINGS ARE THEMSELVES THE RULE -- "FORBIDDEN:
never conclude 'no OOM' from a LOG search", "EXONERATED: the soccer window is
not the egress cause". A compacted entry therefore still states its rule even
before you read the stub line, and the full working is one file away rather than
gone. This is the file's own established pattern, not a new one: see the
`## Compacted entries (rule kept here, evidence in learnings_evidence.md)`
section and its note -- "entries before 2026-08-15 keep their heading and their
rule. Nothing was deleted."

Three things keep a compacted rule findable:
  - the HEADING, retained verbatim in `learnings.md`
  - the RULE LINE, extracted and retained (see `_rule_line` for the order tried)
  - `learnings_index.md`, which `build_learnings_index.py` generates across BOTH
    `learnings.md` and `learnings_evidence.md`, so a rule stays indexed after its
    body is compacted out. REGENERATE IT AFTER RUNNING THIS.

WHAT IT WILL NOT TOUCH: the `## Index` and `## Compacted entries` sections, the
preamble, and anything on or after `--keep-from`. Undated `##` sections are left
alone entirely -- they are structure, not entries.

VERIFICATION BEFORE WRITING, the same three as the lane tools:
  - every heading present before is still present after, in one file or the other
  - every non-blank line conserved across learnings.md + learnings_evidence.md
  - learnings.md re-read immediately before the write; a concurrent change is a
    refusal, not a silent overwrite

    py -3 scripts/compact_learnings.py --keep-from 2026-08-18
    py -3 scripts/compact_learnings.py --keep-from 2026-08-18 --apply

Exit 0 = clean (or nothing to do), 1 = refused, 2 = could not read/verify.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import pathlib
import re
import sys

LEARN = pathlib.Path(".syndicate/learnings.md")
EVID = pathlib.Path(".syndicate/learnings_evidence.md")

SECTION_RE = re.compile(r"^##\s")
DATED_RE = re.compile(r"^##\s+(2026-\d\d-\d\d)")
SKIP_HEADS = ("## Index", "## Compacted entries")


def _rule_line(body):
    """The operative sentence, by preference order. None if nothing qualifies.

    Order matters: an explicit "rule going forward" is the author's own summary
    and always wins. A bold bullet is the next most likely to be the rule. A
    bare first bullet is the weakest and is only used because a stub with no
    rule line still beats a stub with the wrong one -- the heading carries the
    rule regardless, so this is belt-and-braces, not the only copy.
    """
    for l in body:
        if "rule going forward" in l.lower():
            return l.strip()
    for l in body:
        s = l.strip()
        if s.startswith(("- **", "**")) and len(s) > 12:
            return s
    for l in body:
        s = l.strip()
        if s.startswith("- ") and len(s) > 12:
            return s
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep-from", required=True, help="YYYY-MM-DD; entries on/after this stay in full")
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    ap.add_argument("--cap", type=int, default=120000)
    args = ap.parse_args(argv)

    try:
        text = LEARN.read_text(encoding="utf-8", errors="replace")
        evid = EVID.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read: {exc}")
        return 2

    lines = text.split("\n")
    heads = [(i, l) for i, l in enumerate(lines) if SECTION_RE.match(l)]
    out, moved, n_comp, no_rule = [], [], 0, []
    prev_end = heads[0][0] if heads else len(lines)
    out.extend(lines[:prev_end])

    for n, (i, head) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = lines[i:end]
        m = DATED_RE.match(head)
        if (not m) or m.group(1) >= args.keep_from or head.startswith(SKIP_HEADS):
            out.extend(body)
            continue
        rule = _rule_line(body[1:])
        if rule is None:
            no_rule.append(head[:70])
        n_comp += 1
        moved.append("\n".join(body).rstrip("\n"))
        out.append(head)
        out.append("")
        if rule:
            out.append(rule if rule.startswith("-") else f"- {rule}")
        out.append("- *(evidence in `learnings_evidence.md`)*")
        out.append("")

    new_text = "\n".join(out)
    moved_text = "\n\n".join(moved)

    # --- verification, before any write ---
    h_before = collections.Counter(l for l in lines if SECTION_RE.match(l) or l.startswith("### "))
    h_after = collections.Counter(l for l in (new_text + "\n" + moved_text).split("\n")
                                  if SECTION_RE.match(l) or l.startswith("### "))
    # SUBTRACTION, NOT EQUALITY. A compacted heading appears TWICE afterwards --
    # once as the stub in learnings.md and once above its evidence -- so the
    # counters are deliberately unequal and `h_before != h_after` refused a
    # correct transformation while printing "0 heading(s) would be lost", which
    # is a self-contradicting error message. The property that matters is that
    # nothing DISAPPEARS; duplication is the intended outcome.
    lost_heads = list((h_before - h_after).elements())
    if lost_heads:
        print(f"REFUSED: {len(lost_heads)} heading(s) would be lost. Nothing written.")
        for l in lost_heads[:6]:
            print(f"  lost: {l[:88]}")
        return 2

    c_before = collections.Counter(l for l in lines if l.strip())
    c_after = collections.Counter(l for l in (new_text + "\n" + moved_text).split("\n") if l.strip())
    missing = list((c_before - c_after).elements())
    if missing:
        print(f"REFUSED: {len(missing)} line(s) would be lost. Nothing written.")
        for l in missing[:5]:
            print(f"  lost: {l[:88]}")
        return 2

    print(f"compacted sections : {n_comp}  (entries before {args.keep_from})")
    print(f"learnings.md       : {len(text)} -> {len(new_text)} B  ({len(text)-len(new_text)} reclaimed)")
    print(f"cap {args.cap}       : {len(text)/args.cap:.2f}x -> {len(new_text)/args.cap:.2f}x  "
          f"{'UNDER' if len(new_text) < args.cap else '*** STILL OVER ***'}")
    print(f"evidence file      : {len(evid)} -> {len(evid)+len(moved_text)} B")
    if no_rule:
        print(f"\n{len(no_rule)} compacted with NO extractable rule line (heading still carries the rule):")
        for h in no_rule[:8]:
            print(f"   {h}")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    current = LEARN.read_text(encoding="utf-8", errors="replace")
    if current != text:
        print(f"REFUSED: learnings.md changed while this ran ({len(text)} -> {len(current)} B). "
              "Nothing written; re-run.")
        return 1

    stamp = datetime.date.today().isoformat()
    banner = (f"\n\n## EVIDENCE COMPACTED OUT OF `learnings.md` — {stamp}\n\n"
              f"Moved verbatim by `scripts/compact_learnings.py --keep-from {args.keep_from}`.\n"
              f"Nothing summarised or deleted. Each entry keeps its heading AND its rule in\n"
              f"`learnings.md`; this is the full working. `learnings_index.md` spans both\n"
              f"files — regenerate with `py -3 scripts/build_learnings_index.py`.\n\n")
    EVID.write_text(evid + banner + moved_text + "\n", encoding="utf-8")
    LEARN.write_text(new_text, encoding="utf-8")
    print("\nWROTE learnings.md and learnings_evidence.md.")
    print("NEXT: py -3 scripts/build_learnings_index.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

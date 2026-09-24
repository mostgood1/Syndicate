#!/usr/bin/env python3
"""Move a lane block's HISTORY out of `lanes.md` into `lanes_history.md`, verbatim.

WHY THIS EXISTS, and why it is not `trim_lane_blocks.py`. That tool collapses a
lane that has MANY blocks down to its recent ones. Measured 2026-09-24: this
repo's 57 lanes held 57 blocks, one each, so it had nothing to collapse -- while
`lanes.md` sat at 485 KB against a 240,000 B cap with **74% of the file in OPEN
lane bodies**. The bloat is one long block per lane, not many blocks per lane,
and closed-lane archiving could only ever recover 9% of the overage.

WHAT IT KEEPS, as a stated policy rather than a per-block judgement:

  - the header (the lane stays OPEN; this tool never changes lane status)
  - contract keys -- Goal / Why / Files / Hypothesis / Falsification test /
    Verification / Blocked by / GOAL VERDICT -- **and their whole subtrees**
  - the newest dated top-level entry
  - every line still marking work OUTSTANDING: OWED / LEFT: / STILL / NOT MET /
    TODO, plus ancestors
  - every CLAIM-BEARING line, plus ancestors

THREE THINGS LEARNED THE HARD WAY, each of which this encodes:

1. **Claim-bearing lines are MEASURED, never grepped.** For each line: remove it
   and re-run `lane_claims._claims`. On `book-quotes-splice-repair` a choice by
   contiguous range silently dropped **5 of 9 claims**, because a `**Files:**`
   bullet inside a P3 pre-registration and a `Tests:` bullet inside P5 declare
   paths too. One claim-bearing line there (`**Files, scope widened**`) declares
   no path at all -- its removal merely breaks the parse of its children. A grep
   for `Files:` gets the set wrong in BOTH directions. Across five blocks the
   claim-bearing count ran 1, 5, 1, 1, 0, with no relation to block size.

2. **A contract key keeps its SUBTREE.** `polymarket-rejected-resubmit-loop`
   writes `- Hypothesis (to test, not believed), ranked:` and
   `- Falsification test:` as parents whose content is indented children. Keeping
   the parent alone leaves a contract that promises a list and delivers nothing --
   and every automated check passes: no claim moves, nothing is orphaned by
   indentation, the claim set matches. **The damage is to MEANING, which no check
   here measures.** That is why `--apply` is opt-in and the dry run prints every
   kept line with the reason it was kept: a human reading the keep set is the only
   instrument that catches it.

3. **`- Files:` must never leave `lanes.md`.** `lanes_history.md`'s own header
   says a lane declares its exclusive files in its block and archiving that leaves
   `lane-guard` unable to see the claim at all.

REFUSES to write unless, computed BEFORE touching either file: every moved
non-blank line is present verbatim in the new `lanes_history.md` AND absent from
the trimmed BLOCK (scoped to the block, not the file -- boilerplate like
`  - **Tests:**` legitimately recurs in other lanes); every kept line survives;
the claim set is identical AS A SET; the OPEN header count is unchanged; and no
kept indented line is left without a kept ancestor.

    py -3 scripts/trim_lane_narrative.py <slug> [<slug> ...]            # dry run
    py -3 scripts/trim_lane_narrative.py <slug> --apply

Exit 3 on refusal, 2 on a bad slug, 0 otherwise.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANES = os.path.join(REPO, ".syndicate", "lanes.md")
HIST = os.path.join(REPO, ".syndicate", "lanes_history.md")
GUARD = os.path.join(REPO, ".claude", "hooks", "lane_claims.py")

LF = "\n"
EM = "—"

CONTRACT = re.compile(r"^\s*-\s*(Goal|Why|Files|Hypothesis|Falsification test|"
                      r"Verification|Blocked by|GOAL VERDICT)\b", re.I)
OUTSTANDING = re.compile(r"\bOWED\b|\bLEFT:|\bSTILL\b|NOT MET|\bTODO\b")
DATE = re.compile(r"20\d\d-\d\d-\d\d")
OPEN_RE = re.compile(r"^### \S+ — OPEN\b")
BLOCK_END = re.compile(r"^#{2,3}\s")
# a pointer left by any previous run of this tool, in either wording
POINTER_RE = re.compile(r"\*\*TRIMMED \d{4}-\d{2}-\d{2}")


def claims_fn(guard_path=GUARD):
    """`lane_claims._claims`, loaded from the guard that ENFORCES claims.

    Never a local reimplementation: a second parser that disagrees with the guard
    is worse than none (`pending_deploys.py`, quoted in `lane_claim_audit.py`).
    """
    mod = types.ModuleType("lane_claims_ro")
    with open(guard_path, encoding="utf-8") as fh:
        exec(compile(fh.read(), guard_path, "exec"), mod.__dict__)
    return mod._claims


def indent(line):
    return len(line) - len(line.lstrip(" "))


def locate(lines, slug):
    """(start, end) of a lane's block, or None."""
    pat = re.compile(r"^### %s " % re.escape(slug))
    start = next((i for i, l in enumerate(lines) if pat.match(l)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if BLOCK_END.match(lines[i])),
               len(lines))
    return start, end


def plan(block, claims):
    """(all_claims, claim_line_indices, sorted_keep_indices) for one block."""
    full = set(claims(LF.join(block)))
    claim_lines = {i for i in range(1, len(block))
                   if block[i].strip()
                   and set(claims(LF.join(block[:i] + block[i + 1:]))) != full}
    keep = {0} | claim_lines
    keep |= {i for i, l in enumerate(block) if CONTRACT.match(l)}
    keep |= {i for i, l in enumerate(block) if OUTSTANDING.search(l)}

    # A previous run's pointer is METADATA: always kept, and excluded from the
    # newest-dated-entry contest. Without this the tool is NOT IDEMPOTENT -- the
    # pointer carries the trim date, so it wins "newest" and displaces the real
    # newest entry, which a SECOND run then moves out. Measured on
    # `polymarket-ask-pricing` after its first trim: a re-run wanted to move
    # `CLAIM TAKEN 2026-09-23`, the genuine newest line. A trimmer that eats more
    # on every run is worse than none.
    pointers = {i for i, l in enumerate(block) if POINTER_RE.search(l)}
    keep |= pointers
    dated = [(max(DATE.findall(l)), i) for i, l in enumerate(block)
             if i and i not in pointers and indent(l) == 0 and DATE.search(l)]
    if dated:
        keep.add(max(dated)[1])

    # a kept line that promises a list keeps its whole subtree -- see point 2
    for i in sorted(keep):
        if not (CONTRACT.match(block[i]) or block[i].rstrip().endswith(":")):
            continue
        lvl = indent(block[i])
        j = i + 1
        while j < len(block) and (not block[j].strip() or indent(block[j]) > lvl):
            if block[j].strip():
                keep.add(j)
            j += 1

    for i in sorted(keep):
        lvl = indent(block[i])
        j = i - 1
        while j > 0 and lvl > 0:
            if block[j].strip() and indent(block[j]) < lvl:
                keep.add(j)
                lvl = indent(block[j])
            j -= 1
    return full, claim_lines, sorted(keep)


def reason(block, i, claim_lines):
    if i == 0:
        return "header"
    if i in claim_lines:
        return "CLAIM"
    if CONTRACT.match(block[i]):
        return "contract"
    if OUTSTANDING.search(block[i]):
        return "outstanding"
    return "subtree/ancestor/newest"


def pointer_line(slug, n_moved, b_moved, b_block, note=""):
    return ("- **TRIMMED %s by `scripts/trim_lane_narrative.py`. %d lines / %d B of HISTORY "
            "moved VERBATIM to `lanes_history.md` under `## TRIMMED FROM lanes.md %s %s (%s)`; "
            "nothing summarised, nothing deleted, fully reversible. KEPT: the header, the "
            "contract keys and their subtrees, the newest dated entry, every line still marking "
            "work OUTSTANDING, and every CLAIM-BEARING line %s which lines those are was MEASURED "
            "by removal, not grepped. Block was %d B.%s"
            % (TODAY, n_moved, b_moved, EM, TODAY, slug, EM, b_block,
               (" " + note) if note else ""))


TODAY = os.environ.get("TRIM_DATE") or __import__("datetime").date.today().isoformat()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--apply", action="store_true",
                    help="write; without it this is a dry run that prints the keep set")
    ap.add_argument("--note", default="", help="appended to the pointer line")
    ap.add_argument("--retrim", action="store_true",
                    help="trim a block that already carries a pointer, overriding the "
                         "previous trim's judgement; read the dry-run keep set first")
    args = ap.parse_args(argv)

    claims = claims_fn()
    with open(LANES, encoding="utf-8") as fh:
        text = fh.read()
    with open(HIST, encoding="utf-8") as fh:
        hist = orig_hist = fh.read()
    lines = text.split(LF)
    saved = 0

    for slug in args.slugs:
        found = locate(lines, slug)
        if found is None:
            sys.stderr.write("trim_lane_narrative: no block for %r\n" % slug)
            return 2
        s, e = found
        block = lines[s:e]
        full, claim_lines, kept = plan(block, claims)
        moved = [i for i in range(len(block)) if i not in set(kept)]
        bb = sum(len(l.encode("utf-8")) + 1 for l in block)
        mb = sum(len(block[i].encode("utf-8")) + 1 for i in moved)
        print("=== %s ===" % slug)
        print("  %d lines / %d B -> keep %d / %d B, move %d / %d B  (%d claims, %d claim lines)"
              % (len(block), bb, len(kept),
                 sum(len(block[i].encode("utf-8")) + 1 for i in kept),
                 len(moved), mb, len(full), len(claim_lines)))
        if not [i for i in moved if block[i].strip()]:  # blanks do not count
            print("  nothing to move -- already trimmed. Skipping.")
            continue
        if any(POINTER_RE.search(l) for l in block) and not args.retrim:
            # A PREVIOUS TRIM'S JUDGEMENT IS BINDING. This policy is strictly more
            # aggressive than a careful hand trim: measured on the five blocks
            # trimmed 2026-09-24, it would move a further 3,839 B from
            # `bandwidth-controlled-transfer` -- 5 of the 6 current-arm lines that
            # trim kept ON PURPOSE, because live operational state on someone
            # else's lane is not a tool's to compress -- and 1,150 B more from
            # `book-quotes-splice-repair`. So a block that already carries a
            # pointer is left alone rather than second-guessed, which also makes
            # this tool idempotent by construction. `--retrim` overrides, and the
            # keep set should be read in a dry run first.
            print("  already carries a TRIMMED pointer; a previous trim's judgement stands.")
            print("  %d lines / %d B WOULD move under this policy -- pass --retrim to override,"
                  % (len([i for i in moved if block[i].strip()]), mb))
            print("  and read the dry-run keep set before you do.")
            continue
        if not args.apply:
            for i in kept:
                print("    %3d i%-2d %-24s %s"
                      % (i, indent(block[i]), reason(block, i, claim_lines), block[i][:84]))
            saved += mb
            print()
            continue

        head = "## TRIMMED FROM `lanes.md` %s %s (%s)" % (EM, TODAY, slug)
        if head in hist:
            sys.stderr.write("trim_lane_narrative: %s already has a %s section\n" % (slug, TODAY))
            return 3
        new_block = ([block[0], pointer_line(slug, len(moved), mb, bb, args.note), ""]
                     + [block[i] for i in kept if i])
        hist = (hist if hist.endswith(LF) else hist + LF) + (
            LF + head + LF + LF
            + "Moved verbatim by `scripts/trim_lane_narrative.py`; nothing summarised. The lane"
            + LF + "stays OPEN in `lanes.md` with its contract, its newest entry, everything still"
            + LF + "OUTSTANDING and every claim-bearing line. These are the %d historical lines."
            % len(moved) + LF + LF + LF.join(block[i] for i in moved) + LF)

        nb = LF.join(new_block)
        bad = []
        for i in moved:
            l = block[i]
            if l.strip() and l not in hist:
                bad.append("moved line absent from history: %r" % l[:55])
            if l.strip() and l in nb:
                bad.append("moved line still in the block: %r" % l[:55])
        for i in kept:
            if block[i].strip() and block[i] not in nb:
                bad.append("kept line lost: %r" % block[i][:55])
        bad += ["orphaned indented line %d" % i for pos, i in enumerate(kept)
                if i and block[i].strip() and indent(block[i])
                and not any(block[j].strip() and indent(block[j]) < indent(block[i])
                            for j in kept[:pos])]
        if not OPEN_RE.match(new_block[0]):
            bad.append("header no longer reads OPEN")
        if bad:
            for b in bad[:6]:
                sys.stderr.write("  REFUSE %s\n" % b)
            return 3
        lines = lines[:s] + new_block + lines[e:]
        saved += mb
        print("  ok")

    new_text = LF.join(lines)
    c_old, c_new = set(claims(text)), set(claims(new_text))
    o_old = sum(1 for l in text.split(LF) if OPEN_RE.match(l))
    o_new = sum(1 for l in lines if OPEN_RE.match(l))
    print("claims %d -> %d %s | OPEN %d -> %d | lanes.md %d -> %d B"
          % (len(c_old), len(c_new), "identical" if c_old == c_new else "CHANGED",
             o_old, o_new, len(text.encode("utf-8")), len(new_text.encode("utf-8"))))
    if not args.apply:
        print("DRY RUN. %d B would move. Re-run with --apply." % saved)
        return 0
    if c_old != c_new:
        sys.stderr.write("  REFUSE claim set changed: %s\n" % (c_old ^ c_new))
        return 3
    if o_old != o_new:
        sys.stderr.write("  REFUSE OPEN header count moved\n")
        return 3
    with open(LANES, "w", encoding="utf-8", newline=LF) as fh:
        fh.write(new_text)
    if hist != orig_hist:
        with open(HIST, "w", encoding="utf-8", newline=LF) as fh:
            fh.write(hist)
    print("wrote lanes.md and lanes_history.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Archive the superseded `###` history of ONE state subject, and refuse if the cut dangles.

WHY A TOOL. This was done by hand for `[web-oom-leak]` on 2026-10-04 (46 blocks,
79,826 chars to `state_archive_2026-10-04.md`). The hand method worked, but the
cross-reference check only looked for `UPDATE <n>` and therefore could not see a
POSITIONAL reference -- and one existed: the kept block said *"THIS DOES NOT
DISPLACE THE `/api/intelligence/query` SUSPECT ABOVE"*, whose suspect had just been
archived. It was caught by re-reading the kept text afterwards, which is luck, not
method. Doing the remaining subjects by hand is the same coin flip ~20 more times.

WHAT IT REFUSES ON, computed BEFORE either file is written:

  1. A KEPT block naming an ARCHIVED block's `UPDATE <n>`.
  2. A KEPT block using a POSITIONAL reference (`above`, `earlier`, `previously`,
     `the previous update`, `further up`) anywhere in its body. These cannot be
     resolved mechanically, so the tool does not try: it refuses and prints the
     line, and a human decides whether that phrase points across the boundary.
     `--allow-positional` overrides ONE AT A TIME by line substring, so an
     override is a statement about a specific sentence, never a blanket one.
  3. Any non-blank line that would end up in neither file.
  4. A subject that would lose its `## [slug]` keyed heading, or whose part file
     has no such heading to begin with.

SELECTION IS EXPLICIT, AND THAT IS NOT PEDANTRY -- A "NEWEST N" RULE IS UNSAFE HERE.
The first version of this tool kept "the newest `--keep` sub-blocks by file
position". Measured on `[mlb-ladders-native-builder]` 2026-10-05, that would have
ARCHIVED THE VERIFIED CURRENT BLOCK AND KEPT THE PRE-REGISTRATION: that subject is
ordered NEWEST-FIRST (pos 0 is `[2026-08-20 VERIFIED -- SUPERSEDES ...]`, pos 7-8
are undated "named before writing it" notes). `[web-oom-leak]`'s newest block sat
SECOND in its file. Position and recency disagree per subject, and dates are often
absent, so NEITHER can be a default.

Blocks also carry their own instructions, which no ordering rule can see:
`- WHY -- the original diagnosis, KEPT BECAUSE IT IS THE EVIDENCE`, and
`SUPERSEDED CAUSE -- KEPT VISIBLE because it is actionable and WRONG`. The tool
REFUSES to move any block whose heading says it should stay.

So the caller names the blocks to move with `--move POS[,POS...]`, after reading
`--list`. Everything else stays.

A POINTER replaces what left, naming the archive file and the kept range, because
`state.md`'s index points at the PART, and a reader who follows it must still be
able to reach the history.

    py -3 scripts/archive_state_subject.py --part .syndicate/state_mlb.md \\
        --subject mlb-ladders-native-builder --archive .syndicate/state_archive_2026-10-05.md
    ... --apply
    ... --list
    ... --allow-positional "Above it, only keys"

Exit 3 = refused, 2 = bad input, 0 = otherwise.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

NL = "\n"
POSITIONAL = re.compile(r"\b(above|earlier|previously|the previous update|further up)\b", re.I)
UPDATE_N = re.compile(r"UPDATE\s+(\d+)\b")
# A block can say in its OWN HEADING that it must stay, and no ordering rule can see
# that. Measured 2026-10-05: `- WHY -- the original diagnosis, kept because it is the
# evidence` and `SUPERSEDED CAUSE -- kept visible because it is actionable and WRONG`.
# A heading matching this is refused even when the caller names it in --move.
KEEPME = re.compile(r"kept because|kept so|kept visible|keep this|is the evidence|"
                    r"kept for the file", re.I)


def subject_span(lines: list[str], slug: str) -> tuple[int, int]:
    pat = re.compile(r"^## \[?" + re.escape(slug) + r"\]?\b")
    starts = [i for i, l in enumerate(lines) if pat.match(l)]
    if len(starts) != 1:
        raise SystemExit(f"REFUSED: expected exactly one '## [{slug}]' heading, found {len(starts)}")
    i = starts[0]
    j = next((k for k in range(i + 1, len(lines)) if lines[k].startswith("## ")), len(lines))
    return i, j


def block_number(heading: str) -> int | None:
    m = UPDATE_N.search(heading)
    return int(m.group(1)) if m else None


def block_date(body: list[str]) -> str:
    m = re.search(r"(20\d\d-\d\d-\d\d)", NL.join(body[:4]))
    return m.group(1) if m else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--part", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--list", action="store_true",
                    help="list the subject's sub-blocks with positions, and stop")
    ap.add_argument("--move", default="",
                    help="comma-separated POSITIONS to archive (from --list). Required to cut; "
                         "there is deliberately no 'newest N' default -- see the docstring.")
    ap.add_argument("--allow-positional", action="append", default=[],
                    help="override ONE positional-reference refusal by line substring (repeatable)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    part = pathlib.Path(args.part)
    arch = pathlib.Path(args.archive)
    if not part.exists():
        print(f"REFUSED: {part} does not exist.")
        return 2
    text = part.read_text(encoding="utf-8", errors="replace")
    lines = text.split(NL)
    i, j = subject_span(lines, args.subject)
    sec = lines[i:j]
    starts = [n for n, l in enumerate(sec) if l.startswith("### ")]
    blocks = []
    for k, n in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(sec)
        body = sec[n:end]
        blocks.append({"head": sec[n], "body": body, "num": block_number(sec[n]),
                       "date": block_date(body), "pos": k})

    print(f"=== {args.subject} ({part.name}) ===")
    if args.list or not args.move:
        print(f"  {len(blocks)} sub-block(s). Pass --move POS[,POS] to archive specific ones.")
        for b in blocks:
            tag = "KEEP-ME" if KEEPME.search(b["head"]) else ""
            print(f"    pos {b['pos']:>2} {len(NL.join(b['body'])):6}ch "
                  f"{b['date'] or '(undated)':10} {tag:7} {b['head'][4:86]}")
        if not args.move:
            print("  (no --move given; nothing to do)")
        return 0

    want = {int(x) for x in args.move.replace(" ", "").split(",") if x != ""}
    bad = sorted(want - {b["pos"] for b in blocks})
    if bad:
        print(f"  REFUSED: no such position(s): {bad}")
        return 2
    move = [b for b in blocks if b["pos"] in want]
    keep = [b for b in blocks if b["pos"] not in want]
    if not keep:
        print("  REFUSED: that would archive every sub-block; the subject would keep no history.")
        return 3
    protected = [b for b in move if KEEPME.search(b["head"])]
    if protected:
        print(f"  REFUSED: {len(protected)} selected block(s) say in their own heading that they")
        print( "  must stay. No ordering rule can see this; read them and reconsider.")
        for b in protected:
            print(f"    pos {b['pos']}: {b['head'][4:94]}")
        return 3

    moved_chars = sum(len(x) + 1 for b in move for x in b["body"])
    print(f"  archive {len(move)} of {len(blocks)} sub-blocks ({moved_chars:,} chars)")
    for b in move:
        print(f"    MOVE    pos {b['pos']:>2} {b['date'] or '(undated)':10} {b['head'][4:88]}")

    # --- refusals, all computed before any write -------------------------------
    refuse = []
    arch_nums = {b["num"] for b in move if b["num"] is not None}
    for b in keep:
        txt = NL.join(b["body"])
        for m in UPDATE_N.finditer(txt):
            if int(m.group(1)) in arch_nums:
                refuse.append(f"kept block (pos {b['pos']}) names archived UPDATE {m.group(1)}")
        for n_, line in enumerate(b["body"]):
            hit = POSITIONAL.search(line)
            if not hit:
                continue
            if any(ov and ov in line for ov in args.allow_positional):
                print(f"    allowed positional: {line.strip()[:96]}")
                continue
            refuse.append(f"kept block (pos {b['pos']}) positional '{hit.group(1)}': "
                          f"{line.strip()[:92]}")
    if refuse:
        print()
        print(f"  REFUSED -- {len(refuse)} dangling reference(s). The boundary is wrong, or the")
        print( "  phrase does not cross it; decide per sentence with --allow-positional.")
        for r in refuse:
            print(f"    {r}")
        return 3

    pre = sec[:starts[0]]
    pointer = (
        f"**{len(move)} SUPERSEDED SUB-BLOCK(S) ARCHIVED, NOT DELETED** — moved verbatim to "
        f"`{arch.name}` on 2026-10-05 by `scripts/archive_state_subject.py` "
        f"({moved_chars:,} chars). The other {len(keep)} stay below. The tool refused to cut "
        f"until no kept block referenced an archived one, by UPDATE number or by a positional "
        f"phrase. Read the archive for the full history."
    )
    kept_body = NL.join(NL.join(b["body"]).rstrip(NL) for b in keep)
    new_sec = pre + ["", pointer, ""] + kept_body.split(NL)
    new_lines = lines[:i] + new_sec + lines[j:]
    out = NL.join(new_lines).rstrip(NL) + NL

    moved_text = NL.join(NL.join(b["body"]).rstrip(NL) for b in move)
    banner = (f"{NL}{NL}## [{args.subject}] — archived from `{part.name}` 2026-10-05{NL}{NL}"
              f"{len(move)} sub-block(s), {moved_chars:,} chars, moved VERBATIM. Nothing "
              f"summarised. The live section in `{part.name}` keeps the other {len(keep)} and "
              f"points here.{NL}{NL}")
    prior = arch.read_text(encoding="utf-8", errors="replace") if arch.exists() else (
        f"# state archive — 2026-10-05{NL}{NL}Subjects' superseded sub-block history, moved "
        f"verbatim out of the COUNTED state files by `scripts/archive_state_subject.py`. "
        f"Archives are excluded from `STATE_TOTAL`; counted files are not. Nothing here is "
        f"deleted or summarised, and every live section points here.{NL}")
    new_arch = prior.rstrip(NL) + banner + moved_text + NL

    # conservation: nothing may end up in neither file
    before = [l for l in sec if l.strip()]
    after = set(out.split(NL)) | set(new_arch.split(NL))
    lost = [l for l in before if l not in after]
    if lost:
        print(f"  REFUSED: {len(lost)} non-blank line(s) would be in NEITHER file, e.g.")
        for l in lost[:3]:
            print(f"    {l[:96]}")
        return 3
    if not re.search(r"^## \[?" + re.escape(args.subject) + r"\]?\b", out, flags=re.M):
        print("  REFUSED: the subject's keyed heading would be lost.")
        return 3
    print(f"  checks pass: 0 dangling refs, 0 lines lost, keyed heading intact")
    print(f"  {part.name} {len(text):,} -> {len(out):,} chars   {arch.name} += {len(new_arch)-len(prior):,}")
    if not args.apply:
        print("  DRY RUN. Re-run with --apply.")
        return 0
    arch.write_text(new_arch, encoding="utf-8", newline=NL)
    part.write_text(out, encoding="utf-8", newline=NL)
    print("  WROTE both files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read and write a shared ledger file without altering a byte you did not mean to.

WHY THIS EXISTS. Two separate defects, both measured 2026-10-09 on `lanes.md` and
`lanes_history.md`, and they are easy to confuse:

1. THE READ SPLITS A MID-LINE BARE CR. `pathlib.read_text()` and a bare `open()`
   use UNIVERSAL NEWLINES, which maps a lone CR to LF. `lanes.md` contains exactly
   one mid-line bare CR -- inside a peer's verdict line -- so every tool that read
   it with universal newlines turned that line into TWO lines before doing any
   work. `74da0acd` had to repair that split once already, and
   the archive tool reproduced it while archiving the block.
2. THE WRITE CHURNS EVERY LINE ENDING. `write_text()` with no `newline=` uses the
   platform default, so on Windows it rewrote the whole 4MB `lanes_history.md`
   LF -> CRLF. Unstaged `git diff` showed that as 679 insertions / 0 deletions and
   hid it; the STAGED diff was 38,213 / 37,535, which is what got pushed.

The narrative trimmer in this family had fixed only #2 (`newline=LF` on write) and
still had #1, which is what a half-fix of this looks like.

THE CONTRACT. `read_ledger` returns (text, eol): the text with the file's dominant
line ending normalised to LF so ordinary `split("LF")` / `^...$` processing works,
and the eol it found. A bare CR is NOT a line ending and is left in place, so it
stays mid-line through the round trip. `write_ledger` puts the dominant ending
back and writes with `newline=""` so Python performs no translation of its own.

WHY NOT JUST PIN LF EVERYWHERE. Because `core.autocrlf=true` checks these files
out as CRLF, so pinning LF makes every tool run rewrite every line of the working
copy -- the same churn as #2, in the other direction. Preserving what is there
keeps a tool's diff to the lines it actually changed.

A REGEX CAUTION for callers, learned twice in one session: with MULTILINE, `.`
matches CR, so `^...$` on CRLF text swallows the CR into the match and
reassembling re-emits it as a BARE CR. Match the line body with a negated class
instead. After normalisation by `read_ledger` this does not arise, which is part
of why normalising is better than processing raw CRLF.
A NOTE ON NAMING SIBLINGS. `scripts/pending_deploys.py` builds a TRANSITIVE closure
of script basenames NAMED anywhere in runtime-reachable text, and demotes a
`scripts/` path to "owns no service" only when nothing names it. Mentioning a
sibling tool by basename in this docstring pulled that tool -- and, through its
text, a third one -- back into the closure, re-promoting pure ledger tooling to
runtime code. `tests/test_pending_deploys_runtime.py::test_pure_tooling_is_demoted`
caught it. Refer to the siblings by ROLE here, not by filename.
"""
from __future__ import annotations

import pathlib
import re

CR = chr(13)
LF = chr(10)
CRLF = CR + LF


def dominant_eol(raw: str) -> str:
    """The file's line ending, as found. CRLF only if it outnumbers bare LF."""
    crlf = raw.count(CRLF)
    bare_lf = raw.count(LF) - crlf
    return CRLF if crlf > bare_lf else LF


def read_ledger(path) -> tuple[str, str]:
    """(text normalised to LF, the file's own eol). A bare CR survives untouched."""
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        raw = fh.read()
    eol = dominant_eol(raw)
    # Replacing CRLF (not CR) is what leaves a LONE CR alone: it is not part of a
    # CRLF pair, so it is never matched and never becomes a line break.
    return (raw.replace(CRLF, LF) if eol == CRLF else raw), eol


def write_ledger(path, text: str, eol: str) -> None:
    """Write `text` (LF-normalised) back with `eol`, translating nothing else."""
    out = text.replace(LF, eol) if eol == CRLF else text
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)


def lone_cr_count(raw: str) -> int:
    """CRs that are not part of a CRLF -- the thing to assert is conserved."""
    return raw.count(CR) - raw.count(CRLF)
# A lane block ends at the next heading of level 1-3 -- NOT at the next level-3
# heading, and NOT at any heading whatsoever.
#
# BOTH halves of that are measured, and both mistakes have been made here.
#
# Bounding by the next `### ` alone: the LAST block in `lanes.md` then runs to
# EOF and swallows every trailing `## ` section. Done twice, a day apart, by the
# author of the rule against it -- 2026-10-13 a lane close rewrote 765 lines as
# 7, deleting 114,376 chars of `## Archive pointers` / `## Archived lanes`
# (caught by a line-count print, not by a guard); 2026-10-14 a verification
# harness read `signal-engine-wnba` as 785 lines / 120,001 chars instead of 12 /
# 4,101 and reported a correctly-moved block as ALTERED.
#
# Bounding by ANY heading (`#{1,6}`), which is what `learnings.md` 2026-10-13
# prescribes, overshoots: measured on `lanes_history.md`, it truncates 26 of 887
# archived blocks, one of them from 259 lines to 15, because those blocks
# legitimately contain `####` sub-headings. A heading DEEPER than the block's own
# level is CONTENT. `lanes.md` itself has 2 such lines and 0 of its 75 blocks
# contains one, so the two boundaries agree there and only the archive exposes
# the difference -- which is why the narrower rule has to be the default rather
# than a special case someone remembers.
#
# `scripts/check_trimmed_contracts.py` independently chose `^#{2,3}` for the same
# reason; this adds level 1 so a document's own title also closes a block.
_HEADING_1_3 = re.compile(r"^#{1,3}[ \t]")
_BLOCK_HEAD = re.compile(r"^###[ \t]+\**([a-z0-9][a-z0-9-]*)")
# ...AND A `#` LINE INSIDE A FENCED CODE BLOCK IS NOT A HEADING AT ALL.
# A column-0 `# comment` in a ```python block is byte-for-byte a level-1
# Markdown heading, and this module shipped blind to that on 2026-10-14.
# Measured the same day over 1,360 blocks in lanes.md + lanes_history.md +
# lanes_closed.md: 386 fenced lines, 1 of them a false boundary, and it
# truncated `soccer-projection-collapse` from its real 60 lines to 9 -- cut
# at `# syndicate/features/shared/board_enrichment.py:678`, a file path in a
# code sample. lanes.md has 0 fenced lines today, so a lane close that only
# needs `start` was never wrong; an ARCHIVE pass reading bodies out of
# lanes_history.md was. The narrower `^#{2,3}` that archive_released_lanes.py
# chose is immune to this one case and not to a `## ` line in a sample, so
# neither regex alone is the answer: the fence has to be tracked.
_FENCE = re.compile(r"^[ \t]*(```|~~~)")


def fenced_lines(lines):
    """Indices of lines INSIDE a fenced code block (fence lines excluded).

    Closes only on the fence character that opened, so a ``` sample inside a
    ~~~ block does not end it. An UNCLOSED fence makes every line to EOF
    fenced, which is the safe direction: a block then runs LONG (visible in
    any diff) rather than SHORT (silent, and the failure mode measured here).
    """
    inside = set()
    tok = None
    for i, line in enumerate(lines):
        m = _FENCE.match(line)
        if m:
            if tok is None:
                tok = m.group(1)
            elif line.strip().startswith(tok):
                tok = None
            continue
        if tok is not None:
            inside.add(i)
    return inside


def block_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    """slug -> [(start, end)] line spans of every `### <slug>` block, end-exclusive.

    `text` must be LF-normalised, i.e. what `read_ledger` returns. Lines
    inside a fenced code block are CONTENT: they neither start a block nor
    end one, so a `### foo` or a `# comment` in a code sample is invisible
    here. Duplicate slugs are RETURNED, not collapsed: one lane is supposed to have one block,
    and a caller that silently joined two would reproduce the defect this exists
    to prevent.
    """
    lines = text.split(LF)
    fenced = fenced_lines(lines)
    out: dict[str, list[tuple[int, int]]] = {}
    for i, line in enumerate(lines):
        m = _BLOCK_HEAD.match(line)
        if not m or i in fenced:
            continue
        end = next((j for j in range(i + 1, len(lines))
                    if _HEADING_1_3.match(lines[j]) and j not in fenced),
                   len(lines))
        out.setdefault(m.group(1), []).append((i, end))
    return out


def block_bounds(text: str, slug: str) -> tuple[int, int]:
    """The single (start, end) span for `slug`, end-exclusive.

    REFUSES rather than guesses: raises if the slug is absent, and raises if it
    appears more than once, because a duplicated lane block is itself a ledger
    defect and picking one of them hides it.
    """
    spans = block_spans(text).get(slug, [])
    if not spans:
        raise KeyError("no '### %s' block found" % slug)
    if len(spans) > 1:
        raise ValueError(
            "'### %s' appears %d times at lines %s -- one lane, one block; "
            "refusing to choose" % (slug, len(spans), [s + 1 for s, _ in spans])
        )
    return spans[0]


def block_text(text: str, slug: str) -> str:
    """The block's own lines, joined with LF. Same refusals as `block_bounds`."""
    start, end = block_bounds(text, slug)
    return LF.join(text.split(LF)[start:end])

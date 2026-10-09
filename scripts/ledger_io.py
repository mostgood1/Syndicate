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
